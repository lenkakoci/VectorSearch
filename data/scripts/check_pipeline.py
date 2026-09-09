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

OK, WARN, FAIL, TODO = "OK", "VAROVÁNÍ", "CHYBA", "ČEKÁ"

# Below this share of chunks carrying a page number, page attribution is worth a
# look. Two real reports sit at 98% and 86%; well under that means the Markdown
# and the page map drifted apart.
_PAGE_COVERAGE_WARN = 0.80

# A chunk this small is usually a fragment left behind by a bad split.
_MIN_SENSIBLE_TOKENS = 60

# gemini-embedding-001 accepts about 2048 tokens and tiktoken undercounts Czech.
_MAX_SENSIBLE_TOKENS = 1500

# A blank page or two is a separator; this share of them means scanned annexes.
_EMPTY_PAGE_WARN = 0.10

# One section holding more than this share of a document means the heading
# structure ran out somewhere and everything after it inherited the last label.
# Measured: Myslinka 60%, Pazderna 43%, Novy Opatov 39% - all of them annexes
# cited as the final chapter - against 7-21% for the reports whose structure is
# intact. Counting sections that are merely present says nothing about this:
# those three documents all report 100% coverage.
_SECTION_DOMINANCE_WARN = 0.30

# Under this many chunks a document has too few sections for the share to mean
# anything.
_SECTION_DOMINANCE_MIN_CHUNKS = 10

# How many removal rules to print per reason. One report matched fifty furniture
# signatures; the top few are what identify the pattern.
_REMOVED_SAMPLE = 8

_TOC_ENTRY_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(.+?)\s*\.{4,}\s*(\d+)\s*$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+\S")
_WORD_RE = re.compile(r"[^\W\d_]{3,}", re.UNICODE)


def _trailing_section_run(sections: list[Any]) -> int:
    """Return how many chunks at the end of the document share one section.

    The annex sits at the back, so a long run is the shape the dominance share
    only hints at: it says the label stopped changing and never resumed.
    """
    run = 0
    for value in reversed(sections):
        if value != sections[-1]:
            break
        run += 1
    return run


def _looks_like_furniture(signature: str) -> bool:
    """Return whether a repeated line reads like a header rather than a number.

    Laboratory tables repeat fragments like "19," or "<0," down every page and
    those are data, not pagination. A running header has words in it.
    """
    return len(_WORD_RE.findall(signature)) >= 2


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


def check_markdown(stem: str, is_pdf: bool, page_count: int | None = None) -> list[Check]:
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
    # Only contents-shaped leftovers, i.e. numbered. Dot leaders are also used
    # for table footnotes ("*) ..... odvozena hodnota"), which belong in the text
    # and would otherwise put every report with a results table on this list.
    dot_leaders = sum(1 for line in lines if _TOC_ENTRY_RE.match(line.strip()))
    if dot_leaders:
        leftovers.append(f"{dot_leaders}x nezpracovaná položka obsahu")
    tables = sum(1 for line in lines if line.strip().startswith("|"))
    if tables:
        leftovers.append(f"{tables}x řádek tabulky")

    # A repeated short line is usually a running header the normaliser did not
    # reach, but it can equally be a value repeating down a laboratory table, so
    # the page count goes in the message and a human decides which it is.
    counts = Counter(sig for sig in (_signature(line) for line in lines) if sig)
    repeats = [
        (sig, n) for sig, n in counts.items() if n >= 5 and _looks_like_furniture(sig)
    ]
    if repeats:
        signature, count = max(repeats, key=lambda item: item[1])
        pages = f", dokument má {page_count} stran" if page_count else ""
        leftovers.append(f"řádek opakovaný {count}x{pages} ({signature[:36]!r})")

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
            # A blank separator page or two is normal; a fifth of the document
            # being blank means scanned annexes nobody can search.
            noteworthy = pages and empty / len(pages) >= _EMPTY_PAGE_WARN
            checks.append(
                _check(
                    "mapa stránek",
                    not noteworthy,
                    f"{len(pages)} stran" + (f", z toho {empty} prázdných" if empty else ""),
                    warn_only=True,
                )
            )
        else:
            checks.append(Check("mapa stránek", WARN, "chybí .pages.json, čísla stran nebudou"))

    return checks


def check_extraction(stem: str, ran: bool) -> tuple[list[Check], dict[str, Any] | None]:
    """Verify the extraction stage.

    ``ran`` says whether the manifest claims this stage completed. A missing file
    for a stage that never ran is the normal state after --markdown-only, not a
    failure; only a stage the manifest calls done may be missing its output.
    """
    path = stage_outputs(f"{stem}.pdf")["extract"]
    if not path.exists():
        if not ran:
            return [Check("extrakce", TODO, "zatím neproběhla")], None
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


