from __future__ import annotations

import asyncio
from enum import Enum
from typing import Any, Dict, Hashable, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from langgraph.graph import END, START, StateGraph

from schemas import DocumentMetadata, FinalReportJSON, NormalizedIntent, ValidationError
from services.db_service import DatabaseService
from services.gemini_service import GeminiReportingService


class FeedbackAction(str, Enum):
    NONE = "none"
    APPLY_CORRECTION = "apply_correction"
    CONSOLIDATE = "consolidate"


class AgentDocumentInput(BaseModel):
    file_base64: Optional[str] = Field(default=None, alias="fileBase64")
    file_name: Optional[str] = Field(default=None, alias="fileName")
    file_size: Optional[int] = Field(default=None, alias="fileSize")
    mime_type: Optional[str] = Field(default=None, alias="mimeType")  # computed from file_name if missing
    model_config = ConfigDict(populate_by_name=True)


class AgentState(BaseModel):
    # Inputs
    prompt: Optional[str] = None
    document: AgentDocumentInput = Field(default_factory=AgentDocumentInput)

    # User identity — injected by the API layer, used for user-scoped DB calls
    user_id: Optional[str] = None

    # Derived artifacts
    intent: Optional[NormalizedIntent] = None
    report: Optional[FinalReportJSON] = None

    # Memory (long-term style rules stored in Supabase)
    memory: str = "Apply standard professional reporting standards."

    # RAG: org-level knowledge base context (retrieved via vector search)
    org_knowledge: str = ""

    # Feedback evolution (short-term refinement vs long-term consolidation)
    feedback_action: FeedbackAction = FeedbackAction.NONE
    next_suggestion: Optional[str] = None
    feedback_history: List[str] = Field(default_factory=list)
    feedback_score: float = 1.0  # used when persisting audit logs during consolidation

    # Pending consolidation artifacts (produced by feedback_processing, applied in memory_update)
    pending_new_memory: Optional[str] = None
    pending_interaction_summary: Optional[str] = None

    # Guardrail routing
    low_signal: Optional[bool] = None
    status: Literal[
        "in_progress",
        "needs_clarification",
        "rejected_low_signal",
        "completed",
        "error",
    ] = "in_progress"
    clarification_question: Optional[str] = None
    rejection_reason: Optional[str] = None
    error: Optional[ValidationError] = None

    # Pre-extracted document text (set by prefetch_node, consumed by report_generation_node)
    document_text: Optional[str] = None

    # RAG source document names retrieved during prefetch (used in evidence_links)
    rag_sources: List[str] = Field(default_factory=list)

    # Idempotency helpers (avoid duplicated DB writes on retries)
    initial_intent_stored: bool = False


class AgentDeps:
    def __init__(self, gemini: GeminiReportingService, db: DatabaseService, rag=None):
        self.gemini = gemini
        self.db = db
        self.rag = rag  # RAGService | None


def _build_doc_metadata(doc: AgentDocumentInput) -> DocumentMetadata:
    """
    Mirror existing logic from the React client:
    - PDF => pdf
    - TXT/DOCX/others => txt fallback (backend schema only constrains values)
    """
    attached = bool(doc.file_base64)
    file_name = doc.file_name
    file_type = "none"
    if file_name:
        lower = file_name.lower()
        if lower.endswith(".pdf"):
            file_type = "pdf"
        elif lower.endswith(".docx"):
            file_type = "docx"
        elif lower.endswith(".txt"):
            file_type = "txt"
        else:
            file_type = "txt"
    elif attached:
        file_type = "txt"

    return DocumentMetadata(
        attached=attached,
        file_type=file_type,
        file_name=file_name,
        content=None,
        size=doc.file_size,
        low_signal=None,
    )


def _infer_mime_type(doc: AgentDocumentInput, doc_meta: DocumentMetadata) -> str:
    if doc.mime_type:
        return doc.mime_type
    return "application/pdf" if doc_meta.file_type == "pdf" else "text/plain"


def _route_after_ambiguity(state: AgentState) -> Hashable:
    if state.status == "error":
        return "error_node"
    if state.intent is None:
        return "error_node"
    if state.intent.is_ambiguous:
        return "clarification_node"
    return "prefetch"


