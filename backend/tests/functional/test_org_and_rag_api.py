from fastapi.testclient import TestClient

import dependencies
import main
from backend.tests.conftest import ChainTable, FakeResult
from routers import org as org_router
from routers import rag as rag_router


class FakeSupabase:
    def __init__(self, table_results):
        self.table_results = table_results
        self.tables = []

    def table(self, name):
        self.tables.append(name)
        result = self.table_results.get(name, FakeResult([]))
        return ChainTable(result)


def make_client():
    main.app.dependency_overrides[dependencies.get_current_user] = lambda: "user_admin"
    main.app.dependency_overrides[main.get_current_user] = lambda: "user_admin"
    return TestClient(main.app)


def teardown_function():
    main.app.dependency_overrides.clear()
    org_router.supabase = None
    rag_router.supabase = None


def test_org_members_admin_valid(monkeypatch):
    fake = FakeSupabase(
        {
            "user_profiles": FakeResult(
                [{"id": "user_admin", "organization_id": "org_1", "role": "admin", "email": "a@test.com"}]
            ),
            "organizations": FakeResult([{"name": "Acme", "code": "ABC12345"}]),
        }
    )
    org_router.supabase = fake
    client = make_client()

    response = client.get("/api/org/members")

    assert response.status_code == 200
    body = response.json()
    assert body["organization"]["name"] == "Acme"
    assert body["members"][0]["email"] == "a@test.com"


def test_org_members_invalid_no_organization():
    org_router.supabase = FakeSupabase({"user_profiles": FakeResult([{"organization_id": None, "role": "member"}])})
    client = make_client()

    response = client.get("/api/org/members")

    assert response.status_code == 400
    assert response.json()["detail"] == "User does not belong to an organization"


def test_rag_list_documents_valid_member():
    rag_router.supabase = FakeSupabase(
        {
            "user_profiles": FakeResult([{"organization_id": "org_1", "role": "member"}]),
            "org_knowledge_docs": FakeResult(
                [{"id": "doc_1", "file_name": "kb.txt", "file_type": "txt", "file_size": 10, "chunk_count": 1}]
            ),
        }
    )
    client = make_client()

    response = client.get("/api/rag/documents")

    assert response.status_code == 200
    assert response.json()["documents"][0]["file_name"] == "kb.txt"


def test_rag_delete_document_invalid_non_admin():
    rag_router.supabase = FakeSupabase({"user_profiles": FakeResult([{"organization_id": "org_1", "role": "member"}])})
    client = make_client()

    response = client.delete("/api/rag/documents/doc_1")

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin access required"
