import os
from typing import Optional, Dict, List, Any
from datetime import datetime
from supabase import create_client, Client
from dotenv import load_dotenv

from schemas import NormalizedIntent, FinalReportJSON
from .logger import logger

from pathlib import Path

env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

class DatabaseService:
    def __init__(self):
        self.supabase: Optional[Client] = None
        self.cache: Dict[str, FinalReportJSON] = {}
        
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        
        if url and key:
            try:
                self.supabase = create_client(url, key)
                logger.log("Supabase Client initialized", "db")
            except Exception as e:
                logger.log("Supabase connectivity error", "error", e)
        else:
             logger.log("Supabase credentials missing in .env", "warn")

    def get_request_hash(self, prompt: str, file_name: Optional[str], size: Optional[int]) -> str:
        raw = f"{prompt}:{file_name or 'none'}:{size or 0}"
        hash_val = 0
        for char in raw:
            hash_val = ((hash_val << 5) - hash_val) + ord(char)
            hash_val |= 0  # 32bit integer
        return f"h_{hash_val}"

    def get_cached_report(self, hash_val: str) -> Optional[FinalReportJSON]:
        return self.cache.get(hash_val)

    def set_cached_report(self, hash_val: str, report: FinalReportJSON) -> None:
        self.cache[hash_val] = report

    async def store_initial_intent(self, intent: NormalizedIntent, user_id: str) -> None:
        if not self.supabase:
            return
        logger.log(f"Logging initial intent: {intent.request_id}", "db")
        try:
            self.supabase.table('agent_requests').insert({
                "request_id": intent.request_id,
                "task_type": intent.task_type.value,
                "input_mode": intent.input_mode.value,
                "user_prompt": intent.user_prompt,
                "detected_category": intent.detected_category,
                "document_metadata": intent.document_metadata.model_dump(mode='json') if hasattr(intent.document_metadata, 'model_dump') else intent.document_metadata.dict(),
                "user_id": user_id
            }).execute()
        except Exception as e:
            logger.log("Failed to log request intent to DB", "warn", str(e))

    async def get_preferences(self, category: str, user_id: str) -> str:
        logger.log(f"Fetching rules for domain: {category}", "db")
        default_rule = "Apply standard professional reporting standards."
        
        if not self.supabase:
            return default_rule
        
        try:
            response = self.supabase.table('agent_preferences').select('preference_rules').eq('category', category).eq('user_id', user_id).execute()
            data = response.data
            
            if data and len(data) > 0:
                logger.log("Domain-specific rules found", "success")
                return data[0]['preference_rules']

            logger.log("Domain rules not found, falling back to general", "info")
            response_gen = self.supabase.table('agent_preferences').select('preference_rules').eq('category', 'general').eq('user_id', user_id).execute()
            general = response_gen.data
            
            return general[0]['preference_rules'] if general and len(general) > 0 else default_rule
        except Exception as e:
            logger.log(f"Error fetching rules: {e}", "warn")
            return default_rule

    async def update_preference(self, category: str, rules: str, user_id: str) -> None:
        logger.log(f"Updating memory for category: {category}", "db")
        if not self.supabase:
            return

        try:
            existing_response = self.supabase.table('agent_preferences').select('interaction_count, confidence_weight').eq('category', category).eq('user_id', user_id).execute()
            existing = existing_response.data

            if existing and len(existing) > 0:
                row = existing[0]
                self.supabase.table('agent_preferences').update({
                    "preference_rules": rules,
                    "interaction_count": (row.get('interaction_count') or 0) + 1,
                    "confidence_weight": min((row.get('confidence_weight') or 1.0) + 0.1, 5.0),
                    "last_updated": datetime.now().isoformat()
                }).eq('category', category).eq('user_id', user_id).execute()
            else:
                self.supabase.table('agent_preferences').insert({
                    "category": category,
                    "preference_rules": rules,
                    "confidence_weight": 1.0,
                    "interaction_count": 1,
                    "user_id": user_id
                }).execute()
            logger.log("Long-term memory updated in database", "success")
        except Exception as e:
            logger.log("Preference memory update failed", "error", str(e))

    async def store_interaction_summary(self, request_id: str, category: str, summary: str, score: float, user_id: str) -> None:
        if not self.supabase:
            return
        logger.log(f"Persisting interaction audit log for {request_id}", "db")
        try:
            self.supabase.table('agent_interactions').insert({
                "request_id": request_id,
                "category": category,
                "interaction_summary": summary,
                "feedback_score": int(round(score)),
                "user_id": user_id
            }).execute()
        except Exception as e:
            logger.log("Outcome summary logging failed", "warn", str(e))

    # ------------------------------------------------------------------
    # RAG: Org Knowledge Base
    # ------------------------------------------------------------------

    async def store_doc_metadata(
        self,
        org_id: str,
        user_id: str,
        file_name: str,
        file_type: str,
        file_size: Optional[int],
        chunk_count: int,
    ) -> str:
        """Insert a row into org_knowledge_docs. Returns the new doc UUID."""
        if not self.supabase:
            raise RuntimeError("Supabase not configured")
        result = self.supabase.table("org_knowledge_docs").insert({
            "organization_id": org_id,
            "uploaded_by": user_id,
            "file_name": file_name,
            "file_type": file_type,
            "file_size": file_size,
            "chunk_count": chunk_count,
        }).execute()
        doc_id = result.data[0]["id"]
        logger.log(f"RAG DB: stored doc metadata → doc_id={doc_id}", "db")
        return doc_id

    async def store_chunks(
        self,
        doc_id: str,
        org_id: str,
        chunks: List[str],
        embeddings: List[List[float]],
    ) -> None:
        """Bulk-insert chunk rows with embeddings into org_knowledge_chunks."""
        if not self.supabase:
            raise RuntimeError("Supabase not configured")
        rows = [
            {
                "doc_id": doc_id,
                "organization_id": org_id,
                "chunk_index": i,
                "chunk_text": chunk,
                "embedding": emb,  # list[float] — Supabase accepts JSON arrays for vector
            }
            for i, (chunk, emb) in enumerate(zip(chunks, embeddings))
        ]
        # Supabase Python client accepts list of dicts; pgvector column accepts JSON float array
        self.supabase.table("org_knowledge_chunks").insert(rows).execute()
        logger.log(f"RAG DB: inserted {len(rows)} chunks for doc {doc_id}", "db")

    async def list_org_docs(self, org_id: str) -> List[Dict[str, Any]]:
        """Return doc metadata list (no embeddings) ordered newest first."""
        if not self.supabase:
            return []
        result = (
            self.supabase.table("org_knowledge_docs")
            .select("id, file_name, file_type, file_size, chunk_count, created_at")
            .eq("organization_id", org_id)
            .order("created_at", desc=True)
            .execute()
        )
        return result.data or []

    async def delete_org_doc(self, doc_id: str, org_id: str) -> None:
        """Delete a doc record; chunks cascade automatically via FK."""
        if not self.supabase:
            raise RuntimeError("Supabase not configured")
        self.supabase.table("org_knowledge_docs").delete().eq("id", doc_id).eq("organization_id", org_id).execute()
        logger.log(f"RAG DB: deleted doc {doc_id}", "db")

    async def match_org_chunks(
        self,
        query_embedding: List[float],
        org_id: str,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Call the Supabase RPC `match_org_chunks` which does cosine ANN search.
        Returns list of {chunk_text, similarity} dicts.
        """
        if not self.supabase:
            return []
        try:
            result = self.supabase.rpc(
                "match_org_chunks",
                {
                    "query_embedding": query_embedding,
                    "match_org_id": org_id,
                    "match_count": top_k,
                },
            ).execute()
            return result.data or []
        except Exception as e:
            logger.log(f"RAG DB: match_org_chunks RPC failed: {e}", "warn")
            return []