def _route_after_prefetch(state: AgentState) -> Hashable:
    if state.status == "error":
        return "error_node"
    if state.low_signal is True:
        return "rejection_node"
    return "report_generation"


async def intent_normalization_node(state: AgentState, deps: AgentDeps) -> Dict[str, Any]:
    # Run normalization on:
    # - initial call (intent missing)
    # - explicit ambiguity retry (status == needs_clarification)
    # - explicit low-signal restart (status == rejected_low_signal)
    # - errors should be re-attempted only if caller resets them (status != error)
    if state.status not in ("needs_clarification", "rejected_low_signal") and state.intent is not None:
        # Keep existing intent when we're continuing refinement/consolidation.
        return {}

    if (not state.prompt or not state.prompt.strip()) and not state.document.file_base64:
        err = ValidationError(
            error_type="INVALID_PROMPT",
            message="Guardrail: Please provide a prompt or a document to analyze.",
        )
        return {
            "status": "error",
            "error": err,
        }

    if not state.prompt or not state.prompt.strip():
        # If a document is attached but no prompt, auto-generate a sensible default prompt.
        if state.document.file_base64:
            file_name = state.document.file_name or "the uploaded document"
            auto_prompt = f"Please analyze and generate a comprehensive professional report on {file_name}."
            # Mutate state prompt for downstream nodes via a shallow override approach
            state = state.model_copy(update={"prompt": auto_prompt})
        else:
            err = ValidationError(
                error_type="INVALID_PROMPT",
                message="Guardrail: Missing prompt text.",
            )
            return {"status": "error", "error": err}

    doc_meta = _build_doc_metadata(state.document)

    try:
        intent = await deps.gemini.normalize_intent(state.prompt, doc_meta)
    except Exception as e:
        # normalize_intent throws for unsupported tasks (see gemini_service)
        message = str(e)
        err_type = "IRRELEVANT" if "IRRELEVANT" in message else "UNSUPPORTED_TASK"
        err = ValidationError(error_type=err_type, message=message)
        return {"status": "error", "error": err}

    # Clear per-run guardrail outputs; downstream nodes decide next routing.
    result: Dict[str, Any] = {
        "intent": intent,
        "status": "in_progress",
        "clarification_question": None,
        "rejection_reason": None,
        "error": None,
        "low_signal": None,
        # Always persist the (possibly auto-generated) prompt so downstream nodes see it.
        "prompt": state.prompt,
    }
    return result


def ambiguity_check_node(state: AgentState) -> Dict[str, Any]:
    # This node intentionally does not call Gemini.
    # Guardrail routing is done via conditional edges based on intent.is_ambiguous.
    if state.status == "error":
        return {}
    if state.intent is None:
        err = ValidationError(error_type="AMBIGUOUS", message="Intent missing before ambiguity check.")
        return {"status": "error", "error": err}
    return {}


async def clarification_node(state: AgentState) -> Dict[str, Any]:
    question = (
        "Synthesis confidence is below 40%. Please clarify your specific analytical objective to ensure grounding accuracy."
    )
    if state.intent and state.intent.content_scope:
        question += f"\nSuggested scope: {state.intent.content_scope}"
    return {
        "status": "needs_clarification",
        "clarification_question": question,
        "rejection_reason": None,
        "error": None,
    }


