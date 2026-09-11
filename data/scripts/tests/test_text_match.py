"""Tests for the loose text comparison used by the evaluation and quote checks."""

from __future__ import annotations

from text_match import contains_normalized, normalize_for_match


def test_whitespace_dashes_and_case_are_ignored():
    chunk = "Hladina  podzemní\u00a0vody  v rozmezí  od  0,4  –  1,0  m"
    assert contains_normalized(chunk, "v rozmezí od 0,4-1,0 m")
    assert contains_normalized(chunk, "HLADINA PODZEMNÍ VODY")


def test_soft_hyphen_and_zero_width_space_are_removed():
    assert normalize_for_match("pod\u00adzemní\u200b voda") == "podzemní voda"


def test_spaced_and_unspaced_dashes_compare_equal():
    assert normalize_for_match("3,38.10-9 – 8,72.10-9") == normalize_for_match("3,38.10-9–8,72.10-9")


def test_decomposed_letters_match_composed_ones():
    assert contains_normalized("Zábřeh", "Za\u0301br\u030ceh")


def test_facts_are_not_loosened():
    assert not contains_normalized("hladina 0,5 m p. t.", "hladina 0,6 m p. t.")
    assert not contains_normalized("závistský přesmyk", "zavistsky presmyk")


def test_empty_needle_never_matches():
    assert not contains_normalized("cokoli", "")
    assert not contains_normalized("cokoli", "   ")
    assert not contains_normalized(None, "x")
