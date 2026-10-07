"""Tests for reading what a call was billed for, which needs no API.

The counts arrive with a response that was paid for anyway, so the only thing
that can go wrong here is reading them wrong: mistaking thinking for output,
or letting an absent count propagate as something other than zero.
"""

from __future__ import annotations

from types import SimpleNamespace

from gemini_auth import add_usage, no_usage, usage_of


def _response(**counts) -> SimpleNamespace:
    """A response shaped like the SDK's, carrying only the named counts."""
    return SimpleNamespace(usage_metadata=SimpleNamespace(**counts))


def test_thinking_is_read_and_kept_apart_from_the_answer():
    """``candidates_token_count`` excludes thoughts, and both bill as output."""
    usage = usage_of(
        _response(
            prompt_token_count=25000,
            candidates_token_count=600,
            thoughts_token_count=2800,
            cached_content_token_count=0,
            total_token_count=28400,
        )
    )
    assert usage == {
        "prompt": 25000,
        "output": 600,
        "thoughts": 2800,
        "cached": 0,
        "total": 28400,
    }


def test_a_response_without_usage_reads_as_zero():
    """Older responses and stubs carry no usage; that is not an error."""
    assert usage_of(SimpleNamespace()) == no_usage()
    assert usage_of(SimpleNamespace(usage_metadata=None)) == no_usage()


def test_an_absent_count_reads_as_zero_not_none():
    """Every field is optional in the API, and None would break the summing."""
    usage = usage_of(_response(prompt_token_count=10, thoughts_token_count=None))
    assert usage == {"prompt": 10, "output": 0, "thoughts": 0, "cached": 0, "total": 0}


def test_several_calls_add_up():
    """One question is two grading calls and an answering call, billed as one."""
    first = {"prompt": 12000, "output": 300, "thoughts": 1400, "cached": 0, "total": 13700}
    second = {"prompt": 13000, "output": 300, "thoughts": 1400, "cached": 0, "total": 14700}
    assert add_usage(first, second, None) == {
        "prompt": 25000,
        "output": 600,
        "thoughts": 2800,
        "cached": 0,
        "total": 28400,
    }
    assert add_usage() == no_usage()
