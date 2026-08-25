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
