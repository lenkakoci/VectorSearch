"""Remember an answer that has already been paid for.

A demo asks the same five questions over and over, and each one costs a grading
call and an answering call. Nothing about those calls changes between two
identical questions: the temperature is 0, the corpus is the same, the prompt
is the same. So the answer is kept on disk and the second asking is instant and
free.

What the key is made of is the whole design. Two questions share an answer only
when everything that could change it is the same:

- the question, with its whitespace collapsed and its case ignored;
- the filters, which decide what could be retrieved at all;
- the options that shape the evidence - candidates, gate, sources per report,
  token budget, neighbours;
- the answering model and ``PROMPT_VERSION``, so new rules invalidate old
  answers;
- a fingerprint of the corpus, taken from the manifest, so re-ingesting a
  report invalidates every answer that could have used it.

The last one is what keeps a cache honest. Without it a demo would happily
serve an answer about a document that has since been re-chunked.

A cache is a convenience, never a dependency: every failure here - unreadable
file, bad JSON, full disk - returns as a miss, and the chain goes on to
produce the answer the expensive way.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from pipeline_common import ANSWERS_DIR, MANIFEST_PATH

logger = logging.getLogger(__name__)

CACHE_DIR_NAME = "cache"
# Long enough that a collision is not a thing that happens, short enough to
# read in a directory listing.
_KEY_LENGTH = 32


def cache_dir(directory: Path | None = None) -> Path:
    """Return the directory cached answers live in."""
    return (directory or ANSWERS_DIR) / CACHE_DIR_NAME


def corpus_fingerprint(manifest: Path | None = None) -> str:
    """Return a short fingerprint of the corpus state.

    The manifest records what ran under which parameters and is rewritten by
    every ingest, so its size and modification time stand in for "the corpus as
    it is now". A missing manifest fingerprints as empty, which simply means
    answers cached now and later will not be shared.
    """
    path = manifest or MANIFEST_PATH
    try:
        stat = path.stat()
    except OSError:
        return ""
    return f"{int(stat.st_mtime)}-{stat.st_size}"


def key_of(
    question: str,
    *,
    filters: dict[str, Any],
    options: dict[str, Any],
    model: str,
    prompt_version: int,
    corpus: str | None = None,
) -> str:
    """Return the key under which this exact answer would be stored."""
    payload = {
        "question": " ".join((question or "").split()).lower(),
        "filters": filters or {},
        "options": options or {},
        "model": model,
        "prompt_version": prompt_version,
        "corpus": corpus if corpus is not None else corpus_fingerprint(),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:_KEY_LENGTH]


def load(key: str, directory: Path | None = None) -> dict[str, Any] | None:
    """Return the stored answer for ``key``, or None when there is none."""
    path = cache_dir(directory) / f"{key}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Cache %s se nedá přečíst (%s), odpověď se spočítá znovu", path.name, exc)
        return None


def store(key: str, payload: dict[str, Any], directory: Path | None = None) -> Path | None:
    """Write one answer under ``key``. Returns the file, or None when it failed."""
    path = cache_dir(directory) / f"{key}.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
        return path
    except OSError as exc:
        logger.warning("Odpověď se nepodařilo uložit do cache (%s)", exc)
        return None


def clear(directory: Path | None = None) -> int:
    """Delete every cached answer. Returns how many files went."""
    path = cache_dir(directory)
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
