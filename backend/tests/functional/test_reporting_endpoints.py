from fastapi.testclient import TestClient

import dependencies
import main


def make_client():
    main.app.dependency_overrides[main.get_current_user] = lambda: "user_123"
    main.app.dependency_overrides[dependencies.get_current_user] = lambda: "user_123"
    return TestClient(main.app)


def teardown_function():
    main.app.dependency_overrides.clear()


def test_preferences_valid_category(monkeypatch):
    class FakeDB:
        async def get_preferences(self, category, user_id):
            assert category == "Financial Report"
            assert user_id == "user_123"
            return "Use concise executive summaries."

    monkeypatch.setattr(main, "db_service", FakeDB())
    client = make_client()

    response = client.get("/preferences/Financial Report")

    assert response.status_code == 200
    assert response.json() == {"preference_rules": "Use concise executive summaries."}


def test_generate_report_invalid_service_error(monkeypatch, sample_intent):
    class FakeGemini:
        async def generate_report(self, *args, **kwargs):
            raise Exception("model down")

    monkeypatch.setattr(main, "gemini_service", FakeGemini())
    client = make_client()

    response = client.post(
        "/generate-report",
        json={"intent": sample_intent.model_dump(mode="json"), "fileBase64": None, "memoryContext": ""},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "model down"


def test_check_document_signal_valid_true(monkeypatch):
    class FakeGemini:
        async def check_document_signal(self, file_base64, mime_type):
            assert file_base64 == "abc"
            assert mime_type == "text/plain"
            return True

    monkeypatch.setattr(main, "gemini_service", FakeGemini())
    client = make_client()

    response = client.post(
        "/check-document-signal",
        json={"fileBase64": "abc", "mimeType": "text/plain"},
    )

    assert response.status_code == 200
    assert response.json() == {"has_signal": True}


def test_store_interaction_boundary_zero_score(monkeypatch):
    calls = []

    class FakeDB:
        async def store_interaction_summary(self, request_id, category, summary, score, user_id):
            calls.append((request_id, category, summary, score, user_id))

    monkeypatch.setattr(main, "db_service", FakeDB())
    client = make_client()

    response = client.post(
        "/store-interaction",
        json={"requestId": "req_1", "category": "general", "summary": "done", "score": 0},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    assert calls == [("req_1", "general", "done", 0.0, "user_123")]
