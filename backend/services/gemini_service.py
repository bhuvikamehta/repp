import os
import json
import time
import random
import asyncio
import hashlib
from collections import OrderedDict
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
import cohere as cohere_lib
from dotenv import load_dotenv

from schemas import (
    NormalizedIntent, FinalReportJSON, TaskType, InputMode,
    DocumentMetadata, ReportContent, CustomSection, Constraints, Diagram
)
from .logger import logger

from pathlib import Path

env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# Cohere models — tried in order on rate-limit errors.
# Free tier: 5 RPM for command-r-plus, 20 RPM for command-r.
# Rate limits are per-MINUTE (not per-day), so a brief wait restores capacity.
# Full 128k context window usable — no TPM blocking.
COHERE_MODELS = [
    "command-r-plus-08-2024",  # Most capable — 5 RPM free
    "command-r-08-2024",       # Faster fallback — 20 RPM free
]
COHERE_MAX_OUTPUT_TOKENS = 4096


class GeminiReportingService:
    """
    AI Reporting Service — powered by Cohere with automatic model fallback.
    Public interface is identical to the previous Gemini/Groq implementation so
    no other file needs to change.
    """

    # Simple LRU cache for extracted document text (keyed by md5 of first 256 bytes of base64)
    # Avoids re-running heavy OCR when the same document is retried (e.g. on 429).
    _DOC_CACHE_MAX = 10

    def __init__(self):
        self.api_key = os.getenv("COHERE_API_KEY")
        if not self.api_key:
            logger.log("COHERE_API_KEY is missing from environment variables.", "error")
            print("CRITICAL WARNING: COHERE_API_KEY is missing in backend/.env. AI features will fail.")
        else:
            self.client = cohere_lib.ClientV2(api_key=self.api_key)
        # OrderedDict used as a simple LRU cache: key=doc_hash, value=(document_text, has_content)
        self._doc_text_cache: OrderedDict[str, Tuple[str, bool]] = OrderedDict()

    # ------------------------------------------------------------------
    # Internal helper: call Cohere (runs in thread via asyncio.to_thread)
    # ------------------------------------------------------------------
    def _call_groq(
        self,
        system_prompt: str,
        user_content: str,
        json_mode: bool = True,
        prime_json: bool = False,   # kept for call-site compatibility, no-op with Cohere
        max_tokens: int = 4096,
    ) -> str:
        """Calls Cohere API with automatic model fallback on rate-limit errors.

        Cohere advantages over Groq free tier:
        - Rate limits are RPM (per-minute), not TPD (per-day) — resets every minute.
        - No TPM token-count limit — full 128k context usable for large documents.
        - JSON mode is reliable — no HTTP 400 prefix-leak errors.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        response_format: Dict[str, Any] = (
            {"type": "json_object"} if json_mode else {"type": "text"}
        )

        max_tokens = min(max_tokens, COHERE_MAX_OUTPUT_TOKENS)

        last_exc = None
        for model in COHERE_MODELS:
            try:
                logger.log(f"Cohere: calling '{model}' (json_mode={json_mode}, max_tokens={max_tokens})", "api")
                response = self.client.chat(
                    model=model,
                    messages=messages,
                    response_format=response_format,
                    max_tokens=max_tokens,
                    temperature=0.3,
                )
                return response.message.content[0].text
            except Exception as e:
                err_str = str(e)
                # Skip to next model on rate limit errors only
                if any(k in err_str for k in ["429", "too_many_requests", "rate_limit", "rate limit"]):
                    logger.log(f"Cohere: '{model}' rate-limited — trying next model", "warn")
                    last_exc = e
                    continue
                raise e

        raise last_exc or Exception("All Cohere models are rate-limited. Please wait a moment and retry.")


    # ------------------------------------------------------------------
    # normalize_intent
    # ------------------------------------------------------------------
    async def normalize_intent(self, prompt: str, doc_meta: DocumentMetadata) -> NormalizedIntent:
        request_id = f"req_{int(time.time() * 1000)}"

        logger.log("Guardrail: Normalizing Intent & Assessing Scope", "api", {"prompt": prompt})

        system_prompt = """You are a Domain Guardrail Specialist.
Return ONLY a valid JSON object (no markdown, no explanation) with this exact schema:
{
  "is_supported": <boolean>,
  "confidence_score": <number 0.0-1.0>,
  "detected_category": <string>,
  "task_type": <"summary" | "report">,
  "input_mode": <"text_only" | "document_based">,
  "content_scope": <string>,
  "rejection_reason": <string or null>
}