async def prefetch_node(state: AgentState, deps: AgentDeps) -> Dict[str, Any]:
    """
    Parallel prefetch stage — runs after ambiguity_check, before report_generation.

    Concurrently executes:
      1. Signal check (document quality guardrail)
      2. User memory fetch (style preferences from DB)
      3. Org RAG context retrieval (vector search)
      4. Document text extraction (OCR / decode) — moved here from generate_report

    This eliminates sequential I/O that previously added 4-10 s before the
    Cohere generation call even started.
    """
    if state.status in ("needs_clarification", "rejected_low_signal", "error"):
        return {}

    if state.intent is None:
        err = ValidationError(error_type="LOW_SIGNAL", message="Intent missing before prefetch.")
        return {"status": "error", "error": err}

    # Refinement/consolidation: skip signal re-check and memory re-fetch;
    # document text is already in state from the original run.
    if state.feedback_action != FeedbackAction.NONE and state.report is not None:
        return {"low_signal": False, "status": "in_progress", "rejection_reason": None}

    doc_meta = _build_doc_metadata(state.document)
    mime_type = _infer_mime_type(state.document, doc_meta)

    # -----------------------------------------------------------------
    # Task 1 — Signal check (coroutine, not blocking)
    # -----------------------------------------------------------------
    async def _check_signal() -> bool:
        """Returns True if signal is OK (document has content), False if low-signal."""
        # No document → always OK
        if not state.document.file_base64:
            return True
        # PDFs are handled by vision — skip signal check (let OCR decide later)
        if doc_meta.file_type == "pdf":
            return True
        try:
            return await deps.gemini.check_document_signal(state.document.file_base64, mime_type)
        except Exception:
            return True  # Fail open

    # -----------------------------------------------------------------
    # Task 2 — User style memory from DB
    # -----------------------------------------------------------------
    async def _fetch_memory() -> str:
        try:
            return await deps.db.get_preferences(state.intent.detected_category, state.user_id or "")
        except Exception:
            return "Apply standard professional reporting standards."

    # -----------------------------------------------------------------
    # Task 3 — Org RAG context
    # -----------------------------------------------------------------
    async def _fetch_rag():
        """Returns (context_str, source_names_list)."""
        if not (deps.rag and state.user_id):
            return "", []
        try:
            profile_res = deps.db.supabase.table("user_profiles") \
                .select("organization_id") \
                .eq("id", state.user_id) \
                .execute() if deps.db.supabase else None
            org_id = None
            if profile_res and profile_res.data:
                org_id = profile_res.data[0].get("organization_id")
            if not org_id:
                return "", []
            search_query = state.prompt or (state.intent.content_scope if state.intent else "")
            ctx, sources = await deps.rag.retrieve_context(org_id, search_query)
            if ctx:
                from services.logger import logger
                logger.log(f"RAG: injecting {len(ctx)} chars of org context for org {org_id}, sources: {sources}", "success")
            return ctx or "", sources or []
        except Exception as rag_err:
            from services.logger import logger
            logger.log(f"RAG prefetch error (non-fatal): {rag_err}", "warn")
            return "", []

    # -----------------------------------------------------------------
    # Task 4 — Document text extraction (OCR / plain-text decode)
    # -----------------------------------------------------------------
    async def _extract_doc_text() -> str:
        if not state.document.file_base64:
            return ""
        try:
            text, _ = await deps.gemini.extract_document_text(
                file_base64=state.document.file_base64,
                mime_type=mime_type,
                file_name=doc_meta.file_name,
                file_type=doc_meta.file_type,
            )
            return text
        except Exception as ex:
            from services.logger import logger
            logger.log(f"prefetch_node: doc extraction error (non-fatal): {ex}", "warn")
            return ""

    # -----------------------------------------------------------------
    # Run all four tasks concurrently
    # -----------------------------------------------------------------
    from services.logger import logger
    logger.log("prefetch_node: launching signal-check + memory + RAG + OCR concurrently", "info")

    has_signal, memory, (org_knowledge, rag_sources), document_text = await asyncio.gather(
        _check_signal(),
        _fetch_memory(),
        _fetch_rag(),
        _extract_doc_text(),
    )

    logger.log("prefetch_node: all parallel tasks complete", "success")

    if not has_signal:
        return {
            "low_signal": True,
            "status": "rejected_low_signal",
            "rejection_reason": "Low Signal Detected: Provided asset lacks sufficient analytical signal.",
        }

    return {
        "low_signal": False,
        "status": "in_progress",
        "rejection_reason": None,
        "memory": memory,
        "org_knowledge": org_knowledge,
        "rag_sources": rag_sources,
        "document_text": document_text,
    }


