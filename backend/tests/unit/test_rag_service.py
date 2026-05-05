import asyncio

from services.rag_service import RAGService


def test_chunk_text_returns_empty_for_blank_text():
    assert RAGService.chunk_text("") == []
    assert RAGService.chunk_text("   ") == []


def test_chunk_text_keeps_short_text_as_single_chunk():
    assert RAGService.chunk_text("Short report content.") == ["Short report content."]


def test_chunk_text_splits_long_text_with_overlap_boundary():
    text = "Sentence one. " * 400

    chunks = RAGService.chunk_text(text, chunk_size=200, overlap=40)

    assert len(chunks) > 1
    assert all(chunk.strip() for chunk in chunks)
    assert all(len(chunk) <= 220 for chunk in chunks)


def test_retrieve_context_merges_data_and_standards(monkeypatch):
    class FakeDB:
        async def match_org_chunks(self, query_embedding, org_id, top_k=5):
            if query_embedding == [1.0]:
                return [
                    {"chunk_text": "Revenue grew 12%.", "similarity": 0.91, "file_name": "q1.txt"},
                ]
            return [
                {"chunk_text": "Use QBR template.", "similarity": 0.88, "file_name": "standards.txt"},
                {"chunk_text": "Revenue grew 12%.", "similarity": 0.50, "file_name": "q1.txt"},
            ]

    svc = RAGService(FakeDB())
    monkeypatch.setattr(svc, "_embed_query_sync", lambda query: [2.0] if "formatting" in query else [1.0])

    context, sources = asyncio.run(svc.retrieve_context("org_1", "revenue report"))

    assert "ORGANIZATIONAL STANDARDS" in context
    assert "RELEVANT DATA" in context
    assert "Revenue grew 12%." in context
    assert "Use QBR template." in context
    assert sources == ["q1.txt", "standards.txt"]


def test_retrieve_context_returns_empty_for_blank_query():
    svc = RAGService(db_service=object())

    assert asyncio.run(svc.retrieve_context("org_1", "")) == ("", [])
