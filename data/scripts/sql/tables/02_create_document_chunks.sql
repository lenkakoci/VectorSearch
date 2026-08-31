-- One row per embedded chunk of a report.
--
-- This schema is domain-independent and stable: it will NOT change when the
-- extraction schema is finalised.

CREATE TABLE IF NOT EXISTS public.document_chunks (
    id          BIGSERIAL PRIMARY KEY,
    chunk_id    UUID NOT NULL UNIQUE,
    document_id UUID NOT NULL REFERENCES public.documents(id) ON DELETE CASCADE,

    chunk_index INT  NOT NULL,
    section     TEXT,
    page_from   INT,
    page_to     INT,

    -- chunk_raw is the verbatim source text, used for citation in the UI.
    -- chunk_text is what was actually embedded (may carry a context prefix).
    chunk_raw   TEXT NOT NULL,
    chunk_text  TEXT NOT NULL,
    token_count INT,

    -- Gemini supports 128-3072 dimensions (recommended tiers 768/1536/3072) but a
    -- pgvector HNSW index accepts at most 2000, so 3072 is not usable here.
    -- 1536 is the largest recommended tier that fits. Must match
    -- EMBEDDING_DIMENSIONS in .env; changing it requires recreating this table.
    embedding   vector(1536),

    -- Maintained by trigger, not GENERATED: unaccent() is STABLE, not IMMUTABLE.
    fts_chunk   tsvector NOT NULL DEFAULT to_tsvector('simple', ''),

    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_chunks_embedding_cosine
    ON public.document_chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_chunks_fts
    ON public.document_chunks USING GIN (fts_chunk);

CREATE INDEX IF NOT EXISTS idx_chunks_document_id
    ON public.document_chunks (document_id);

-- FTS is built from chunk_raw, not chunk_text: the context prefix repeats the
-- same document metadata on every chunk and would pollute the keyword index.
CREATE OR REPLACE FUNCTION public.document_chunks_fts_trigger()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.fts_chunk := to_tsvector('simple', unaccent(coalesce(NEW.chunk_raw, '')));
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_document_chunks_fts ON public.document_chunks;
CREATE TRIGGER trg_document_chunks_fts
    BEFORE INSERT OR UPDATE OF chunk_raw ON public.document_chunks
    FOR EACH ROW EXECUTE FUNCTION public.document_chunks_fts_trigger();

COMMENT ON TABLE public.document_chunks IS
    'Embedded chunks of geological reports for hybrid (vector + full-text) retrieval.';
COMMENT ON COLUMN public.document_chunks.chunk_raw IS
    'Verbatim chunk text. Cite this to the user and index it for full-text search.';
COMMENT ON COLUMN public.document_chunks.chunk_text IS
    'Text actually sent to the embedding model, optionally prefixed with document context.';
COMMENT ON COLUMN public.document_chunks.section IS
    'Markdown heading path the chunk came from. Primary citation unit.';
COMMENT ON COLUMN public.document_chunks.page_from IS
    'Best-effort source page, matched against the pdfminer page text the chunk was cut from. NULL when unresolved.';