async def report_generation_node(state: AgentState, deps: AgentDeps) -> Dict[str, Any]:
    if state.status in ("needs_clarification", "rejected_low_signal", "error"):
        return {}

    # Refinement/consolidation should operate on the existing report.
    # This mirrors the current UI behavior (refine without regenerating from scratch).
    if state.feedback_action != FeedbackAction.NONE and state.report is not None:
        return {}

    if state.intent is None:
        err = ValidationError(error_type="INVALID_PROMPT", message="Intent missing before report_generation.")
        return {"status": "error", "error": err}

    try:
        if not state.initial_intent_stored:
            # Mirrors your current UI: store request once, before generate-report.
            await deps.db.store_initial_intent(state.intent, state.user_id or "")
    except Exception:
        # DB failures should not block report generation.
        pass

    doc_meta = _build_doc_metadata(state.document)
    mime_type = _infer_mime_type(state.document, doc_meta)
    try:
        report = await deps.gemini.generate_report(
            intent=state.intent,
            file_base64=state.document.file_base64,
            memory_context=state.memory,
            mime_type=mime_type,
            org_knowledge=state.org_knowledge,
            document_text=state.document_text,  # pre-extracted by prefetch_node
            rag_sources=state.rag_sources,       # source file names for evidence_links
        )
    except Exception as e:
        msg = str(e)
        if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
            err_type = "QUOTA_EXCEEDED"
        elif "503" in msg or "UNAVAILABLE" in msg or "Failed to fetch" in msg or "Connection" in msg:
            err_type = "API_UNAVAILABLE"
        elif "parsing failed" in msg.lower() or "JSON" in msg:
            err_type = "PARSE_ERROR"
        else:
            err_type = "REPORT_GENERATION_ERROR"
        err = ValidationError(error_type=err_type, message=msg)
        return {"status": "error", "error": err}

    return {
        "report": report,
        "initial_intent_stored": True,
        "status": "completed",
    }


async def feedback_processing_node(state: AgentState, deps: AgentDeps) -> Dict[str, Any]:
    if state.status in ("needs_clarification", "rejected_low_signal", "error"):
        return {}

    if state.feedback_action == FeedbackAction.NONE:
        return {}

    if state.intent is None or state.report is None:
        err = ValidationError(error_type="INVALID_FORMAT", message="Missing intent/report before feedback_processing.")
        return {"status": "error", "error": err}

    # APPLY_CORRECTION: refine an existing report
    if state.feedback_action == FeedbackAction.APPLY_CORRECTION:
        if not state.next_suggestion or not state.next_suggestion.strip():
            err = ValidationError(error_type="INVALID_FORMAT", message="Missing suggestion for apply_correction.")
            return {"status": "error", "error": err}

        try:
            refined = await deps.gemini.refine_report(
                previous_report=state.report,
                suggestion=state.next_suggestion,
                intent=state.intent,
                memory_context=state.memory,
                org_knowledge=state.org_knowledge,
            )
        except Exception as e:
            msg = str(e)
            err_type = "QUOTA_EXCEEDED" if ("429" in msg or "quota" in msg.lower()) else "REFINEMENT_ERROR"
            err = ValidationError(error_type=err_type, message=msg)
            return {"status": "error", "error": err}

        new_hist = list(state.feedback_history)
        new_hist.append(state.next_suggestion)

        return {
            "report": refined,
            "feedback_history": new_hist,
            "next_suggestion": None,
            "feedback_action": FeedbackAction.NONE,
            "status": "completed",
        }

    # CONSOLIDATE: learn durable style rules from feedback history
    if state.feedback_action == FeedbackAction.CONSOLIDATE:
        try:
            extracted = await deps.gemini.extract_style_preferences(
                intent=state.intent,
                iterations=list(state.feedback_history),
                final_report=state.report,
                current_memory=state.memory,
            )
        except Exception as e:
            msg = str(e)
            err_type = "QUOTA_EXCEEDED" if ("429" in msg or "quota" in msg.lower()) else "CONSOLIDATION_ERROR"
            err = ValidationError(error_type=err_type, message=msg)
            return {"status": "error", "error": err}

        return {
            "pending_new_memory": extracted.get("newMemory") or state.memory,
            "pending_interaction_summary": extracted.get("interactionSummary") or "Session complete.",
            "status": "completed",
        }

    return {}