Rules:
1. Classify the task as REPORTING_TASK (is_supported=true) or IRRELEVANT (is_supported=false) for chat, code, casual talk.
2. Score intent confidence (0.0 to 1.0). If goal is vague, score < 0.4.
3. CATEGORIZATION ARCHETYPES — do NOT use the document title as category name. Use consistent mid-level archetypes:
   - Scientific/Research documents -> 'Academic Research'
   - Presentation slides/summaries -> 'Business/Technical Presentation'
   - Lectures/educational notes -> 'Educational Material'
   - Job specs/resumes -> 'Employment Document'
   - Financial docs/audits -> 'Financial Report'
   - Manuals/tech docs -> 'Technical Documentation'
   - Industry-specific reports -> '[Industry Name] Industry' (e.g. 'Aerospace Industry')
4. Map the analytical scope precisely in content_scope."""

        user_content = (
            f"User Prompt: {prompt}\n"
            f"Document Context: {'Attached: ' + doc_meta.file_name if doc_meta.attached and doc_meta.file_name else 'None'}"
        )

        max_retries = 3
        for attempt in range(max_retries):
            try:
                # max_tokens=512: normalize_intent output is a small classification JSON
                # (~200 tokens). Keeping this low prevents 413 on llama-3.1-8b-instant
                # whose free-tier TPM is 6 000 (input ~400 + output 512 = ~912, well under limit).
                raw = await asyncio.to_thread(self._call_groq, system_prompt, user_content, True, False, 512)
                result = json.loads(raw)

                if not result.get("is_supported"):
                    logger.log("Guardrail: Task rejected (Out of Scope)", "guardrail", result.get("rejection_reason"))
                    raise Exception(result.get("rejection_reason") or "IRRELEVANT_TASK: This agent only handles analysis and reporting.")

                return NormalizedIntent(
                    request_id=request_id,
                    task_type=TaskType(result["task_type"]),
                    input_mode=InputMode(result["input_mode"]),
                    user_prompt=prompt,
                    detected_category=result.get("detected_category") or "Professional Analysis",
                    document_metadata=doc_meta,
                    content_scope=result["content_scope"],
                    confidence_score=result["confidence_score"],
                    is_ambiguous=result["confidence_score"] < 0.4,
                    is_supported=result["is_supported"],
                    constraints=Constraints(hallucination_allowed=False, output_structure_required=True),
                    timestamp=datetime.now().isoformat()
                )
            except Exception as e:
                error_str = str(e)
                # Re-raise guardrail/irrelevant errors immediately
                if "IRRELEVANT" in error_str or "UNSUPPORTED" in error_str:
                    logger.log(f"Guardrail Error: {error_str}", "error")
                    raise e
                if attempt < max_retries - 1:
                    # Exponential backoff with jitter: 2s, 4s (+jitter)
                    delay = 2 * (2 ** attempt) + random.uniform(0, 1)
                    logger.log(f"Groq normalize_intent error (attempt {attempt + 1}/{max_retries}): {error_str} — retrying in {delay:.1f}s", "warn")
                    await asyncio.sleep(delay)
                    continue
                logger.log(f"Guardrail Error: {error_str}", "error")
                raise e

    # ------------------------------------------------------------------
    # check_document_signal
    # Groq is text-only — for PDFs we rely on OCR. For non-PDF binary
    # documents we cannot check signal without vision, so we optimistically
    # return True to preserve existing behaviour.
    # ------------------------------------------------------------------
    async def check_document_signal(self, file_base64: str, mime_type: str) -> bool:
        logger.log("Guardrail: Checking Document Signal Strength (text-based via Groq)", "guardrail")

        try:
            is_pdf = (mime_type or "").lower() == "application/pdf"
            if is_pdf:
                from .ocr_service import extract_text_from_pdf_base64
                extracted = await asyncio.to_thread(extract_text_from_pdf_base64, file_base64)
                has_signal = bool(extracted and len(extracted.strip()) > 50)
                logger.log(f"Guardrail: PDF signal check via OCR → has_signal={has_signal}", "guardrail")
                return has_signal

            # For non-PDF types (plain text / docx) try to decode as UTF-8 text
            import base64 as b64lib
            raw_bytes = b64lib.b64decode(file_base64)
            try:
                text_content = raw_bytes.decode("utf-8", errors="ignore").strip()
                has_signal = len(text_content) > 50
                logger.log(f"Guardrail: Text signal check → has_signal={has_signal}", "guardrail")
                return has_signal
            except Exception:
                return True  # Cannot decode — optimistically allow
        except Exception:
            return True  # Fail open

    # ------------------------------------------------------------------
    # extract_document_text  (public — called from prefetch_node in parallel)
    # ------------------------------------------------------------------
    async def extract_document_text(
        self,
        file_base64: Optional[str],
        mime_type: Optional[str],
        file_name: Optional[str] = None,
        file_type: Optional[str] = None,
    ) -> Tuple[str, bool]:
        """
        Extract text from a document (PDF via OCR, or plain-text/notebook decode).
        Returns (document_text, has_content).

        Results are cached by a hash of the first 256 bytes of file_base64 to avoid
        re-running heavy OCR on the same document during retries.
        """
        if not file_base64:
            return "", False

        # --- Cache lookup ---
        cache_key = hashlib.md5(file_base64[:256].encode("utf-8", errors="ignore")).hexdigest()
        if cache_key in self._doc_text_cache:
            self._doc_text_cache.move_to_end(cache_key)  # LRU: mark as recently used
            logger.log("OCR cache hit — skipping re-extraction", "info")
            return self._doc_text_cache[cache_key]

        MAX_DOC_CHARS = 40_000  # Keep well within Cohere's context window
        document_text = ""
        has_document_content = False

        is_pdf = (mime_type or "").lower() == "application/pdf" or file_type == "pdf"

        if is_pdf:
            try:
                from .ocr_service import extract_text_from_pdf_base64
                logger.log("OCR: extracting text locally from PDF", "info")
                extracted_text = await asyncio.to_thread(extract_text_from_pdf_base64, file_base64)
                if extracted_text and extracted_text.strip():
                    if len(extracted_text) > MAX_DOC_CHARS:
                        extracted_text = extracted_text[:MAX_DOC_CHARS] + "\n...[document truncated for context limit]..."
                        logger.log(f"OCR: text truncated to {MAX_DOC_CHARS} chars", "warn")
                    document_text = extracted_text.strip()
                    has_document_content = True
                    logger.log(f"OCR: extracted {len(document_text)} chars from PDF", "success")
                else:
                    logger.log("OCR: extraction returned empty — will generate from intent/filename", "warn")
            except Exception as ocr_err:
                logger.log(f"OCR: local extraction failed ({ocr_err}) — will generate from intent/filename", "warn")
        else:
            # Non-PDF: detect file type and extract appropriately
            try:
                import base64 as b64lib
                raw_bytes = b64lib.b64decode(file_base64)
                raw_text = raw_bytes.decode("utf-8", errors="ignore").strip()

                fname = (file_name or "").lower()
                is_notebook = fname.endswith(".ipynb") or (
                    raw_text.startswith("{") and '"cell_type"' in raw_text[:500]
                )

                if is_notebook:
                    try:
                        nb = json.loads(raw_text)
                        cell_texts = []
                        for cell in nb.get("cells", []):
                            source = cell.get("source", [])
                            src = "".join(source) if isinstance(source, list) else str(source)
                            if src.strip():
                                prefix = "[MARKDOWN]" if cell.get("cell_type") == "markdown" else "[CODE]"
                                cell_texts.append(f"{prefix}\n{src.strip()}")
                        text_content = "\n\n".join(cell_texts)
                        logger.log(f"Notebook: extracted {len(cell_texts)} cells → {len(text_content)} chars", "success")
                    except Exception as nb_err:
                        logger.log(f"Notebook parse failed ({nb_err}) — using raw text", "warn")
                        text_content = raw_text
                else:
                    text_content = raw_text

                if text_content:
                    if len(text_content) > MAX_DOC_CHARS:
                        text_content = text_content[:MAX_DOC_CHARS] + "\n...[content truncated]..."
                    document_text = text_content
                    has_document_content = True
                    logger.log(f"Document text ready: {len(document_text)} chars", "success")
            except Exception as decode_err:
                logger.log(f"File decode failed ({decode_err}) — will generate from intent", "warn")

        result: Tuple[str, bool] = (document_text, has_document_content)

        # --- Cache store (LRU eviction) ---
        self._doc_text_cache[cache_key] = result
        self._doc_text_cache.move_to_end(cache_key)
        if len(self._doc_text_cache) > self._DOC_CACHE_MAX:
            self._doc_text_cache.popitem(last=False)  # evict oldest

        return result

    # ------------------------------------------------------------------
    # generate_report
    # ------------------------------------------------------------------
    async def generate_report(
        self,
        intent: NormalizedIntent,
        file_base64: Optional[str] = None,
        memory_context: str = "",
        mime_type: Optional[str] = None,
        org_knowledge: str = "",
        document_text: Optional[str] = None,  # pre-extracted by prefetch_node (avoids redundant OCR)
        rag_sources: Optional[List[str]] = None,  # source file names from RAG retrieval
    ) -> FinalReportJSON:

        override = intent.user_prompt
        long_term = memory_context or "Apply standard professional reporting standards."

        logger.log(f"Guardrail: Generating with Fact-Check Policy for domain: {intent.detected_category}", "api")

        # --- Step 1: Use pre-extracted text if provided, otherwise extract now ---
        has_document_content = False

        if document_text is not None:
            # Pre-extracted by prefetch_node — skip redundant OCR
            has_document_content = bool(document_text and document_text.strip())
            if has_document_content:
                logger.log(f"generate_report: using pre-extracted document text ({len(document_text)} chars)", "info")
            else:
                document_text = ""
        elif file_base64:
            # Fallback: extract inline (e.g. when called from legacy /generate-report endpoint)
            document_text, has_document_content = await self.extract_document_text(
                file_base64=file_base64,
                mime_type=mime_type,
                file_name=intent.document_metadata.file_name,
                file_type=intent.document_metadata.file_type,
            )
        else:
            document_text = ""

        # --- Step 2: Decide generation strategy ---
        # If we have real document content, use it as the primary source.
        # If not (OCR failed / empty file), fall back to knowledge-based generation
        # so the model doesn't return 'Not Found' for every field.
        effective_mode = intent.input_mode
        if file_base64 and not has_document_content:
            # OCR failed — degrade gracefully to knowledge-based
            effective_mode = InputMode.TEXT_ONLY
            logger.log("OCR produced no content — degrading to knowledge-based generation", "warn")

        if effective_mode == InputMode.DOCUMENT_BASED and has_document_content:
            hallucination_policy = (
                "1. DOCUMENT-ONLY: Every sentence in your report MUST be derived from the SOURCE DOCUMENT below. "
                "Do NOT add facts, context, or topics from your training data that are not in the document. "
                "If the document does not mention something, do not mention it either. "
                "Analyze, summarize, and paraphrase the document — do not invent content. "
                "Fill ALL JSON fields with content from the document; if a field truly cannot be populated "
                "from the document, write a brief statement about what the document covers instead."
            )
        else:
            hallucination_policy = (
                "1. KNOWLEDGE BASE: Use your extensive internal knowledge to generate a comprehensive, "
                "detailed, and highly informative report on the user's prompt and document topic. "
                "Generate rich, substantive content for EVERY field. Do NOT return 'Not Found' for any field."
            )

        # --- Step 3: Build prompts ---
        # Org knowledge is injected AFTER style rules but BEFORE the user document
        # so the model treats it as background context that can inform the report.
        org_context_section = ""
        if org_knowledge and org_knowledge.strip():
            org_context_section = (
                f"\n\n--- ORGANIZATIONAL CONTEXT (MANDATORY — READ AND APPLY) ---\n"
                f"The following passages are retrieved from your organization's knowledge base.\n"
                f"You MUST follow these rules when using this context:\n"
                f"\n"
                f"RULE 1 — TEMPLATE MATCHING (CRITICAL):\n"
                f"  Scan the organizational context for a PREFERRED REPORT TEMPLATES section.\n"
                f"  Identify which template best matches the report type (e.g., Quarterly Business Review,\n"
                f"  Incident Post-Mortem, Market Intelligence Brief, Sprint Summary).\n"
                f"  If a matching template is found, you MUST use its prescribed section order\n"
                f"  for the 'additional_sections' field. Each section in the template becomes\n"
                f"  one entry in additional_sections, in the exact order specified.\n"
                f"  Do NOT invent your own section names if a template exists.\n"
                f"\n"
                f"RULE 2 — COMPLETENESS:\n"
                f"  Do NOT summarize or omit items from the source data.\n"
                f"  Include ALL risks identified in the source (not just the top 3).\n"
                f"  Include ALL actions listed in the source (not just the top 3).\n"
                f"  Risks must follow the org format: [SEVERITY] Description. Impact. Mitigation. Owner.\n"
                f"  Actions must follow the org format: ACTION: description | Owner: role | Timeline: duration\n"
                f"\n"
                f"RULE 3 — STYLE COMPLIANCE:\n"
                f"  Apply all writing style, formatting, and domain-specific rules from the org standards.\n"
                f"  Key highlights must start with a quantified metric or action verb.\n"
                f"  Financial figures must include comparison to prior period and variance alerts where > 10%.\n"
                f"  Data classification tag must be noted in the executive summary opening line.\n"
                f"\n"
                f"ORGANIZATIONAL CONTEXT PASSAGES:\n"
                f"{org_knowledge}\n"
                f"--- END ORGANIZATIONAL CONTEXT ---"
            )
            logger.log(f"Org context injected: {len(org_knowledge)} chars", "info")

        # doc_section is appended LAST in the system prompt so the document content
        # is the freshest thing in context when the model generates the report.
        doc_section = ""
        if has_document_content:
            doc_section = (
                f"\n\n--- SOURCE DOCUMENT (analyze this ONLY, do NOT add outside knowledge) ---\n"
                f"{document_text}\n--- END OF SOURCE DOCUMENT ---"
            )

        # Template instruction goes OUTSIDE the JSON block (before it), not inside the schema.
        # Embedding instructions inside the JSON schema confuses the model into outputting invalid JSON.
        template_instruction = ""
        if org_knowledge:
            template_instruction = (
                "SECTION STRUCTURE INSTRUCTION: Before writing the JSON, identify the report type "
                "(QBR, Post-Mortem, Market Brief, Sprint Summary, etc.) from the user request. "
                "Then find the matching template in the ORGANIZATIONAL STANDARDS section above and use "
                "its prescribed sections IN ORDER for the 'additional_sections' array. "
                "Each template section becomes one object with title, content, and image_keyword. "
                "Do not invent section names if a template exists.\n"
            )

        # Build evidence_links instruction — always cite RAG source docs if retrieved
        rag_source_list = rag_sources or []
        if rag_source_list:
            rag_evidence_hint = (
                ", ".join(f'"[SOURCE: Org KB \u2014 {fn}]"' for fn in rag_source_list)
            )
            evidence_links_schema = (
                f'    "evidence_links": [{rag_evidence_hint}, "<[SOURCE: Internal \u2013 Dataset Name, Period]>"],\n'
            )
            evidence_instruction = (
                "EVIDENCE RULE: The following org knowledge documents were retrieved and used in this report. "
                "You MUST include each as a separate entry in evidence_links, "
                "formatted as [SOURCE: Org KB \u2013 <filename>]: "
                + ", ".join(rag_source_list) + ". "
                "Also add any internal data sources cited.\n"
            )
        else:
            evidence_links_schema = (
                '    "evidence_links": ["<[SOURCE: Internal \u2013 Dataset Name, Period]>","<source 2>"],\n'
            )
            evidence_instruction = ""

        system_prompt = (
            f"You are an expert Reporting Agent.\n"
            f"PII MASKING: Redact all names, emails, phone numbers, SSNs with [REDACTED].\n"
            f"Style rules: {long_term}\n"
            f"{org_context_section}\n"
            f"\nPOLICY:\n{hallucination_policy}\n"
            f"{evidence_instruction}"
            f"{template_instruction}"
            f"Focus scope: \"{intent.content_scope}\".\n"
            f"Bold all Big-O / formulas: **O(N^2)**.\n"
            f"Mermaid: use only --> and -->|label| arrows (never |> syntax).\n"
            f"\nYour response must be ONLY the following JSON object — no text before or after:\n"
            f'{{\n'
            f'  "report": {{\n'
            f'    "hero_image_keyword": "<one descriptive word>",\n'
            f'    "executive_summary": "<3-5 paragraphs prose only — no bullets. Open with [INTERNAL] classification tag. Para 1: purpose+scope. Para 2: critical finding. Para 3-5: context/caveats.>",\n'
            f'    "highlights": ["<start with metric: e.g. 23.4% revenue growth QoQ to $3.8M>","<metric-first finding 2>","<metric-first finding 3>","<metric-first finding 4>","<metric-first finding 5>"],\n'
            f'    "risks_and_blockers": ["<[SEVERITY] Description. Impact. Mitigation. Owner. — list ALL risks, not just 3>","<risk 2>","<risk 3>","<risk 4 if exists>","<risk 5 if exists>","<risk 6 if exists>"],\n'
            f'    "actions_required": ["<ACTION: desc | Owner: role | Timeline: date — list ALL actions>","<action 2>","<action 3>","<action 4 if exists>","<action 5 if exists>"],\n'
            + evidence_links_schema +
            f'    "diagrams": [{{"title": "<title>", "mermaid_code": "flowchart TD\\n  A[X] --> B[Y]"}}],\n'
            f'    "additional_sections": [\n'
            f'      {{"title": "<section 1 — use org template if available>", "content": "<detailed multi-paragraph analysis>", "image_keyword": "<word>"}},\n'
            f'      {{"title": "<section 2>", "content": "<detailed analysis>", "image_keyword": "<word>"}},\n'
            f'      {{"title": "<section 3 — MAX 5 SECTIONS TOTAL>", "content": "<analysis>", "image_keyword": "<word>"}}\n'
            f'    ]\n'
            f'  }},\n'
            f'  "confidence_level": "<high|medium|low>"\n'
            f'}}'
            f"{doc_section}"
        )

        if has_document_content:
            user_content = (
                f"Analyze the SOURCE DOCUMENT provided in the system prompt and generate the report JSON. "
                f"Your report must reflect ONLY what is in that document. "
                f"IMPORTANT: Keep additional_sections to a MAXIMUM of 5 entries. "
                f"Merge related topics into single sections rather than creating one section per subtopic. "
                f"Each section content should be 2-3 paragraphs maximum. "
                f"User objective: {override}"
            )
        else:
            user_content = (
                f"Generate the report JSON. Topic: {intent.detected_category}. Objective: {override}. "
                f"Keep additional_sections to a MAXIMUM of 5 entries."
            )

        max_retries = 3
        response_text = None
        last_error = None

        for attempt in range(max_retries):
            try:
                # json_mode=False: prevents Cohere from echoing document JSON back
                # when the input contains structured JSON (e.g. .ipynb notebooks).
                # _parse_response handles robust JSON extraction from the response.
                response_text = await asyncio.to_thread(
                    self._call_groq, system_prompt, user_content, False, False, COHERE_MAX_OUTPUT_TOKENS
                )
                last_error = None
                break
            except Exception as e:
                last_error = e
                error_str = str(e)
                logger.log(f"Groq generate_report error (attempt {attempt + 1}/{max_retries}): {error_str}", "error")
                if attempt < max_retries - 1:
                    # Exponential backoff with jitter: 4s → 8s (+jitter)
                    delay = 4 * (2 ** attempt) + random.uniform(0, 2)
                    logger.log(f"Retrying in {delay:.1f} seconds...", "warn")
                    await asyncio.sleep(delay)
                    continue
                raise e

        if response_text is not None and last_error is None:
            logger.log("Groq report generated successfully, parsing response.", "success")
            return self._parse_response(response_text, intent.request_id, effective_mode)

        logger.log("Using fallback mock report due to API issues", "warn")
        return self._generate_mock_report(intent.request_id, intent.input_mode)

    # ------------------------------------------------------------------
    # refine_report
    # ------------------------------------------------------------------
    async def refine_report(
        self,
        previous_report: FinalReportJSON,
        suggestion: str,
        intent: NormalizedIntent,
        memory_context: str = "",
        org_knowledge: str = "",
    ) -> FinalReportJSON:

        org_refinement_section = ""
        if org_knowledge and org_knowledge.strip():
            org_refinement_section = (
                f"\n\nORGANIZATIONAL STANDARDS (apply these while refining):\n"
                f"Follow all formatting, style, and completeness rules from the org standards below.\n"
                f"{org_knowledge}\n"
                f"--- END STANDARDS ---\n"
            )

        system_prompt = (
            f"You are an expert Reporting Agent in Refinement Mode, specialized in {intent.detected_category}.\n"
            f"Apply ONLY the user's correction. Preserve all other existing content.\n"
            f"PII MASKING: Redact all PII with [REDACTED].\n"
            f"{org_refinement_section}"
            f"\nYour response must be ONLY the following JSON object — no text before or after:\n"
            f'{{\n'
            f'  "report": {{\n'
            f'    "hero_image_keyword": "<keyword>",\n'
            f'    "executive_summary": "<detailed multi-paragraph summary>",\n'
            f'    "highlights": ["<h1>","<h2>","<h3>","<h4>","<h5>"],\n'
            f'    "risks_and_blockers": ["<r1>","<r2>","<r3>"],\n'
            f'    "actions_required": ["<a1>","<a2>","<a3>"],\n'
            f'    "evidence_links": ["<ref1>","<ref2>"],\n'
            f'    "diagrams": [{{"title": "<title>", "mermaid_code": "flowchart TD\\n  A --> B"}}],\n'
            f'    "additional_sections": [\n'
            f'      {{"title": "<title>", "content": "<content>", "image_keyword": "<word>"}},\n'
            f'      {{"title": "<title>", "content": "<content>", "image_keyword": "<word>"}}\n'
            f'    ]\n'
            f'  }},\n'
            f'  "confidence_level": "<high|medium|low>"\n'
            f'}}'
        )

        user_content = f"""HARD CONSTRAINTS: {memory_context}
