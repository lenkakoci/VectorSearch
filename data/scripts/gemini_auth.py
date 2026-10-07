"""Google Gemini client construction and retry helpers for data scripts.

Uses the native ``google-genai`` SDK rather than Gemini's OpenAI-compatibility
layer. That layer exposes only chat completions - it has no Responses API - and
does not document the ``dimensions`` parameter for embeddings. The native SDK
gives us both structured output bound directly to a Pydantic model and explicit
``output_dimensionality`` plus ``task_type`` control, which the pipeline needs.
"""

from __future__ import annotations

import logging
import math
import os
from collections.abc import Sequence
from typing import Any

from google import genai
from google.genai import errors

logger = logging.getLogger(__name__)

# Retryable HTTP status codes: rate limiting and transient server faults.
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


def create_gemini_client() -> genai.Client:
    """Create a Gemini API client from the environment.

    Reads ``GEMINI_API_KEY`` (falling back to ``GOOGLE_API_KEY``, which the SDK
    also honours).

    Raises:
        ValueError: If no API key is configured.
    """
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY is required. Copy .env.template to .env and fill it in."
        )
    return genai.Client(api_key=api_key)


def is_retryable_error(exc: BaseException) -> bool:
    """Return True for rate limits and transient server errors."""
    if isinstance(exc, errors.ServerError):
        return True
    if isinstance(exc, errors.ClientError):
        return getattr(exc, "code", None) in _RETRYABLE_STATUS
    if isinstance(exc, errors.APIError):
        return getattr(exc, "code", None) in _RETRYABLE_STATUS
    return False


# What one generative call was billed for. ``output`` is the answer itself and
# ``thoughts`` the reasoning behind it: the API reports them separately but
# prices them the same, and output costs five times input on the flash models.
USAGE_KEYS = ("prompt", "output", "thoughts", "cached", "total")


def no_usage() -> dict[str, int]:
    """Return a zero token count, for a call that did not happen."""
    return dict.fromkeys(USAGE_KEYS, 0)


def usage_of(response: Any) -> dict[str, int]:
    """Return the token counts one generative call was billed for.

    The counts are free - they arrive with a response that was paid for anyway -
    and nothing here used to read them. That left the one cost nobody could see:
    thinking is billed as output and no call in this pipeline sets a thinking
    budget, so a grading call may reason at length before returning a 0-3 grade
    and charge the output rate for it.

    ``output`` excludes ``thoughts``; ``total`` is the API's own sum and is the
    figure to hold against a bill. A count the API omits reads as zero, so two
    of these can always be added together.

    These are the counts of the attempt that answered. An attempt that failed
    and was retried leaves no response to read, so a run that hit rate limits
    reads lower here than on the bill - which is the opposite of the error worth
    worrying about, but worth knowing when the two do not agree.

    Embeddings have no equivalent: ``EmbedContentResponse`` reports only
    ``billable_character_count`` and only on Vertex, so the embedding half of
    the bill stays a local estimate from ``chunker.count_tokens``.
    """
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return no_usage()
    return {
        "prompt": int(getattr(usage, "prompt_token_count", 0) or 0),
        "output": int(getattr(usage, "candidates_token_count", 0) or 0),
        "thoughts": int(getattr(usage, "thoughts_token_count", 0) or 0),
        "cached": int(getattr(usage, "cached_content_token_count", 0) or 0),
        "total": int(getattr(usage, "total_token_count", 0) or 0),
    }


def add_usage(*parts: dict[str, int] | None) -> dict[str, int]:
    """Add the token counts of several calls into one."""
    summed = no_usage()
    for part in parts:
        for key in USAGE_KEYS:
            summed[key] += int((part or {}).get(key) or 0)
    return summed


def normalize(vector: Sequence[float]) -> list[float]:
    """L2-normalise an embedding vector.

    ``gemini-embedding-001`` truncates via Matryoshka representation learning
    when ``output_dimensionality`` is below 3072, and Google documents that the
    result must be re-normalised. Cosine distance is scale-invariant so this is
    strictly required only for other metrics, but normalising keeps the stored
    vectors correct for any metric and is idempotent for already-unit vectors.

    Returns:
        The normalised vector, or the input unchanged when its norm is zero.
    """
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        logger.warning("Zero-norm embedding encountered; storing as-is")
        return list(vector)
    return [value / norm for value in vector]
