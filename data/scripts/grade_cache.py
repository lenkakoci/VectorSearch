"""Keep grades between processes, so the same question is graded once.

``rerank_service.py`` already remembers a grade for the life of a process. That
covers the web demo, whose API stays up, and covers nothing else: every CLI
question and every evaluation run starts with an empty memory and pays for
forty gradings again. This is the same cache written down.

One file per (model, question), holding the grade of every chunk graded for it.
Reading is one file, writing is one file, and a torn or unreadable file reads
as no grades at all.

The key includes a fingerprint of the corpus, and that is not decoration. A
chunk id is ``uuid5(document_id:chunk_index)``, so it survives re-chunking even
when the text under it changes completely - without the fingerprint, a grade
given to yesterday's text would be served for today's.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from answer_cache import corpus_fingerprint
from pipeline_common import ANSWERS_DIR

logger = logging.getLogger(__name__)

GRADES_DIR_NAME = "grades"
_KEY_LENGTH = 32


def grades_dir(directory: Path | None = None) -> Path:
    """Return the directory grade files live in."""
    return (directory or ANSWERS_DIR) / GRADES_DIR_NAME


def key_of(model: str, query: str, corpus: str | None = None) -> str:
    """Return the file key for one model asking one question of this corpus."""
    payload = "\n".join(
        [
            model or "",
            " ".join((query or "").split()).lower(),
            corpus if corpus is not None else corpus_fingerprint(),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:_KEY_LENGTH]


def load(key: str, directory: Path | None = None) -> dict[str, tuple[int, str]]:
    """Return the grades stored under ``key``: chunk id to (grade, reason)."""
    path = grades_dir(directory) / f"{key}.json"
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Uložené známky %s se nedají přečíst (%s)", path.name, exc)
        return {}
    grades: dict[str, tuple[int, str]] = {}
    for chunk_id, value in (stored.get("grades") or {}).items():
        try:
            grade, reason = value
            grades[str(chunk_id)] = (int(grade), str(reason))
        except (TypeError, ValueError):
            continue
    return grades


def store(
    key: str,
    grades: dict[str, tuple[int, str]],
    directory: Path | None = None,
    *,
    model: str = "",
    query: str = "",
) -> Path | None:
    """Write every grade known for this question. Returns the file, or None."""
    path = grades_dir(directory) / f"{key}.json"
    payload: dict[str, Any] = {
        "model": model,
        "query": query,
        "grades": {chunk_id: [grade, reason] for chunk_id, (grade, reason) in grades.items()},
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path
    except OSError as exc:
        logger.warning("Známky se nepodařilo uložit (%s)", exc)
        return None


def clear(directory: Path | None = None) -> int:
    """Delete every stored grade. Returns how many files went."""
    path = grades_dir(directory)
    if not path.exists():
        return 0
    gone = 0
    for item in path.glob("*.json"):
        try:
            item.unlink()
            gone += 1
        except OSError as exc:
            logger.warning("Nepodařilo se smazat %s (%s)", item.name, exc)
    return gone