NEW OVERRIDE: "{suggestion}"
PREVIOUS DATA: {json.dumps(previous_report.report.dict())}

CRITICAL: Apply the command while respecting existing grounding and bolding policies for the domain: {intent.detected_category}."""

        max_retries = 3
        response_text = None

        for attempt in range(max_retries):
            try:
                response_text = await asyncio.to_thread(self._call_groq, system_prompt, user_content, False, True)
                break
            except Exception as e:
                error_str = str(e)
                if attempt < max_retries - 1:
                    # Exponential backoff with jitter: 4s → 8s (+jitter)
                    delay = 4 * (2 ** attempt) + random.uniform(0, 2)
                    logger.log(f"Groq refine_report error (attempt {attempt + 1}/{max_retries}): {error_str} — retrying in {delay:.1f}s", "warn")
                    await asyncio.sleep(delay)
                    continue
                raise e

        return self._parse_response(
            response_text,
            previous_report.request_id,
            InputMode.DOCUMENT_BASED if previous_report.source_type == 'document' else InputMode.TEXT_ONLY
        )

    # ------------------------------------------------------------------
    # extract_style_preferences
    # ------------------------------------------------------------------
    async def extract_style_preferences(
        self,
        intent: NormalizedIntent,
        iterations: List[str],
        final_report: FinalReportJSON,
        current_memory: str
    ) -> Dict[str, str]:

        logger.log("Guardrail: Meta-Learning Feedback Integrity", "api")

        system_prompt = f"""You are an Eager Preference Learner.