async def memory_update_node(state: AgentState, deps: AgentDeps) -> Dict[str, Any]:
    if state.status in ("needs_clarification", "rejected_low_signal", "error"):
        return {}

    if state.feedback_action != FeedbackAction.CONSOLIDATE:
        return {}

    if state.intent is None:
        err = ValidationError(error_type="INVALID_FORMAT", message="Intent missing before memory_update.")
        return {"status": "error", "error": err}

    if not state.pending_new_memory:
        err = ValidationError(error_type="INVALID_FORMAT", message="No pending_new_memory available for memory_update.")
        return {"status": "error", "error": err}

    try:
        await deps.db.update_preference(state.intent.detected_category, state.pending_new_memory, state.user_id or "")
    except Exception as e:
        # Memory update failure should not corrupt the report, but should be visible.
        err = ValidationError(error_type="MEMORY_UPDATE_ERROR", message=f"Memory consolidation failed: {e}")
        return {"status": "error", "error": err}

    try:
        await deps.db.store_interaction_summary(
            request_id=state.intent.request_id,
            category=state.intent.detected_category,
            summary=state.pending_interaction_summary or "Session complete.",
            score=float(state.feedback_score),
            user_id=state.user_id or "",
        )
    except Exception:
        # Audit failures should not block the update.
        pass

    return {
        "memory": state.pending_new_memory,
        "pending_new_memory": None,
        "pending_interaction_summary": None,
        "feedback_history": [],
        "feedback_action": FeedbackAction.NONE,
    }


def build_agent_graph(*, deps: AgentDeps) -> StateGraph:
    builder: StateGraph = StateGraph(AgentState)

    # Core pipeline nodes
    async def intent_normalization(state: AgentState) -> Dict[str, Any]:
        return await intent_normalization_node(state, deps)

    def ambiguity_check(state: AgentState) -> Dict[str, Any]:
        return ambiguity_check_node(state)

    async def clarification(state: AgentState) -> Dict[str, Any]:
        return await clarification_node(state)

    async def prefetch(state: AgentState) -> Dict[str, Any]:
        return await prefetch_node(state, deps)

    async def rejection(state: AgentState) -> Dict[str, Any]:
        return await rejection_node(state)

    async def report_generation(state: AgentState) -> Dict[str, Any]:
        return await report_generation_node(state, deps)

    async def feedback_processing(state: AgentState) -> Dict[str, Any]:
        return await feedback_processing_node(state, deps)

    async def memory_update(state: AgentState) -> Dict[str, Any]:
        return await memory_update_node(state, deps)

    def error_node(state: AgentState) -> Dict[str, Any]:
        # Error state is already stored by upstream nodes.
        return {"status": "error"}

    builder.add_node("intent_normalization", intent_normalization)
    builder.add_node("ambiguity_check", ambiguity_check)
    builder.add_node("clarification_node", clarification)
    builder.add_node("prefetch", prefetch)  # replaces signal_check + memory_fetch
    builder.add_node("rejection_node", rejection)
    builder.add_node("report_generation", report_generation)
    builder.add_node("feedback_processing", feedback_processing)
    builder.add_node("memory_update", memory_update)
    builder.add_node("error_node", error_node)

    builder.add_edge(START, "intent_normalization")
    builder.add_edge("intent_normalization", "ambiguity_check")

    builder.add_conditional_edges(
        "ambiguity_check",
        _route_after_ambiguity,
        {
            "clarification_node": "clarification_node",
            "prefetch": "prefetch",
            "error_node": "error_node",
        },
    )

    builder.add_edge("clarification_node", END)
    builder.add_edge("rejection_node", END)
    builder.add_edge("error_node", END)

    builder.add_conditional_edges(
        "prefetch",
        _route_after_prefetch,
        {
            "report_generation": "report_generation",
            "rejection_node": "rejection_node",
            "error_node": "error_node",
        },
    )

    builder.add_edge("report_generation", "feedback_processing")
    builder.add_edge("feedback_processing", "memory_update")
    builder.add_edge("memory_update", END)

    return builder


def compile_agent_graph(*, builder: StateGraph, checkpointer: Any) -> Any:
    """
    Caller-owned checkpointer so they can manage lifecycle (startup/shutdown) in FastAPI.
    """
    return builder.compile(checkpointer=checkpointer)

