"""
RAG Service — Cohere Embed v3 + Supabase pgvector

Responsibilities:
  1. chunk_text   — sliding-window text chunker
  2. embed_texts  — batch embed document chunks via Cohere embed-english-v3.0
  3. embed_query  — embed a single search query
  4. ingest_document — full pipeline: chunk → embed → store in Supabase
  5. retrieve_context — embed query → cosine search → return formatted top-k chunks
"""

from __future__ import annotations

import asyncio
import os
from typing import List, Optional, Tuple

import cohere as cohere_lib
from dotenv import load_dotenv
from pathlib import Path

from .logger import logger

env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# Cohere embed model — 1024-dim, free tier supported
_EMBED_MODEL = "embed-english-v3.0"

# Chunking parameters (in characters; ~4 chars ≈ 1 token)
_CHUNK_SIZE = 2000   # ~500 tokens per chunk
_OVERLAP    = 400    # ~100 tokens overlap between consecutive chunks

# How many chunks to retrieve per query
_TOP_K = 5


class RAGService:
    """Handles document ingestion (chunking + embedding) and semantic retrieval."""

    def __init__(self, db_service):
        """
        Args:
            db_service: DatabaseService instance (already initialised)
        """
        self._db = db_service
        api_key = os.getenv("COHERE_API_KEY")
        if not api_key:
            logger.log("RAGService: COHERE_API_KEY missing — embeddings will fail", "error")
            self._client = None
        else:
            self._client = cohere_lib.ClientV2(api_key=api_key)

    # ------------------------------------------------------------------
    # Public: ingest_document
    # ------------------------------------------------------------------
    async def ingest_document(
        self,
        org_id: str,
        user_id: str,
        file_name: str,
        file_type: str,
        file_size: Optional[int],
        raw_text: str,
    ) -> int:
        """
        Full ingestion pipeline.
        Returns the number of chunks stored.
        """
        if not raw_text or not raw_text.strip():
            logger.log("RAG ingest: empty text — nothing to store", "warn")
            return 0

        # 1. Chunk
        chunks = self.chunk_text(raw_text)
        logger.log(f"RAG ingest: '{file_name}' → {len(chunks)} chunks", "info")

        # 2. Embed (runs in thread to avoid blocking)
        embeddings = await asyncio.to_thread(self._embed_texts_sync, chunks)

        # 3. Store metadata row → get doc_id
        doc_id = await self._db.store_doc_metadata(
            org_id=org_id,
            user_id=user_id,
            file_name=file_name,
            file_type=file_type,
            file_size=file_size,
            chunk_count=len(chunks),
        )

        # 4. Bulk-store chunks + embeddings
        await self._db.store_chunks(
            doc_id=doc_id,
            org_id=org_id,
            chunks=chunks,
            embeddings=embeddings,
        )

        logger.log(f"RAG ingest: stored {len(chunks)} chunks for doc {doc_id}", "success")
        return len(chunks)

    # ------------------------------------------------------------------
    # Public: retrieve_context  (dual-retrieval)
    # ------------------------------------------------------------------
    async def retrieve_context(self, org_id: str, query: str) -> Tuple[str, List[str]]:
        """
        Dual-retrieval strategy:
          Pass A — DATA: top-5 chunks semantically closest to the user's query.
                         Catches relevant facts, metrics, project names, etc.
          Pass B — STANDARDS: top-5 chunks closest to a fixed anchor query that
                         always targets formatting rules, report templates, and
                         style guidelines — regardless of what the user asked.

        Both sets are deduplicated (by chunk text) and injected together so the
        model always sees both the relevant *data* AND the org *standards*.

        Returns:
            (context_text, source_file_names) — context_text is the formatted
            string for injection into the prompt; source_file_names is a
            deduplicated list of document file names that contributed chunks,
            used to populate evidence_links in the report.
        """
        if not query or not query.strip():
            return "", []
        try:
            # Embed both queries concurrently
            STANDARDS_ANCHOR = (
                "report formatting rules template structure style guidelines "
                "writing standards sections preferred report templates QBR"
            )
            data_vec, standards_vec = await asyncio.gather(
                asyncio.to_thread(self._embed_query_sync, query),
                asyncio.to_thread(self._embed_query_sync, STANDARDS_ANCHOR),
            )

            # Run both searches concurrently
            data_rows, standards_rows = await asyncio.gather(
                self._db.match_org_chunks(query_embedding=data_vec, org_id=org_id, top_k=5),
                self._db.match_org_chunks(query_embedding=standards_vec, org_id=org_id, top_k=5),
            )

            # Merge and deduplicate by chunk text
            seen: set = set()
            merged = []
            for row in (data_rows or []):
                t = row.get("chunk_text", "").strip()
                if t and t not in seen:
                    seen.add(t)
                    merged.append(("DATA", row))

            for row in (standards_rows or []):
                t = row.get("chunk_text", "").strip()
                if t and t not in seen:
                    seen.add(t)
                    merged.append(("STANDARDS", row))

            if not merged:
                logger.log(f"RAG retrieve: no chunks found for org {org_id}", "info")
                return "", []

            # Collect unique source file names (for evidence_links in the report)
            seen_sources: dict = {}  # file_name -> order of first appearance
            for _, row in merged:
                fn = (row.get("file_name") or "").strip()
                if fn and fn not in seen_sources:
                    seen_sources[fn] = len(seen_sources)
            source_file_names: List[str] = list(seen_sources.keys())

            # Format with clear labels + source attribution
            data_parts = []
            standards_parts = []
            for label, row in merged:
                text = row.get("chunk_text", "").strip()
                sim = row.get("similarity", 0)
                fn = (row.get("file_name") or "Org Knowledge Base").strip()
                entry = f"[source: {fn}] [relevance: {sim:.2f}]\n{text}"
                if label == "DATA":
                    data_parts.append(entry)
                else:
                    standards_parts.append(entry)

            sections = []
            if standards_parts:
                sections.append(
                    "=== ORGANIZATIONAL STANDARDS & TEMPLATES ===\n"
                    + "\n\n".join(standards_parts)
                )
            if data_parts:
                sections.append(
                    "=== RELEVANT DATA & CONTENT ===\n"
                    + "\n\n".join(data_parts)
                )

            context = "\n\n".join(sections)
            logger.log(
                f"RAG retrieve: {len(data_parts)} data + {len(standards_parts)} standards "
                f"chunks for org {org_id} (query: '{query[:50]}...') "
                f"sources: {source_file_names}",
                "success",
            )
            return context, source_file_names
        except Exception as e:
            logger.log(f"RAG retrieve error: {e}", "warn")
            return "", []

    # ------------------------------------------------------------------
    # Public: chunk_text
    # ------------------------------------------------------------------
    @staticmethod
    def chunk_text(text: str, chunk_size: int = _CHUNK_SIZE, overlap: int = _OVERLAP) -> List[str]:
        """
        Sliding-window character-level chunker.
        Tries to break at sentence boundaries ('. ') when possible.
        """
        text = text.strip()
        if not text:
            return []

        chunks: List[str] = []
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunk = text[start:end]

            # Try to snap end to last sentence boundary to avoid mid-sentence cuts
            if end < len(text):
                last_period = chunk.rfind(". ")
                if last_period > chunk_size // 2:  # Only snap if we're past half
                    end = start + last_period + 2  # include the '. '
                    chunk = text[start:end]

            chunks.append(chunk.strip())
            if end >= len(text):
                break
            start = end - overlap  # slide back by overlap amount

        return [c for c in chunks if c]

    # ------------------------------------------------------------------
    # Private: _embed_texts_sync (blocking, run in thread)
    # ------------------------------------------------------------------
    def _embed_texts_sync(self, texts: List[str]) -> List[List[float]]:
        """Batch-embed document chunks. Cohere free tier: 100 calls/min."""
        if not self._client:
            raise RuntimeError("Cohere client not initialized (missing API key)")

        # Cohere embed API supports up to 96 texts per call
        all_embeddings: List[List[float]] = []
        batch_size = 90
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            logger.log(
                f"RAG embed: batch {i // batch_size + 1} — {len(batch)} texts",
                "api",
            )
            response = self._client.embed(
                texts=batch,
                model=_EMBED_MODEL,
                input_type="search_document",
                embedding_types=["float"],
            )
            # response.embeddings is EmbedByTypeResponseEmbeddings; .float is the list
            batch_vecs = response.embeddings.float_
            all_embeddings.extend(batch_vecs)

        return all_embeddings

    # ------------------------------------------------------------------
    # Private: _embed_query_sync (blocking, run in thread)
    # ------------------------------------------------------------------
    def _embed_query_sync(self, query: str) -> List[float]:
        """Embed a single search query."""
        if not self._client:
            raise RuntimeError("Cohere client not initialized (missing API key)")

        response = self._client.embed(
            texts=[query],
            model=_EMBED_MODEL,
            input_type="search_query",
            embedding_types=["float"],
        )
        return response.embeddings.float_[0]
