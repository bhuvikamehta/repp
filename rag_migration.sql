-- ============================================================
-- RAG Knowledge Base Migration
-- Run this in your Supabase SQL Editor (one-time setup)
-- ============================================================

-- 1. Enable pgvector extension (built-in on Supabase, free)
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Parent table: one row per uploaded file (metadata only, no embeddings here)
CREATE TABLE IF NOT EXISTS public.org_knowledge_docs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    uploaded_by UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    file_name TEXT NOT NULL,
    file_type TEXT NOT NULL,        -- 'pdf' | 'docx' | 'txt'
    file_size INTEGER,
    chunk_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now() NOT NULL
);

-- 3. Child table: one row per text chunk, stores the 1024-dim Cohere embedding
CREATE TABLE IF NOT EXISTS public.org_knowledge_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id UUID NOT NULL REFERENCES public.org_knowledge_docs(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding vector(1024),         -- Cohere embed-english-v3.0 dimension
    created_at TIMESTAMPTZ DEFAULT now() NOT NULL
);

-- 4. IVFFlat index for fast approximate cosine similarity search
--    (lists=50 is a good starting point; increase to 100+ for >10k chunks)
CREATE INDEX IF NOT EXISTS org_chunks_embedding_idx
    ON public.org_knowledge_chunks
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 50);

-- 5. Row Level Security
ALTER TABLE public.org_knowledge_docs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.org_knowledge_chunks ENABLE ROW LEVEL SECURITY;

-- org_knowledge_docs policies
CREATE POLICY "Org members read docs"
    ON public.org_knowledge_docs FOR SELECT
    USING (
        organization_id IN (
            SELECT organization_id FROM public.user_profiles WHERE id = auth.uid()
        )
    );

CREATE POLICY "Admins insert docs"
    ON public.org_knowledge_docs FOR INSERT
    WITH CHECK (
        organization_id IN (
            SELECT organization_id FROM public.user_profiles
            WHERE id = auth.uid() AND role = 'admin'
        )
    );

CREATE POLICY "Admins delete docs"
    ON public.org_knowledge_docs FOR DELETE
    USING (
        organization_id IN (
            SELECT organization_id FROM public.user_profiles
            WHERE id = auth.uid() AND role = 'admin'
        )
    );

-- org_knowledge_chunks policies
CREATE POLICY "Org members read chunks"
    ON public.org_knowledge_chunks FOR SELECT
    USING (
        organization_id IN (
            SELECT organization_id FROM public.user_profiles WHERE id = auth.uid()
        )
    );

CREATE POLICY "Admins insert chunks"
    ON public.org_knowledge_chunks FOR INSERT
    WITH CHECK (
        organization_id IN (
            SELECT organization_id FROM public.user_profiles
            WHERE id = auth.uid() AND role = 'admin'
        )
    );

CREATE POLICY "Admins delete chunks"
    ON public.org_knowledge_chunks FOR DELETE
    USING (
        organization_id IN (
            SELECT organization_id FROM public.user_profiles
            WHERE id = auth.uid() AND role = 'admin'
        )
    );

-- 6. RPC function for vector similarity search
--    Returns chunk_text, similarity, AND file_name so the model can cite sources.
--    DROP is required first because the return type changed (added file_name column).
DROP FUNCTION IF EXISTS match_org_chunks(vector, uuid, integer);

CREATE OR REPLACE FUNCTION match_org_chunks(
    query_embedding vector(1024),
    match_org_id    UUID,
    match_count     INT DEFAULT 5
)
RETURNS TABLE (chunk_text TEXT, similarity FLOAT, file_name TEXT)
LANGUAGE SQL STABLE AS $$
    SELECT
        c.chunk_text,
        1 - (c.embedding <=> query_embedding) AS similarity,
        d.file_name
    FROM public.org_knowledge_chunks c
    JOIN public.org_knowledge_docs d ON d.id = c.doc_id
    WHERE c.organization_id = match_org_id
      AND c.embedding IS NOT NULL
    ORDER BY c.embedding <=> query_embedding
    LIMIT match_count;
$$;
