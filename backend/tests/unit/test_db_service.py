from services.db_service import DatabaseService


def test_request_hash_is_deterministic_without_supabase(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    db = DatabaseService()

    first = db.get_request_hash("prompt", "file.txt", 123)
    second = db.get_request_hash("prompt", "file.txt", 123)

    assert first == second
    assert first.startswith("h_")


def test_request_hash_changes_for_boundary_inputs(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    db = DatabaseService()

    assert db.get_request_hash("", None, 0) != db.get_request_hash("x", None, 0)
    assert db.get_request_hash("x", None, 0) != db.get_request_hash("x", "a.pdf", 0)


def test_report_cache_round_trip(monkeypatch, sample_report):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    db = DatabaseService()

    assert db.get_cached_report("missing") is None

    db.set_cached_report("h_1", sample_report)

    assert db.get_cached_report("h_1") == sample_report
