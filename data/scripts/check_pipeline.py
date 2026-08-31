"""Verify that every report came through the pipeline intact.

Reads nothing but the artefacts the pipeline already produced - Markdown, page
map, extraction JSON, parquet, and the database - and reports per document
whether each stage did its job. Makes no API calls and writes nothing, so it is
safe to run at any time and costs nothing.

The point is the stages that fail *quietly*. An empty PDF or a failed API call
is loud, but a report whose headings were never recognised imports perfectly and
simply has no section citation, and a running footer that was not stripped just
quietly pollutes every chunk. Those are what this looks for.

Run from data/scripts:
    uv run python check_pipeline.py
    uv run python check_pipeline.py --only Roudno
    uv run python check_pipeline.py --no-db     # skip the database checks
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg2

from manifest import Manifest, timestamp_key
from markdown_normalizer import MARKDOWN_VERSION, _signature
from pipeline_common import (
    MANIFEST_PATH,
    MARKDOWN_DIR,
    Settings,
    configure_logging,
    load_connection_params,
    load_settings,
    stage_outputs,
)
from schemas import SCHEMA_VERSION

logger = logging.getLogger(__name__)

OK, WARN, FAIL = "OK", "VAROVÁNÍ", "CHYBA"

# Below this share of chunks carrying a page number, page attribution is worth a
# look. Two real reports sit at 98% and 86%; well under that means the Markdown
# and the page map drifted apart.
_PAGE_COVERAGE_WARN = 0.80

# A chunk this small is usually a fragment left behind by a bad split.
_MIN_SENSIBLE_TOKENS = 60

# gemini-embedding-001 accepts about 2048 tokens and tiktoken undercounts Czech.
_MAX_SENSIBLE_TOKENS = 1500

_DOT_LEADER_RE = re.compile(r"\.{4,}")
_HEADING_RE = re.compile(r"^(#{1,6})\s+\S")


@dataclass
class Check:
    """One verified property of one document."""

    label: str
    status: str
    detail: str


def _check(label: str, ok: bool, detail: str, *, warn_only: bool = False) -> Check:
    """Build a Check, degrading a failure to a warning when it is not fatal."""
    if ok:
        return Check(label, OK, detail)
    return Check(label, WARN if warn_only else FAIL, detail)


def check_markdown(stem: str, is_pdf: bool) -> list[Check]:
    """Verify the Markdown stage: headings present, artefacts gone."""
    path = MARKDOWN_DIR / f"{stem}.md"
    if not path.exists():
        return [Check("markdown", FAIL, f"chybí {path.name}")]

    lines = path.read_text(encoding="utf-8").splitlines()
    headings = [line for line in lines if _HEADING_RE.match(line)]
    titles = [line for line in headings if line.startswith("# ")]

    checks = [
        _check(
            "markdown",
            bool(headings),
            f"{len(headings)} nadpisů ({len(titles)} titulní, {len(headings) - len(titles)} číslovaných)"
            f", {len(lines)} řádků"
            if headings
            else "ŽÁDNÉ nadpisy - všechny chunky zůstanou bez sekce",
        )
    ]
    if headings and not titles:
        checks.append(Check("titulek", WARN, "chybí nadpis úrovně '#' s názvem zprávy"))

    # Artefacts the normaliser is supposed to have removed. Present means it did
    # not recognise them, which usually also means the headings are wrong.
    leftovers = []
    dot_leaders = sum(1 for line in lines if _DOT_LEADER_RE.search(line))
    if dot_leaders:
        leftovers.append(f"{dot_leaders}x zbytek obsahu (tečkové vodítko)")
    tables = sum(1 for line in lines if line.strip().startswith("|"))
    if tables:
        leftovers.append(f"{tables}x řádek tabulky")

    counts = Counter(sig for sig in (_signature(line) for line in lines) if sig)
    repeats = [(sig, n) for sig, n in counts.items() if n >= 5]
    if repeats:
        worst = max(repeats, key=lambda item: item[1])
        leftovers.append(f"řádek opakovaný {worst[1]}x ({worst[0][:34]!r})")

    checks.append(
        _check(
            "zbytky konverze",
            not leftovers,
            "; ".join(leftovers) if leftovers else "bez obsahu, tabulek a paginace",
            warn_only=True,
        )
    )

    if is_pdf:
        pages_path = MARKDOWN_DIR / f"{stem}.pages.json"
        if pages_path.exists():
            pages = json.loads(pages_path.read_text(encoding="utf-8"))
            empty = sum(1 for page in pages if not page.strip())
            checks.append(
                _check(
                    "mapa stránek",
                    empty == 0,
                    f"{len(pages)} stran" + (f", z toho {empty} prázdných" if empty else ""),
                    warn_only=True,
                )
            )
        else:
            checks.append(Check("mapa stránek", WARN, "chybí .pages.json, čísla stran nebudou"))

    return checks


def check_extraction(stem: str) -> tuple[list[Check], dict[str, Any] | None]:
    """Verify the extraction stage."""
    path = stage_outputs(f"{stem}.pdf")["extract"]
    if not path.exists():
        return [Check("extrakce", FAIL, f"chybí {path.name}")], None

    payload = json.loads(path.read_text(encoding="utf-8"))
    extraction = payload.get("extraction", {})
    version = payload.get("extraction_schema_version")
    missing = extraction.get("missing_fields") or []

    detail = f"schéma v{version}, {len(missing)} chybějících polí"
    if missing:
        detail += f" ({', '.join(missing[:4])})"

    checks = [
        _check("extrakce", bool(extraction.get("title")), detail if extraction.get("title") else "prázdný titulek"),
    ]
    if version != SCHEMA_VERSION:
        checks.append(
            Check("schéma", WARN, f"extrahováno pod v{version}, aktuální je v{SCHEMA_VERSION}")
        )
    return checks, payload


def check_chunks(stem: str, settings: Settings, is_pdf: bool) -> tuple[list[Check], pd.DataFrame | None]:
    """Verify the chunking and embedding stage."""
    path = stage_outputs(f"{stem}.pdf")["chunk"]
    if not path.exists():
        return [Check("chunky", FAIL, f"chybí {path.name}")], None

    frame = pd.read_parquet(path)
    total = len(frame)
    if not total:
        return [Check("chunky", FAIL, "parquet je prázdný")], frame

    tokens = frame["token_count"].dropna()
    checks = [
        Check("chunky", OK, f"{total} chunků, {int(tokens.min())}-{int(tokens.max())} tokenů"),
    ]
    if tokens.min() < _MIN_SENSIBLE_TOKENS:
        checks.append(Check("velikost chunků", WARN, f"nejmenší má {int(tokens.min())} tokenů"))
    if tokens.max() > _MAX_SENSIBLE_TOKENS:
        checks.append(
            Check("velikost chunků", WARN, f"největší má {int(tokens.max())} tokenů, limit modelu je ~2048")
        )

    with_section = int(frame["section"].notna().sum())
    checks.append(
        _check(
            "sekce",
            with_section == total,
            f"{with_section}/{total} má sekci"
            + ("" if with_section == total else " - citace budou neúplné"),
        )
    )

    if is_pdf:
        with_page = int(frame["page_from"].notna().sum())
        share = with_page / total
        checks.append(
            _check(
                "stránky",
                share >= _PAGE_COVERAGE_WARN,
                f"{with_page}/{total} má číslo stránky ({share:.0%})",
                warn_only=True,
            )
        )

    dims = {len(vector) for vector in frame["embedding"]}
    checks.append(
        _check(
            "embeddingy",
            dims == {settings.embedding_dimensions},
            f"{total}x {dims.pop() if len(dims) == 1 else sorted(dims)} dim"
            + ("" if dims == set() else f", očekáváno {settings.embedding_dimensions}"),
        )
        if dims != {settings.embedding_dimensions}
        else Check("embeddingy", OK, f"{total}x {settings.embedding_dimensions} dim")
    )

    expected = list(range(total))
    if list(frame["chunk_index"]) != expected:
        checks.append(Check("číslování chunků", WARN, "chunk_index není souvislá řada od 0"))

    return checks, frame


def check_manifest(entry: dict[str, Any], settings: Settings) -> list[Check]:
    """Verify the manifest records current versions for every stage."""
    stale = []
    if entry.get("markdown_version") != MARKDOWN_VERSION:
        stale.append(f"markdown v{entry.get('markdown_version')} != v{MARKDOWN_VERSION}")
    if entry.get("extraction_schema_version") != SCHEMA_VERSION:
        stale.append(f"schéma v{entry.get('extraction_schema_version')} != v{SCHEMA_VERSION}")
    if entry.get("embedding_model") != settings.embedding_model:
        stale.append(f"model {entry.get('embedding_model')}")
    if entry.get("embedding_dimensions") != settings.embedding_dimensions:
        stale.append(f"dimenze {entry.get('embedding_dimensions')}")
    if entry.get("chunk_params_hash") != settings.pipeline_config().chunk_params:
        stale.append("parametry chunkování")

    missing_stages = [stage for stage in ("markdown", "extract", "chunk", "import")
                      if not entry.get(timestamp_key(stage))]
    if missing_stages:
        stale.append("neproběhlo: " + ", ".join(missing_stages))

    return [
        _check(
            "manifest",
            not stale,
            "; ".join(stale) if stale else "všechny verze aktuální",
            warn_only=True,
        )
    ]


def check_database(cursor, stem: str, payload: dict[str, Any] | None, frame: pd.DataFrame | None) -> list[Check]:
    """Verify the document landed in the database and is searchable."""
    if payload is None:
        return [Check("databáze", WARN, "přeskočeno, chybí extrakce")]

    document_id = payload["document_id"]
    cursor.execute("SELECT title FROM public.documents WHERE id = %s", (document_id,))
    row = cursor.fetchone()
    if row is None:
        return [Check("databáze", FAIL, "dokument v databázi není")]

    cursor.execute(
        """SELECT count(*), count(section), count(page_from),
                  count(*) FILTER (WHERE fts_chunk IS NULL OR fts_chunk = '')
           FROM public.document_chunks WHERE document_id = %s""",
        (document_id,),
    )
    total, sections, pages, empty_fts = cursor.fetchone()

    checks = []
    expected = len(frame) if frame is not None else total
    checks.append(
        _check("databáze", total == expected, f"{total} chunků" + ("" if total == expected else f", parquet má {expected}"))
    )
    checks.append(
        _check("db sekce", sections == total, f"{sections}/{total} má sekci")
    )
    checks.append(
        _check("db fulltext", empty_fts == 0, f"{total - empty_fts}/{total} má naplněný fts_chunk")
    )

    # End-to-end: take words out of the middle of the document and check the
    # full-text side actually finds it. Catches a missing Czech configuration or
    # a trigger that never fired.
    if frame is not None and len(frame):
        sample = frame.iloc[len(frame) // 2]["chunk_raw"]
        words = [w for w in re.findall(r"\w{5,}", sample, flags=re.UNICODE)][:4]
        if words:
            probe = " ".join(words)
            try:
                cursor.execute(
                    """SELECT count(*) FROM public.document_chunks
                       WHERE document_id = %s
                         AND fts_chunk @@ (websearch_to_tsquery('public.czech', %s)
                                        || websearch_to_tsquery('public.czech_literal', %s))""",
                    (document_id, probe, probe),
                )
                hits = cursor.fetchone()[0]
                checks.append(
                    _check("fulltext test", hits > 0, f"dotaz {probe!r} vrací {hits} chunků")
                )
            except psycopg2.Error as exc:
                checks.append(Check("fulltext test", FAIL, str(exc).strip().splitlines()[0]))
    return checks


def render(stem: str, key: str, checks: list[Check]) -> tuple[int, int]:
    """Print one document's checks. Returns (failures, warnings)."""
    failures = sum(1 for check in checks if check.status == FAIL)
    warnings = sum(1 for check in checks if check.status == WARN)
    marker = "FAIL" if failures else ("WARN" if warnings else "OK")

    print(f"\n=== {stem}  ({key})  [{marker}]")
    for check in checks:
        print(f"  {check.status:9} {check.label:18} {check.detail}")
    return failures, warnings


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Check every stage of the report pipeline.")
    parser.add_argument(
        "--only", nargs="*", help="Restrict to these documents (stem, file name or path)"
    )
    parser.add_argument("--no-db", action="store_true", help="Skip the database checks")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns 1 when any document failed a check."""
    configure_logging()
    args = parse_args(argv if argv is not None else sys.argv[1:])
    settings = load_settings()
    manifest = Manifest(MANIFEST_PATH)

    wanted = {Path(item).stem for item in args.only} if args.only else None
    keys = [key for key in manifest.keys() if wanted is None or Path(key).stem in wanted]
    if not keys:
        logger.warning("Nothing to check; the manifest is empty or --only matched nothing")
        return 0

    cursor = None
    connection = None
    if not args.no_db:
        try:
            connection = psycopg2.connect(**load_connection_params())
            cursor = connection.cursor()
        except psycopg2.Error as exc:
            logger.warning("Database unreachable, skipping those checks: %s", str(exc).strip())

    total_failures = 0
    total_warnings = 0
    try:
        for key in keys:
            stem = Path(key).stem
            is_pdf = key.lower().endswith(".pdf")
            entry = manifest.get(key)

            checks = check_markdown(stem, is_pdf)
            extraction_checks, payload = check_extraction(stem)
            checks += extraction_checks
            chunk_checks, frame = check_chunks(stem, settings, is_pdf)
            checks += chunk_checks
            if cursor is not None:
                checks += check_database(cursor, stem, payload, frame)
            checks += check_manifest(entry, settings)

            failures, warnings = render(stem, key, checks)
            total_failures += failures
            total_warnings += warnings
    finally:
        if connection is not None:
            connection.close()

    print(
        f"\nSOUHRN: {len(keys)} dokumentů | {total_failures} chyb, {total_warnings} varování"
    )
    return 1 if total_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
