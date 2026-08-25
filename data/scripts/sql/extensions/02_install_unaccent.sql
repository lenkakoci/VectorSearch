-- Enable unaccent extension for accent-insensitive full-text search normalization
-- Used by the document_chunks FTS trigger for accent-insensitive keyword search

CREATE EXTENSION IF NOT EXISTS unaccent;

-- Verify installation
SELECT extname, extversion FROM pg_extension WHERE extname = 'unaccent';
