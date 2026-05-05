import pytest

from schemas import InputMode
from services.gemini_service import GeminiReportingService


def make_service() -> GeminiReportingService:
    return GeminiReportingService()


def test_parse_response_accepts_markdown_fenced_json():
    svc = make_service()
    raw = """```json
{
  "report": {
    "hero_image_keyword": "finance",
    "executive_summary": "Summary",
    "highlights": ["A"],
    "risks_and_blockers": ["R"],
    "actions_required": ["Do it"],
    "evidence_links": ["source"],
    "diagrams": [{"title": "Flow", "mermaid_code": "flowchart TD\\n  A --> B"}],
    "additional_sections": [{"title": "Details", "content": "Body", "image_keyword": "chart"}]
  },
  "confidence_level": "high"
}
```"""

    report = svc._parse_response(raw, "req_1", InputMode.TEXT_ONLY)

    assert report.request_id == "req_1"
    assert report.status == "completed"
    assert report.source_type == "text"
    assert report.confidence_level == "high"
    assert report.report.highlights == ["A"]


def test_parse_response_uses_defaults_for_boundary_missing_fields():
    svc = make_service()

    report = svc._parse_response('{"report": {}, "confidence_level": "low"}', "req_2", InputMode.DOCUMENT_BASED)

    assert report.report.hero_image_keyword == "abstract"
    assert report.report.executive_summary == "Report generated."
    assert report.report.highlights == []
    assert report.source_type == "document"


def test_parse_response_strips_prefix_and_suffix_text():
    svc = make_service()
    raw = 'Here is the JSON: {"report": {"executive_summary": "Done"}, "confidence_level": "medium"} trailing'

    report = svc._parse_response(raw, "req_3", InputMode.TEXT_ONLY)

    assert report.report.executive_summary == "Done"
    assert report.confidence_level == "medium"


def test_parse_response_raises_on_invalid_json():
    svc = make_service()

    with pytest.raises(Exception, match="Analysis parsing failed"):
        svc._parse_response("not json", "req_bad", InputMode.TEXT_ONLY)
