-- Czech full-text search.
--
-- Until this file existed the corpus was indexed with the 'simple'
-- configuration, which lowercases and does nothing else. Czech inflects
-- heavily, so entire questions were unanswerable: the report section
-- "Technicke parametry vrtu pro tepelne cerpadlo" could not be found by
-- searching "vrty pro tepelne cerpadlo", because 'vrtu' and 'vrty' are simply
-- two different lexemes. Measured on the real corpus, three of six realistic
-- queries returned nothing at all.
--
-- Two configurations are created, and BOTH are indexed into the same tsvector:
--
--   czech          hunspell morphology. 'vrtu' and 'vrty' both become 'vrt',
--                  'zastizena' becomes 'zastihnout'. Stop words are dropped.
--                  Lexemes keep their diacritics.
--   czech_literal  what this project did before: strip accents, index verbatim.
--
-- Neither is enough alone. Morphology only matches when the query carries the
-- same diacritics as the document, so 'cerpadlo' would miss 'cerpadlo' written
-- properly. The obvious repair - stripping accents from the hunspell dictionary
-- itself - was tried and rejected: it collapses about 12000 of the dictionary's
-- 261000 entries into duplicates and alters the condition of 517 affix rules,
-- and measurably breaks lemmas that work in the intact dictionary ('hladiny'
-- stops resolving to 'hladina'). Indexing both configurations and OR-ing the two
-- queries keeps every match either one would find, at the cost of a larger
-- tsvector. Verified against a matrix of accented and unaccented queries.
--
-- Requires czech.affix, czech.dict and czech.stop in $SHAREDIR/tsearch_data,
-- installed by postgres/Dockerfile. If those are missing this file fails and
-- leaves the 'simple' trigger from 02 in place, which is the previous, working
-- behaviour - deliberately, so a stock image degrades instead of breaking.

CREATE EXTENSION IF NOT EXISTS unaccent;

-- Text search objects have no IF NOT EXISTS, hence the catalog guards.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_ts_dict WHERE dictname = 'czech_hunspell') THEN
        CREATE TEXT SEARCH DICTIONARY public.czech_hunspell (
            TEMPLATE  = ispell,
            DictFile  = czech,
            AffFile   = czech,
            StopWords = czech
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = 'czech') THEN
        CREATE TEXT SEARCH CONFIGURATION public.czech (COPY = simple);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = 'czech_literal') THEN
        CREATE TEXT SEARCH CONFIGURATION public.czech_literal (COPY = simple);
    END IF;
END
$$;

-- All six word token types, not just 'word'. COPY = simple brings the mappings
-- of the simple configuration along, and the parser classifies a token with no
-- non-ASCII characters as 'asciiword' - so mapping only 'word' would send
-- "vrty" to the simple dictionary while "vrtu" went to the Czech one, and the
-- two could never meet.
ALTER TEXT SEARCH CONFIGURATION public.czech
    ALTER MAPPING FOR asciiword, asciihword, hword_asciipart, word, hword, hword_part
    WITH czech_hunspell, unaccent, simple;

ALTER TEXT SEARCH CONFIGURATION public.czech_literal
    ALTER MAPPING FOR asciiword, asciihword, hword_asciipart, word, hword, hword_part
    WITH unaccent, simple;

-- Replaces the 'simple' version created in 02. Both configurations are
-- IMMUTABLE - unaccent is a dictionary in the chain here, not the STABLE
-- unaccent() function - so unlike before, nothing stops this becoming a
-- GENERATED column later.
CREATE OR REPLACE FUNCTION public.document_chunks_fts_trigger()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.fts_chunk :=
        to_tsvector('public.czech', coalesce(NEW.chunk_raw, ''))
        || to_tsvector('public.czech_literal', coalesce(NEW.chunk_raw, ''));
    RETURN NEW;
END;
$$;

-- Rebuild what the old configuration indexed. The trigger fires on UPDATE OF
-- chunk_raw, so assigning the column to itself is enough.
UPDATE public.document_chunks SET chunk_raw = chunk_raw;

COMMENT ON FUNCTION public.document_chunks_fts_trigger() IS
    'Indexes chunk_raw under both the Czech morphological and the accent-stripped literal configuration.';