Extract ANY preference, correction, or stylistic choice from the feedback history for the specific domain: {intent.detected_category}.
- ALWAYS incorporate the new feedback into the existing rules.
- NEVER ignore user feedback. Assume all changes are permanent preferences for this user.

Return ONLY a valid JSON object (no markdown) with this schema:
{{
  "preference_rules": "<updated combined style rules as a string>",
  "interaction_summary": "<brief summary of this session>"
}}"""

        user_content = f"""DOMAIN: {intent.detected_category}
EXISTING RULES: "{current_memory}"
FEEDBACK HISTORY: [{' THEN '.join(iterations)}]
SUCCESSFUL OUTPUT: {json.dumps(final_report.report.dict())[:1000]}"""

        max_retries = 3
        response_text = None

        for attempt in range(max_retries):
            try:
                response_text = await asyncio.to_thread(self._call_groq, system_prompt, user_content, True, False, 512)
                break
            except Exception as e:
                error_str = str(e)
                if attempt < max_retries - 1:
                    # Exponential backoff with jitter: 4s → 8s (+jitter)
                    delay = 4 * (2 ** attempt) + random.uniform(0, 2)
                    logger.log(f"Groq extract_style_preferences error (attempt {attempt + 1}/{max_retries}): {error_str} — retrying in {delay:.1f}s", "warn")
                    await asyncio.sleep(delay)
                    continue
                raise e

        try:
            res = json.loads(response_text or "{}")
            return {
                "newMemory": res.get("preference_rules") or current_memory,
                "interactionSummary": res.get("interaction_summary") or "Session complete."
            }
        except Exception:
            return {"newMemory": current_memory, "interactionSummary": "Session complete."}

    # ------------------------------------------------------------------
    # _parse_response
    # ------------------------------------------------------------------
    def _parse_response(self, json_str: Optional[str], id: str, mode: InputMode) -> FinalReportJSON:
        from datetime import datetime
        try:
            raw_text = json_str or "{}"

            # --- Robust JSON extraction ---
            # Strip markdown code fences
            if "```" in raw_text:
                # Extract content between first ``` and last ```
                parts = raw_text.split("```")
                for part in parts[1::2]:  # odd-indexed parts are inside fences
                    candidate = part.strip()
                    if candidate.startswith("json"):
                        candidate = candidate[4:].strip()
                    if candidate.startswith("{"):
                        raw_text = candidate
                        break

            # Strip any prefix text before the first '{' (model echoed document content)
            first_brace = raw_text.find("{")
            if first_brace > 0:
                logger.log(f"Parse: stripping {first_brace} chars of prefix text before JSON", "warn")
                raw_text = raw_text[first_brace:]

            # Strip any suffix text after the last '}'
            last_brace = raw_text.rfind("}")
            if last_brace != -1 and last_brace < len(raw_text) - 1:
                raw_text = raw_text[:last_brace + 1]

            # Sanitize literal control characters inside JSON string values.
            # Models sometimes output actual \n or \t bytes inside strings instead
            # of the escaped \\n / \\t sequences, which causes json.loads to raise
            # "Invalid control character" errors.
            import re as _re
            def _sanitize_json(s: str) -> str:
                # Replace literal control characters inside quoted strings only.
                # Strategy: replace \r\n and bare \n/\t/\r with their JSON escapes.
                s = s.replace('\r\n', '\\n').replace('\r', '\\n')
                # Only replace bare newlines/tabs that are NOT already escaped
                s = _re.sub(r'(?<!\\)\n', '\\\\n', s)
                s = _re.sub(r'(?<!\\)\t', '\\\\t', s)
                return s

            try:
                raw = json.loads(raw_text)
            except json.JSONDecodeError:
                # Try sanitizing control characters first
                sanitized = _sanitize_json(raw_text)
                try:
                    raw = json.loads(sanitized)
                except json.JSONDecodeError:
                    # --- Truncation recovery ---
                    # The model hit max_tokens mid-JSON. Walk back from the last
                    # complete '}' and try to close the structure minimally.
                    logger.log("Parse: attempting truncation recovery on incomplete JSON", "warn")
                    recovered = None
                    # Try progressively shorter tail cuts until we get valid JSON
                    # or run out of candidates. We add the minimum closing tokens
                    # needed: close current string, close object, close array(s), close root.
                    closers = [
                        '"}]}},"confidence_level":"medium"}',
                        '"]}},"confidence_level":"medium"}',
                        '}]},"confidence_level":"medium"}',
                        '}]},"confidence_level":"medium"}',
                        '}},"confidence_level":"medium"}',
                        '}',
                    ]
                    # Find the last safe truncation point — last complete closing }
                    for closer in closers:
                        candidate = sanitized.rstrip() + closer
                        try:
                            recovered = json.loads(candidate)
                            logger.log(f"Parse: truncation recovery succeeded with closer: {repr(closer)}", "success")
                            break
                        except json.JSONDecodeError:
                            continue
                    if recovered is None:
                        raise  # re-raise original decode error
                    raw = recovered

            data = raw.get("report") or raw
            return FinalReportJSON(
                request_id=id,
                status='completed',
                report=ReportContent(
                    hero_image_keyword=data.get("hero_image_keyword") or "abstract",
                    executive_summary=data.get("executive_summary") or "Report generated.",
                    highlights=data.get("highlights") if isinstance(data.get("highlights"), list) else [],
                    risks_and_blockers=data.get("risks_and_blockers") if isinstance(data.get("risks_and_blockers"), list) else [],
                    actions_required=data.get("actions_required") if isinstance(data.get("actions_required"), list) else [],
                    evidence_links=data.get("evidence_links") if isinstance(data.get("evidence_links"), list) else [],
                    diagrams=[Diagram(**s) for s in (data.get("diagrams") or [])],
                    additional_sections=[CustomSection(**s) for s in (data.get("additional_sections") or [])]
                ),
                source_type='document' if mode == InputMode.DOCUMENT_BASED else 'text',
                confidence_level=raw.get("confidence_level") or 'medium',
                generated_at=datetime.now().isoformat()
            )
        except Exception as e:
            logger.log(f"Parse Error: {e}", "error", {"raw": json_str})
            print(f"FAILED JSON: {json_str}")
            raise Exception(f"Analysis parsing failed: {e}")

    # ------------------------------------------------------------------
    # _generate_mock_report (fallback when API is unavailable)
    # ------------------------------------------------------------------
    def _generate_mock_report(self, request_id: str, input_mode: InputMode) -> FinalReportJSON:
        """Generate a mock report for demo purposes when API is unavailable."""
        from datetime import datetime
        return FinalReportJSON(
            request_id=request_id,
            status='completed',
            report=ReportContent(
                hero_image_keyword="business",
                executive_summary="This is a demo report generated due to API unavailability. In a production environment, this would contain actual analysis based on the provided content.",
                highlights=[
                    "Demo highlight 1: Key insights would be extracted here",
                    "Demo highlight 2: Important findings would be listed",
                    "Demo highlight 3: Actionable recommendations would be provided"
                ],
                risks_and_blockers=[
                    "Groq API temporarily unavailable — please retry",
                    "Check GROQ_API_KEY in backend/.env"
                ],
                actions_required=[
                    "Verify GROQ_API_KEY is set correctly in backend/.env",
                    "Check Groq API status at https://status.groq.com",
                    "Retry the request"
                ],
                evidence_links=[
                    "https://console.groq.com",
                    "https://console.groq.com/docs/openai"
                ],
                diagrams=[
                    Diagram(
                        title="System Architecture",
                        mermaid_code="graph TD\n    A[Frontend] --> B[Backend]\n    B --> C[Groq API]\n    C --> D[llama-3.3-70b-versatile]\n    D --> E[Report Output]"
                    )
                ],
                additional_sections=[
                    CustomSection(
                        title="Setup Instructions",
                        content="To enable full AI reporting, set GROQ_API_KEY in backend/.env. Get a free API key at https://console.groq.com.",
                        image_keyword="technology"
                    )
                ]
            ),
            source_type='document' if input_mode == InputMode.DOCUMENT_BASED else 'text',
            confidence_level='medium',
            generated_at=datetime.now().isoformat()
        )
