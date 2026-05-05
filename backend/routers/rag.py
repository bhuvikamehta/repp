"""
RAG Router — Organizational Knowledge Base Document Management

Endpoints:
  POST   /api/rag/documents          — Admin: upload a document (multipart)
  GET    /api/rag/documents          — Any org member: list uploaded docs
  DELETE /api/rag/documents/{doc_id} — Admin: delete a document (chunks cascade)
"""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any, Dict

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from dependencies import get_current_user
from .auth import supabase

router = APIRouter(prefix="/rag", tags=["rag"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_org_and_role(user_id: str) -> Dict[str, Any]:
    """Return {organization_id, role} for the given user, raising 400 if none."""
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not configured")
    res = supabase.table("user_profiles").select("organization_id, role").eq("id", user_id).execute()
    if not res.data or not res.data[0].get("organization_id"):
        raise HTTPException(status_code=400, detail="User does not belong to an organization")
    return res.data[0]


def _require_admin(user_id: str) -> str:
    """Return org_id if user is admin, else raise 403."""
    profile = _get_org_and_role(user_id)
    if profile.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return profile["organization_id"]


def _extract_text(content: bytes, filename: str, mime_type: str) -> str:
    """Extract plain text from uploaded bytes depending on file type."""
    name_lower = filename.lower()

    # ---- PDF ---------------------------------------------------------------
    if name_lower.endswith(".pdf") or mime_type == "application/pdf":
        try:
            from services.ocr_service import extract_text_from_pdf_base64
            b64 = base64.b64encode(content).decode()
            text = extract_text_from_pdf_base64(b64)
            return text or ""
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"PDF extraction failed: {e}")

    # ---- DOCX --------------------------------------------------------------
    if name_lower.endswith(".docx"):
        try:
            import io
            from docx import Document  # python-docx
            doc = Document(io.BytesIO(content))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except ImportError:
            raise HTTPException(
                status_code=500,
                detail="python-docx not installed. Run: pip install python-docx",
            )
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"DOCX extraction failed: {e}")

    # ---- Jupyter Notebook --------------------------------------------------
    if name_lower.endswith(".ipynb"):
        try:
            nb = json.loads(content.decode("utf-8", errors="ignore"))
            cells = []
            for cell in nb.get("cells", []):
                src = cell.get("source", [])
                text = "".join(src) if isinstance(src, list) else str(src)
                if text.strip():
                    prefix = "[MARKDOWN]" if cell.get("cell_type") == "markdown" else "[CODE]"
                    cells.append(f"{prefix}\n{text.strip()}")
            return "\n\n".join(cells)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Notebook extraction failed: {e}")

    # ---- Plain text (TXT, MD, CSV, etc.) -----------------------------------
    try:
        return content.decode("utf-8", errors="ignore").strip()
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Text decoding failed: {e}")


def _file_type_label(filename: str) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        return "pdf"
    if name.endswith(".docx"):
        return "docx"
    if name.endswith(".ipynb"):
        return "ipynb"
    return "txt"


# ---------------------------------------------------------------------------
# POST /api/rag/documents
# ---------------------------------------------------------------------------

@router.post("/documents")
async def upload_document(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Admin-only: upload an organizational document into the knowledge base."""
    org_id = _require_admin(user_id)

    content = await file.read()
    file_size = len(content)
    filename = file.filename or "document"
    mime_type = file.content_type or ""

    if file_size == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    # Extract text (may be slow for large PDFs — runs synchronously inside await)
    raw_text = await asyncio.to_thread(_extract_text, content, filename, mime_type)
    if not raw_text or not raw_text.strip():
        raise HTTPException(
            status_code=422,
            detail="Could not extract any text from the uploaded document.",
        )

    # Lazy-import to avoid circular deps (main.py wires rag_service onto app.state)
    from fastapi import Request  # noqa: F401 — not needed here, using app.state via trick
    import main as _main_module  # type: ignore

    rag_service = getattr(_main_module.app.state, "_rag_service", None)
    if rag_service is None:
        raise HTTPException(status_code=500, detail="RAG service not initialized")

    file_type = _file_type_label(filename)
    chunk_count = await rag_service.ingest_document(
        org_id=org_id,
        user_id=user_id,
        file_name=filename,
        file_type=file_type,
        file_size=file_size,
        raw_text=raw_text,
    )

    return {"message": "Document ingested successfully", "chunk_count": chunk_count}


# ---------------------------------------------------------------------------
# GET /api/rag/documents
# ---------------------------------------------------------------------------

@router.get("/documents")
async def list_documents(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Any org member: list all documents in the org knowledge base."""
    profile = _get_org_and_role(user_id)
    org_id = profile["organization_id"]

    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not configured")

    docs = await asyncio.to_thread(
        lambda: supabase.table("org_knowledge_docs")
        .select("id, file_name, file_type, file_size, chunk_count, created_at")
        .eq("organization_id", org_id)
        .order("created_at", desc=True)
        .execute()
    )
    return {"documents": docs.data or []}


# ---------------------------------------------------------------------------
# DELETE /api/rag/documents/{doc_id}
# ---------------------------------------------------------------------------

@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: str,
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Admin-only: delete a document and all its chunks (cascade)."""
    org_id = _require_admin(user_id)

    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not configured")

    # Verify the doc belongs to this org before deleting
    check = supabase.table("org_knowledge_docs").select("id").eq("id", doc_id).eq("organization_id", org_id).execute()
    if not check.data:
        raise HTTPException(status_code=404, detail="Document not found in your organization")

    supabase.table("org_knowledge_docs").delete().eq("id", doc_id).execute()
    return {"message": "Document deleted successfully"}
