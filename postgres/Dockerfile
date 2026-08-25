# PostgreSQL 17 with pgvector for the geological report vector search project.
#
# The base image already ships pgvector, so this layer is intentionally thin.
# It exists so docker-compose has a build context we own - the place to add a
# Czech full-text search dictionary (hunspell/ispell) later without touching
# the compose file or rewriting the search schema.

FROM pgvector/pgvector:pg17

LABEL org.opencontainers.image.title="PostgreSQL 17 with pgvector" \
      org.opencontainers.image.description="Postgres 17 + pgvector for semantic search over geological reports" \
      org.opencontainers.image.licenses="Apache-2.0"

# Extensions are enabled per-database by data/scripts/configure_postgresql.py:
#   CREATE EXTENSION IF NOT EXISTS vector;
#   CREATE EXTENSION IF NOT EXISTS unaccent;
