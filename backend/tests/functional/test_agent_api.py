from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

import dependencies
import main


class FakeGraph:
    def __init__(self, response: dict[str, Any]):
        self.response = response
        self.calls: list[tuple[dict[str, Any], dict[str, Any]]] = []

    async def ainvoke(self, update: dict[str, Any], config: dict[str, Any]):
        self.calls.append((update, config))
        return self.response


def make_client():
    main.app.dependency_overrides[main.get_current_user] = lambda: "user_123"
    main.app.dependency_overrides[dependencies.get_current_user] = lambda: "user_123"
    return TestClient(main.app)


def teardown_function():
    main.app.dependency_overrides.clear()
    if hasattr(main.app.state, "_langgraph_graph"):
        delattr(main.app.state, "_langgraph_graph")
    if hasattr(main.app.state, "_langgraph_init_error"):
        delattr(main.app.state, "_langgraph_init_error")


def test_agent_run_valid_completed_response(sample_intent, sample_report):
    graph = FakeGraph(
        {
            "prompt": "Create report",
            "intent": sample_intent.model_dump(mode="json"),
            "report": sample_report.model_dump(mode="json"),
            "status": "completed",
        }
    )
    main.app.state._langgraph_graph = graph
    client = make_client()

    response = client.post("/agent/run", json={"prompt": "Create report"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["thread_id"]
    assert body["report"]["request_id"] == "req_test"
    assert graph.calls[0][0]["user_id"] == "user_123"


def test_agent_run_scrubs_pii_before_graph(sample_intent):
    graph = FakeGraph(
        {
            "prompt": "Contact [REDACTED_EMAIL]",
            "intent": sample_intent.model_dump(mode="json"),
            "status": "needs_clarification",
            "clarification_question": "Clarify objective",
        }
    )
    main.app.state._langgraph_graph = graph
    client = make_client()

    response = client.post("/agent/run", json={"prompt": "Email test@example.com about revenue"})

    assert response.status_code == 200
    assert "test@example.com" not in graph.calls[0][0]["prompt"]
    assert "[REDACTED_EMAIL]" in graph.calls[0][0]["prompt"]


def test_agent_run_boundary_missing_graph_returns_500():
    main.app.state._langgraph_init_error = "startup failed"
    client = make_client()

    response = client.post("/agent/run", json={"prompt": "Create report"})

    assert response.status_code == 500
    assert response.json()["detail"] == "startup failed"


def test_agent_run_invalid_without_auth_override_is_rejected():
    client = TestClient(main.app)

    response = client.post("/agent/run", json={"prompt": "Create report"})

    assert response.status_code in {401, 403}


def test_agent_feedback_valid_consolidate_defaults_score(sample_intent, sample_report):
    graph = FakeGraph(
        {
            "intent": sample_intent.model_dump(mode="json"),
            "report": sample_report.model_dump(mode="json"),
            "status": "completed",
            "memory": "Updated style rules",
        }
    )
    main.app.state._langgraph_graph = graph
    client = make_client()

    response = client.post(
        "/agent/feedback",
        json={"thread_id": "thread_1", "feedback_action": "consolidate"},
    )

    assert response.status_code == 200
    assert response.json()["memory"] == "Updated style rules"
    assert graph.calls[0][0]["feedback_score"] == 1.0
    assert graph.calls[0][1]["configurable"]["thread_id"] == "thread_1"


def test_agent_feedback_invalid_graph_error_is_normalized():
    class ExplodingGraph:
        async def ainvoke(self, update, config):
            raise Exception("unsupported task")

    main.app.state._langgraph_graph = ExplodingGraph()
    client = make_client()

    response = client.post(
        "/agent/feedback",
        json={"thread_id": "thread_1", "feedback_action": "apply_correction", "next_suggestion": "shorter"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert response.json()["error"]["error_type"] == "UNSUPPORTED_TASK"
