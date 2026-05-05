import asyncio

import pytest

from langgraph_agent import (
    AgentDeps,
    AgentDocumentInput,
    AgentState,
    FeedbackAction,
    _build_doc_metadata,
    _infer_mime_type,
    _route_after_ambiguity,
    _route_after_prefetch,
    ambiguity_check_node,
    clarification_node,
    feedback_processing_node,
    intent_normalization_node,
    report_generation_node,
)
from schemas import ValidationError


def test_build_doc_metadata_file_type_boundaries():
    assert _build_doc_metadata(AgentDocumentInput()).file_type == "none"
    assert _build_doc_metadata(AgentDocumentInput(fileName="a.PDF", fileBase64="x")).file_type == "pdf"
    assert _build_doc_metadata(AgentDocumentInput(fileName="a.docx", fileBase64="x")).file_type == "docx"
    assert _build_doc_metadata(AgentDocumentInput(fileName="a.txt", fileBase64="x")).file_type == "txt"
    assert _build_doc_metadata(AgentDocumentInput(fileName="a.csv", fileBase64="x")).file_type == "txt"


def test_infer_mime_type_prefers_explicit_value():
    doc = AgentDocumentInput(fileName="a.pdf", mimeType="application/custom")
    meta = _build_doc_metadata(doc)

    assert _infer_mime_type(doc, meta) == "application/custom"
    assert _infer_mime_type(AgentDocumentInput(fileName="a.pdf"), meta) == "application/pdf"


def test_routes_handle_valid_invalid_and_boundary_states(sample_intent):
    assert _route_after_ambiguity(AgentState(status="error")) == "error_node"
    assert _route_after_ambiguity(AgentState(intent=sample_intent)) == "prefetch"

    ambiguous = sample_intent.model_copy(update={"is_ambiguous": True})
    assert _route_after_ambiguity(AgentState(intent=ambiguous)) == "clarification_node"

    assert _route_after_prefetch(AgentState(status="error")) == "error_node"
    assert _route_after_prefetch(AgentState(low_signal=True)) == "rejection_node"
    assert _route_after_prefetch(AgentState(low_signal=False)) == "report_generation"


def test_intent_normalization_rejects_missing_prompt_and_document():
    result = asyncio.run(intent_normalization_node(AgentState(), AgentDeps(gemini=object(), db=object())))

    assert result["status"] == "error"
    assert result["error"].error_type == "INVALID_PROMPT"


def test_intent_normalization_valid_prompt_calls_gemini(sample_intent):
    class FakeGemini:
        async def normalize_intent(self, prompt, doc_meta):
            self.prompt = prompt
            self.doc_meta = doc_meta
            return sample_intent

    gemini = FakeGemini()

    result = asyncio.run(
        intent_normalization_node(
            AgentState(prompt="Create a QBR."),
            AgentDeps(gemini=gemini, db=object()),
        )
    )

    assert result["status"] == "in_progress"
    assert result["intent"] == sample_intent
    assert gemini.prompt == "Create a QBR."
    assert gemini.doc_meta.file_type == "none"


def test_ambiguity_check_errors_when_intent_missing():
    result = ambiguity_check_node(AgentState())

    assert result["status"] == "error"
    assert result["error"].error_type == "AMBIGUOUS"


def test_clarification_node_includes_scope(sample_intent):
    result = asyncio.run(clarification_node(AgentState(intent=sample_intent)))

    assert result["status"] == "needs_clarification"
    assert "Revenue performance" in result["clarification_question"]


def test_report_generation_maps_quota_error(sample_intent):
    class FakeGemini:
        async def generate_report(self, **kwargs):
            raise Exception("429 quota exceeded")

    class FakeDB:
        async def store_initial_intent(self, intent, user_id):
            pass

    result = asyncio.run(
        report_generation_node(
            AgentState(prompt="x", intent=sample_intent),
            AgentDeps(gemini=FakeGemini(), db=FakeDB()),
        )
    )

    assert result["status"] == "error"
    assert result["error"].error_type == "QUOTA_EXCEEDED"


def test_feedback_processing_requires_suggestion(sample_intent, sample_report):
    result = asyncio.run(
        feedback_processing_node(
            AgentState(
                intent=sample_intent,
                report=sample_report,
                feedback_action=FeedbackAction.APPLY_CORRECTION,
            ),
            AgentDeps(gemini=object(), db=object()),
        )
    )

    assert result["status"] == "error"
    assert result["error"].error_type == "INVALID_FORMAT"
