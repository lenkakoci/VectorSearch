# PostgreSQL 17 with pgvector and a Czech full-text search dictionary,
# for the geological report vector search project.

FROM pgvector/pgvector:pg17

LABEL org.opencontainers.image.title="PostgreSQL 17 with pgvector" \
      org.opencontainers.image.description="Postgres 17 + pgvector + Czech FTS for semantic search over geological reports" \
      org.opencontainers.image.licenses="Apache-2.0"

# PostgreSQL ships Snowball stemmers for 28 languages and Czech is not one of
# them, so the only option was the 'simple' configuration, which lowercases and
# does nothing else. Czech inflects heavily, which made whole queries
# unanswerable: a section titled "Technicke parametry vrtu pro tepelne cerpadlo"
# could not be found by searching "vrty pro tepelne cerpadlo".
#
# hunspell-cs is the LibreOffice Czech spellchecking dictionary. PostgreSQL's
# ispell template reads hunspell's .aff/.dic pair directly, using it in reverse:
# hunspell derives forms from a stem, the dictionary here recovers the stem from
# a form.
#
# The files are only renamed, never converted. PostgreSQL derives the filenames
# from the DictFile/AffFile parameters (czech -> czech.dict / czech.affix) and
# reads them in the database encoding; this dictionary already declares
# SET UTF-8, so no transcoding is involved.
#
# Licence: the cs_CZ dictionary is GPL-2. It is data read at runtime, not linked
# code, so it does not reach the licence of the pipeline. It would only matter if
# this image were distributed outside the organisation.
RUN apt-get update \
 && apt-get install -y --no-install-recommends hunspell-cs \
 && cp /usr/share/hunspell/cs_CZ.aff /usr/share/postgresql/17/tsearch_data/czech.affix \
 && cp /usr/share/hunspell/cs_CZ.dic /usr/share/postgresql/17/tsearch_data/czech.dict \
 && apt-get purge -y hunspell-cs \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

# Stop words are not part of the hunspell package and 'simple' has none at all,
# which is why the preposition "pro" used to be a search term carrying the same
# weight as "cerpadlo". Function words only - nothing from the domain.
COPY tsearch_data/czech.stop /usr/share/postgresql/17/tsearch_data/czech.stop

# Extensions and text search configurations are created per-database by
# data/scripts/configure_postgresql.py:
#   CREATE EXTENSION IF NOT EXISTS vector;
#   CREATE EXTENSION IF NOT EXISTS unaccent;
#   sql/tables/03_create_czech_fts.sql
