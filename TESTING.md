# Testing Guide

This project now has separate backend/frontend and unit/functional test suites.
All external Cohere and Supabase calls are mocked in normal tests, so the suite is safe to run locally and in CI.

## Commands

```bash
# Backend unit + functional tests
pytest -q backend/tests

# Frontend unit tests
npm run test:unit -- --run

# Frontend functional tests
npm run test:functional -- --run

# Production build check
npm run build
```

## Backend Unit Tests

`backend/tests/unit/test_pii_scrubber.py`
- Valid: masks email, phone, SSN, and credit-card-like values.
- Invalid/boundary: handles empty and `None` input without crashing.
- Clean case: leaves non-PII prompts unchanged.

`backend/tests/unit/test_db_service.py`
- Valid: verifies deterministic request hashing and report cache round trips.
- Boundary: verifies empty prompt/no file/zero-size inputs produce a valid hash.
- Invalid-ish variation: verifies hash changes when prompt or file changes.

`backend/tests/unit/test_rag_service.py`
- Valid: checks RAG retrieval merges data chunks and standards/template chunks.
- Boundary: blank text/query returns empty results; short text stays one chunk.
- Large boundary: long text splits into multiple overlapping chunks.

`backend/tests/unit/test_gemini_parse.py`
- Valid: parses normal model JSON and markdown-fenced JSON.
- Boundary: missing report fields get safe defaults.
- Invalid: malformed/non-JSON model output raises a parsing error.

`backend/tests/unit/test_langgraph_nodes.py`
- Valid: tests document metadata inference, routing, intent normalization, clarification, and error mapping.
- Invalid: missing prompt/document returns `INVALID_PROMPT`; missing intent returns `AMBIGUOUS`; missing correction suggestion returns `INVALID_FORMAT`.
- Boundary: unsupported file extensions fall back to `txt`; explicit MIME type wins; quota errors map to `QUOTA_EXCEEDED`.

`backend/tests/unit/test_rag_router_helpers.py`
- Valid: extracts text from plain text and notebooks.
- Boundary: unknown extension labels as `txt`.
- Invalid: malformed notebook raises HTTP 422.

## Backend Functional Tests

`backend/tests/functional/test_agent_api.py`
- Valid: `/agent/run` returns completed report and injects authenticated user ID.
- Valid security behavior: prompt PII is scrubbed before LangGraph receives it.
- Invalid: unauthenticated requests are rejected; graph startup failure returns HTTP 500.
- Boundary: `/agent/feedback` consolidation defaults missing score to `1.0`.
- Error path: graph exceptions normalize to `status="error"`.

`backend/tests/functional/test_reporting_endpoints.py`
- Valid: `/preferences/{category}`, `/check-document-signal`, and `/store-interaction`.
- Boundary: zero feedback score is accepted and passed through.
- Invalid: `/generate-report` service failure returns HTTP 500.

`backend/tests/functional/test_org_and_rag_api.py`
- Valid: admin can list organization members; member can list RAG docs.
- Invalid: user without organization gets HTTP 400; non-admin document deletion gets HTTP 403.

## Frontend Unit Tests

`tests/unit/Terminal.test.tsx`
- Valid: open terminal subscribes to logs and renders messages/payload details.
- Boundary: closed terminal renders nothing.
- Interaction: clear button clears logs; close button calls `onClose`.

`tests/unit/AuthViews.test.tsx`
- Valid: login navigates home; signup succeeds; organization creation displays invite code.
- Invalid: login and signup errors render user-facing messages.

## Frontend Functional Tests

`tests/functional/ReportingAgent.functional.test.tsx`
- Valid: prompt submission calls `/agent/run` with auth token and renders report sections.
- Invalid: empty prompt shows `INVALID_PROMPT`; unsupported file extension shows `INVALID_FORMAT`.
- Boundary/guardrail states: ambiguous backend response shows clarification UI; low-signal response shows rejection UI.

`tests/functional/AdminPanel.functional.test.tsx`
- Valid: loads org info, members, and knowledge-base documents.
- Valid: uploads a supported RAG document and deletes a document after confirmation.
- Invalid: unsupported admin upload extension shows an error.

## Supabase Key Cleanup

`backend/test_supa.py` no longer contains a hardcoded Supabase URL or JWT. It now reads:

```bash
SUPABASE_URL=... SUPABASE_KEY=... python backend/test_supa.py
```

If either variable is missing, the smoke test exits safely without touching Supabase.
