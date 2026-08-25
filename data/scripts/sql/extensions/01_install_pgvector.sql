-- Install pgvector extension for vector operations
-- This extension provides support for vector data types and operations

-- Create the extension if it doesn't exist
CREATE EXTENSION IF NOT EXISTS vector;

-- Verify the extension is installed
SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';
