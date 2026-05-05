from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from schemas import (
    Constraints,
    CustomSection,
    Diagram,
    DocumentMetadata,
    FinalReportJSON,
    InputMode,
    NormalizedIntent,
    ReportContent,
    TaskType,
)


@pytest.fixture
def sample_doc_meta() -> DocumentMetadata:
    return DocumentMetadata(attached=False, file_type="none")


@pytest.fixture
def sample_intent(sample_doc_meta: DocumentMetadata) -> NormalizedIntent:
    return NormalizedIntent(
        request_id="req_test",
        task_type=TaskType.REPORT,
        input_mode=InputMode.TEXT_ONLY,
        user_prompt="Create a revenue report.",
        detected_category="Financial Report",
        content_scope="Revenue performance",
        confidence_score=0.91,
        is_ambiguous=False,
        is_supported=True,
        constraints=Constraints(hallucination_allowed=False, output_structure_required=True),
        timestamp=datetime.now().isoformat(),
        document_metadata=sample_doc_meta,
    )


@pytest.fixture
def sample_report() -> FinalReportJSON:
    return FinalReportJSON(
        request_id="req_test",
        status="completed",
        source_type="text",
        confidence_level="high",
        generated_at=datetime.now().isoformat(),
        report=ReportContent(
            hero_image_keyword="finance",
            executive_summary="[INTERNAL] Revenue improved with manageable risk.",
            highlights=["12% revenue growth QoQ"],
            risks_and_blockers=["[LOW] Data latency. Impact minimal. Mitigation automate refresh. Owner Ops."],
            actions_required=["ACTION: Validate dataset | Owner: Analytics | Timeline: 1 week"],
            evidence_links=["[SOURCE: Internal - Q1 dataset]"],
            diagrams=[Diagram(title="Flow", mermaid_code="flowchart TD\n  A --> B")],
            additional_sections=[
                CustomSection(title="Revenue", content="Revenue details.", image_keyword="chart")
            ],
        ),
    )


class FakeResult:
    def __init__(self, data: list[dict[str, Any]] | None = None):
        self.data = data or []


class ChainTable:
    def __init__(self, result: FakeResult):
        self.result = result
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def select(self, *args: Any, **kwargs: Any) -> "ChainTable":
        self.calls.append(("select", args, kwargs))
        return self

    def eq(self, *args: Any, **kwargs: Any) -> "ChainTable":
        self.calls.append(("eq", args, kwargs))
        return self

    def order(self, *args: Any, **kwargs: Any) -> "ChainTable":
        self.calls.append(("order", args, kwargs))
        return self

    def insert(self, *args: Any, **kwargs: Any) -> "ChainTable":
        self.calls.append(("insert", args, kwargs))
        return self

    def update(self, *args: Any, **kwargs: Any) -> "ChainTable":
        self.calls.append(("update", args, kwargs))
        return self

    def delete(self, *args: Any, **kwargs: Any) -> "ChainTable":
        self.calls.append(("delete", args, kwargs))
        return self

    def execute(self) -> FakeResult:
        return self.result
