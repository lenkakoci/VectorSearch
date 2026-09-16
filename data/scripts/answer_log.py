"""Keep what people actually asked, one JSON line per answer.

The golden set was written by hand, from what its author imagined a colleague
would ask. Real questions are better than imagined ones, and they only exist
while someone is using the demo - so every answered question is appended here
with what it retrieved, what it cited and how the check went. Turning a line of
this log into a golden entry is a human's job: the question is there, the cited
document is there, and the verbatim quotes are exactly the evidence snippets
``golden.yaml`` wants.

What is deliberately not written: the prompt and the model's raw answer. Both
are large, both are reproducible from the sources, and a log that is expensive
to keep gets deleted.

Writing happens at the edges - ``ask_reports.py`` and ``search_api.py`` - not
in ``answer_service.py``. The chain stays a library that touches no files, and
an evaluation run does not pollute the record of what people asked.

A failure to write is never allowed to break an answer: the answer is the
product, the log is a note about it.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline_common import ANSWERS_DIR

logger = logging.getLogger(__name__)

LOG_NAME = "asked.jsonl"


def log_path(directory: Path | None = None) -> Path:
    """Return the file answers are appended to."""
    return (directory or ANSWERS_DIR) / LOG_NAME


def record(
    result: Any,
    *,
    source: str,
    filters: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
    ms: float | None = None,
) -> dict[str, Any]:
    """Return the line that describes one answer.

    ``result`` is an ``AnswerResult``; it is taken loosely so a test can pass a
    stand-in and so this module imports nothing from the answering chain.
    """
    trace = dict(getattr(result, "trace", {}) or {})
    sources = []
    for item in getattr(result, "sources", []) or []:
        sources.append(
            {
                "id": item.get("id"),
                "cited": bool(item.get("cited")),
                "role": item.get("role"),
                "document_id": str(item.get("document_id")),
                "title": item.get("title"),
                "chunk_index": item.get("chunk_index"),
                "section": item.get("section"),
                "page_from": item.get("page_from"),
                "content_kind": item.get("content_kind"),
                "rerank_grade": item.get("rerank_grade"),
            }
        )
    return {
        "asked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source,
        "question": getattr(result, "question", ""),
        "status": getattr(result, "status", ""),
        "model": getattr(result, "model", ""),
        "prompt_version": getattr(result, "prompt_version", None),
        "filters": filters or {},
        "options": options or {},
        "statements": [
            {
                "text": statement.get("text"),
                "check": statement.get("check"),
                "source_ids": statement.get("source_ids"),
                "quotes": statement.get("quotes"),
            }
            for statement in getattr(result, "statements", []) or []
        ],
        "missing": list(getattr(result, "missing", []) or []),
        "conflicts": len(getattr(result, "conflicts", []) or []),
        "sources": sources,
        # Whether this answer was paid for or came from the cache, so counting
        # what a demo cost does not need the API bill.
        "cache": trace.get("cache", "miss"),
        "gate": trace.get("gate"),
        "context": trace.get("context"),
        "validation": trace.get("validation"),
        "server_ms": trace.get("total_ms"),
        "client_ms": round(ms, 1) if ms is not None else None,
    }


def append(line: dict[str, Any], directory: Path | None = None) -> Path | None:
    """Append one record. Returns the file written, or None when it failed."""
    path = log_path(directory)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
        return path
    except OSError as exc:  # a read-only mount, a full disk, a missing volume
        logger.warning("Odpověď se nepodařilo zapsat do %s: %s", path, exc)
        return None


def read(directory: Path | None = None) -> list[dict[str, Any]]:
    """Return every record written so far, oldest first.

    A line that does not parse is skipped rather than fatal: the log is
    append-only from several processes and a truncated last line is possible.
    """
    path = log_path(directory)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            logger.warning("Přeskakuji poškozený řádek v %s", path)
    return records
