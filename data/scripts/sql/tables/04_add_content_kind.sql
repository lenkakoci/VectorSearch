-- Mark chunks that come from a report's annex rather than its body.
--
-- Reports carry borehole logs, laboratory certificates and coordinate tables
-- after the last chapter. They are worth keeping and worth searching by keyword
-- - a borehole number has to stay findable - but a filled-in form has nothing
-- for semantic search to match, and on this corpus they are most of the
-- embedding bill: 176 of 265 pages in one report, 86 of 167 in another.
--
-- Annex chunks are therefore imported with embedding IS NULL. No query change
-- is needed: the vector search in search_reports.py already reads
-- WHERE c.embedding IS NOT NULL, while fts_chunk is built by trigger from
-- chunk_raw and so still covers them.
--
-- Re-runnable, like everything in this directory. The default keeps rows
-- imported before this column existed searchable by vector.

ALTER TABLE public.document_chunks
    ADD COLUMN IF NOT EXISTS content_kind TEXT NOT NULL DEFAULT 'prose';

COMMENT ON COLUMN public.document_chunks.content_kind IS
    'prose = report body, annex = borehole logs, laboratory forms and tables (not embedded)';

-- Reporting on how much of a document is annex, and filtering it out of counts.
CREATE INDEX IF NOT EXISTS idx_chunks_content_kind
    ON public.document_chunks (document_id, content_kind);