def check_chunks(
    stem: str, settings: Settings, is_pdf: bool, ran: bool
) -> tuple[list[Check], pd.DataFrame | None]:
    """Verify the chunking and embedding stage."""
    path = stage_outputs(f"{stem}.pdf")["chunk"]
    if not path.exists():
        if not ran:
            return [Check("chunky", TODO, "zatím neproběhly")], None
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

    if total >= _SECTION_DOMINANCE_MIN_CHUNKS:
        counts = frame["section"].value_counts(dropna=False)
        top_label, top_count = str(counts.index[0]), int(counts.iloc[0])
        share = top_count / total
        trailing = _trailing_section_run(list(frame["section"]))
        checks.append(
            _check(
                "kvalita sekcí",
                share <= _SECTION_DOMINANCE_WARN,
                f"největší sekce drží {top_count}/{total} chunků ({share:.0%}), "
                f"koncový běh {trailing}"
                + (
                    ""
                    if share <= _SECTION_DOMINANCE_WARN
                    else f" - '{top_label[-48:]}' zřejmě pohltila přílohu"
                ),
                warn_only=True,
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
    """Verify the manifest records current versions for every stage.

    A document that has only been converted so far is reported as waiting rather
    than stale: comparing its absent extraction model against the configured one
    would just be noise during the convert-and-inspect step.
    """
    pending = [
        stage
        for stage in ("markdown", "extract", "chunk", "import")
        if not entry.get(timestamp_key(stage))
    ]
    if pending:
        return [Check("manifest", TODO, "zbývá: " + ", ".join(pending))]

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
        return [Check("databáze", TODO, "čeká na dřívější fáze")]

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


def check_unconverted(settings: Settings, wanted: set[str] | None) -> list[Check]:
    """Report source PDFs that produced no Markdown at all.

    These never reach the manifest, so every other check in this file is blind to
    them - the documents that failed hardest were the ones the report did not
    mention. A PDF whose pages hold no characters has no text layer: it is a scan
    and needs OCR before this pipeline can do anything with it.
    """
    from extract_reports import pdf_pages  # heavy import, only needed here

    checks: list[Check] = []
    for path in sorted(settings.input_dir.glob("*.pdf")):
        if wanted is not None and path.stem not in wanted:
            continue
        if (MARKDOWN_DIR / f"{path.stem}.md").exists():
            continue
        try:
            pages = pdf_pages(path)
        except Exception as exc:  # noqa: BLE001 - report it rather than crash the run
            checks.append(Check(path.stem, FAIL, f"nelze přečíst: {type(exc).__name__}"))
            continue
        if pages and not any(page.strip() for page in pages):
            checks.append(
                Check(path.stem, FAIL, f"chybí OCR vrstva — {len(pages)} stran bez textu")
            )
        else:
            checks.append(Check(path.stem, FAIL, "převod nevrátil žádný text"))
    return checks


def verdict_of(checks: list[Check]) -> str:
    """Return the worst status among ``checks``."""
    for status in (FAIL, WARN, TODO):
        if any(check.status == status for check in checks):
            return status
    return OK


def render_triage(
    results: list[tuple[str, list[Check]]], unconverted: list[Check]
) -> None:
    """Print only what needs a decision, grouped by what to do about it."""
    ocr = [c for c in unconverted if "OCR" in c.detail]
    broken = [c for c in unconverted if "OCR" not in c.detail]
    no_sections = [
        (stem, c) for stem, checks in results for c in checks
        if c.label == "markdown" and c.status == FAIL
    ]
    failed = [
        (stem, c) for stem, checks in results for c in checks
        if c.status == FAIL and c.label != "markdown"
    ]
    attention = [(stem, c) for stem, checks in results for c in checks if c.status == WARN]
    fine = [stem for stem, checks in results if verdict_of(checks) in (OK, TODO)]

    def block(title: str, rows: list[tuple[str, str]], action: str) -> None:
        if not rows:
            return
        print(f"\n{title} ({len(rows)})")
        for name, detail in rows:
            print(f"   {name[:52]:54} {detail}")
        print(f"   -> {action}")

    print("\n" + "=" * 72)
    print("TRIAGE")
    print("=" * 72)

    block(
        "CHYBÍ OCR VRSTVA",
        [(c.label, c.detail.split("—")[-1].strip()) for c in ocr],
        "nechat projít OCR a nahrát znovu; jinak z nich pipeline nic nedostane",
    )
    block(
        "PŘEVOD SELHAL",
        [(c.label, c.detail) for c in broken],
        "podívat se na PDF ručně",
    )
    block(
        "BEZ NADPISŮ",
        [(stem, c.detail) for stem, c in no_sections],
        "chunky nedostanou citaci sekce; prohlédnout .md a případně nahlásit vzorec",
    )
    block("CHYBY", [(stem, f"{c.label}: {c.detail}") for stem, c in failed], "opravit před ingestem")
    block(
        "STOJÍ ZA POHLED",
        [(stem, f"{c.label}: {c.detail}") for stem, c in attention],
        "obvykle obsah tabulek nebo skenované přílohy; posoudit očima",
    )

    print(f"\nV POŘÁDKU ({len(fine)})")
    for stem in fine[:6]:
        print(f"   {stem[:66]}")
    if len(fine) > 6:
        print(f"   … a dalších {len(fine) - 6}")


def render(stem: str, key: str, checks: list[Check]) -> tuple[int, int, int]:
    """Print one document's checks. Returns (failures, warnings, pending)."""
    failures = sum(1 for check in checks if check.status == FAIL)
    warnings = sum(1 for check in checks if check.status == WARN)
    pending = sum(1 for check in checks if check.status == TODO)
    marker = "FAIL" if failures else ("WARN" if warnings else ("ČEKÁ" if pending else "OK"))

    print(f"\n=== {stem}  ({key})  [{marker}]")
    for check in checks:
        print(f"  {check.status:9} {check.label:18} {check.detail}")
    return failures, warnings, pending


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Check every stage of the report pipeline.")
    parser.add_argument(
        "--only", nargs="*", help="Restrict to these documents (stem, file name or path)"
    )
    parser.add_argument("--no-db", action="store_true", help="Skip the database checks")
    parser.add_argument(
        "--triage", action="store_true",
        help="Print only what needs a decision, grouped by what to do about it",
    )
    parser.add_argument(
        "--removed", action="store_true",
        help="Print what the normaliser deleted from each document and why",
    )
    return parser.parse_args(argv)


def render_removed(stems: list[str]) -> None:
    """Print what normalisation deleted, grouped by the rule that deleted it.

    Furniture removal is the one step that can take real content with nothing
    downstream able to tell - the reason the 25% text-loss guard exists at all.
    This is how to see what it actually took.
    """
    for stem in stems:
        path = MARKDOWN_DIR / f"{stem}.removed.json"
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        removals = payload.get("removals") or []
        total = sum(item["lines"] for item in removals)
        print()
        print("=" * 72)
        print(f"{stem}  -  odstraněno {total} řádků")
        if payload.get("furniture_kept"):
            print("  !  pojistka zabrala: záhlaví se nemazalo, aby se zachovaly nadpisy")
        for reason, label in (("furniture", "ZÁHLAVÍ/PATIČKA"), ("contents", "OBSAH")):
            group = [item for item in removals if item["reason"] == reason]
            if not group:
                continue
            print(f"\n  {label}  ({sum(item['lines'] for item in group)} řádků)")
            for item in group[:_REMOVED_SAMPLE]:
                print(f"    {item['lines']:>6}x  {item['detail'][:88]}")
            if len(group) > _REMOVED_SAMPLE:
                print(f"    … a dalších {len(group) - _REMOVED_SAMPLE} pravidel")


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns 1 when any document failed a check."""
    configure_logging()
    args = parse_args(argv if argv is not None else sys.argv[1:])
    settings = load_settings()
    manifest = Manifest(MANIFEST_PATH)

    wanted = {Path(item).stem for item in args.only} if args.only else None
    keys = [key for key in manifest.keys() if wanted is None or Path(key).stem in wanted]

    if args.removed:
        render_removed([Path(key).stem for key in keys])
        return 0

    unconverted = check_unconverted(settings, wanted)
    if not keys and not unconverted:
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

    total_failures = len(unconverted)
    total_warnings = 0
    total_pending = 0
    results: list[tuple[str, list[Check]]] = []
    try:
        for key in keys:
            stem = Path(key).stem
            is_pdf = key.lower().endswith(".pdf")
            entry = manifest.get(key)

            checks = check_markdown(stem, is_pdf, entry.get("page_count"))
            extraction_checks, payload = check_extraction(
                stem, bool(entry.get(timestamp_key("extract")))
            )
            checks += extraction_checks
            chunk_checks, frame = check_chunks(
                stem, settings, is_pdf, bool(entry.get(timestamp_key("chunk")))
            )
            checks += chunk_checks
            if cursor is not None:
                checks += check_database(cursor, stem, payload, frame)
            checks += check_manifest(entry, settings)

            results.append((stem, checks))
            if args.triage:
                failures = sum(1 for c in checks if c.status == FAIL)
                warnings = sum(1 for c in checks if c.status == WARN)
                pending = sum(1 for c in checks if c.status == TODO)
            else:
                failures, warnings, pending = render(stem, key, checks)
            total_failures += failures
            total_warnings += warnings
            total_pending += pending
    finally:
        if connection is not None:
            connection.close()

    if args.triage:
        render_triage(results, unconverted)
    elif unconverted:
        print("\n=== zdroje bez převodu (nejsou v manifestu)")
        for check in unconverted:
            print(f"  {check.status:9} {check.label[:44]:46} {check.detail}")

    print(
        f"\nSOUHRN: {len(keys) + len(unconverted)} zdrojů | {total_failures} chyb,"
        f" {total_warnings} varování, {total_pending} čeká na zpracování"
    )
    return 1 if total_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
