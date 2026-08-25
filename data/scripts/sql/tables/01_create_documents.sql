-- One row per geological report.
--
-- SCHEMA EVOLUTION NOTE
-- The extraction schema is provisional: it was designed before any real report
-- was available. Only fields that every report will have regardless of the final
-- schema are typed columns; everything domain-specific lives in extraction_json.
-- When the schema is finalised, add a migration (03_alter_documents_*.sql) that
-- introduces typed columns and backfills them from extraction_json. No data loss,
-- no re-extraction needed.
--
-- IF NOT EXISTS (not DROP TABLE) is deliberate: this database accumulates real
-- documents and configure_postgresql.py is re-run whenever the schema changes.

CREATE TABLE IF NOT EXISTS public.documents (
    id                        UUID PRIMARY KEY,

    -- Provenance
    source_file               TEXT NOT NULL UNIQUE,
    source_sha256             TEXT NOT NULL,
    markdown_path             TEXT,

    -- Stable core: present in any report regardless of the final schema
    title                     TEXT,
    report_type               TEXT,
    locality                  TEXT,
    report_date               DATE,
    author                    TEXT,
    client                    TEXT,
    summary                   TEXT,

    -- Evolving domain payload: the full Pydantic extraction result
    extraction_json           JSONB NOT NULL DEFAULT '{}'::jsonb,
    extraction_schema_version INT   NOT NULL DEFAULT 1,
    extraction_model          TEXT,

    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_documents_extraction_json
    ON public.documents USING GIN (extraction_json);
CREATE INDEX IF NOT EXISTS idx_documents_report_date
    ON public.documents (report_date);
CREATE INDEX IF NOT EXISTS idx_documents_schema_version
    ON public.documents (extraction_schema_version);
CREATE INDEX IF NOT EXISTS idx_documents_report_type
    ON public.documents (report_type);

COMMENT ON TABLE public.documents IS
    'One row per geological report. Typed columns are the stable core; extraction_json holds the evolving domain schema.';
COMMENT ON COLUMN public.documents.source_sha256 IS
    'SHA-256 of the source file. Drives incremental re-processing in data/scripts/manifest.py.';
COMMENT ON COLUMN public.documents.extraction_json IS
    'Full GeologicalReport extraction result, including extra_fields and missing_fields.';
COMMENT ON COLUMN public.documents.extraction_schema_version IS
    'SCHEMA_VERSION from data/scripts/schemas.py at extraction time. Bumping it triggers re-extraction.';
