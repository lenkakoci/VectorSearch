"""Tests for turning a --only argument into the stem the manifest is keyed by.

This is the quietest failure the pipeline has produced: `Path(item).stem` on a
report named "ZZ_V.P. - IGP, HGP_final" returns "ZZ_V.P", so the document matched
nothing, the chunking and import stages dropped it without a word, and the run
exited 0 after its extraction had already been paid for.
"""

from __future__ import annotations

from pipeline_common import wanted_stems


def test_a_stem_containing_dots_survives():
    """The case that was broken: the dots are part of the name, not a suffix."""
    assert wanted_stems(["ZZ_V.P. - IGP, HGP_final"]) == {"ZZ_V.P. - IGP, HGP_final"}


def test_every_form_of_the_same_document_gives_one_stem():
    """A stem, a file name and a path all select the same document."""
    forms = [
        "ZZ_V.P. - IGP, HGP_final",
        "ZZ_V.P. - IGP, HGP_final.pdf",
        "PDFs/ZZ_V.P. - IGP, HGP_final.pdf",
    ]
    assert wanted_stems(forms) == {"ZZ_V.P. - IGP, HGP_final"}


def test_a_plain_name_works_in_all_three_forms():
    assert wanted_stems(["Roudno", "Roudno.pdf", "PDFs/Roudno.pdf"]) == {"Roudno"}


def test_a_markdown_source_loses_its_suffix_too():
    """The test fixture is a .md, and it is in the manifest like any other source."""
    assert wanted_stems(["sample_posudek.md"]) == {"sample_posudek"}


def test_several_documents_stay_separate():
    assert wanted_stems(["Roudno", "Zábřeh na Moravě.pdf"]) == {"Roudno", "Zábřeh na Moravě"}
