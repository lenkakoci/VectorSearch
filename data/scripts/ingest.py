"""Incremental pipeline runner - the one command to run when a report arrives.

Scans the input folders, diffs each file against the manifest, and runs only the
stages that are actually stale:

    source sha256 changed        -> everything, starting from PDF -> Markdown
    SCHEMA_VERSION or LLM model  -> extract -> chunk -> embed -> import
    chunk params or embed model  -> chunk -> embed -> import
    nothing changed              -> skip the file

That last row is the point. Dropping a new report into data/PDFs/ and running
this costs exactly one extraction. Bumping SCHEMA_VERSION in schemas.py
re-extracts every document from cached Markdown, without re-parsing a PDF.

Run from data/scripts:
    uv run python ingest.py                  # process whatever is stale
    uv run python ingest.py --dry-run        # show the plan and exit
    uv run python ingest.py --only report.pdf
    uv run python ingest.py --force          # redo everything
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import chunk_and_embed
import extract_reports
import import_reports
from manifest import STAGES, Manifest, file_sha256
from pipeline_common import (
    DATA_DIR,
    MANIFEST_PATH,
    configure_logging,
    discover_sources,
    ensure_dirs,
    load_settings,
    source_key,
)

logger = logging.getLogger(__name__)


def build_plan(sources: list[Path], manifest: Manifest, settings, force: bool) -> dict[str, set[str]]:
    """Return the set of stale stages per source file."""
    config = settings.pipeline_config()
    plan: dict[str, set[str]] = {}
    for path in sources:
        key = source_key(path)
        if force:
            plan[key] = set(STAGES)
            continue
        pending = manifest.stages_to_run(key, file_sha256(path), config)
        if pending:
            plan[key] = pending
    return plan


def describe_plan(plan: dict[str, set[str]], total: int) -> None:
    """Log what the run is about to do."""
    if not plan:
        logger.info("No changes: all %d source files are up to date", total)
        return
    logger.info("Plan for %d of %d source files:", len(plan), total)
    for key, stages in sorted(plan.items()):
        ordered = [stage for stage in STAGES if stage in stages]
        logger.info("  %-50s %s", key, " -> ".join(ordered))


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Run the incremental report ingestion pipeline.")
    parser.add_argument("--force", action="store_true", help="Reprocess everything from scratch")
    parser.add_argument("--dry-run", action="store_true", help="Show the plan and exit")
    parser.add_argument("--only", nargs="*", help="Restrict to these files (name or path)")
    parser.add_argument(
        "--skip-import", action="store_true", help="Stop after embedding, do not touch the database"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    configure_logging()
    args = parse_args(argv if argv is not None else sys.argv[1:])
    settings = load_settings()
    ensure_dirs()
    manifest = Manifest(MANIFEST_PATH)

    if args.only:
        sources = []
        for item in args.only:
            candidate = Path(item)
            if not candidate.exists():
                candidate = settings.input_dir / item
            if not candidate.exists():
                logger.error("Source not found: %s", item)
                return 1
            sources.append(candidate)
    else:
        sources = discover_sources(settings, extra_dirs=[DATA_DIR / "samples"])

    if not sources:
        logger.warning(
            "No source files found in %s (supported: .pdf, .md)", settings.input_dir
        )
        return 0

    plan = build_plan(sources, manifest, settings, args.force)
    describe_plan(plan, len(sources))

    if args.dry_run or not plan:
        return 0

    stems = sorted({Path(key).stem for key in plan})
    paths = [str(path) for path in sources if source_key(path) in plan]

    logger.info("--- Stage 1/3: extract ---")
    extract_argv = ["--only", *paths]
    if args.force:
        extract_argv.append("--force")
    if extract_reports.main(extract_argv) != 0:
        logger.error("Extraction reported failures; stopping before chunking")
        return 1

    logger.info("--- Stage 2/3: chunk and embed ---")
    chunk_argv = ["--only", *stems]
    if args.force:
        chunk_argv.append("--force")
    if chunk_and_embed.main(chunk_argv) != 0:
        logger.error("Chunking reported failures; stopping before import")
        return 1

    if args.skip_import:
        logger.info("--skip-import set; stopping before the database stage")
        return 0

    logger.info("--- Stage 3/3: import ---")
    import_argv = ["--only", *stems]
    if args.force:
        import_argv.append("--force")
    if import_reports.main(import_argv) != 0:
        logger.error("Import reported failures")
        return 1

    logger.info("Ingest complete for %d source files", len(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
