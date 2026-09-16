# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""Regression tests for the cadastral attribute translation.

    python tests/test_translations.py

Plain asserts and a ``main``, so this runs with no test runner installed; pytest
will also collect it if you have it.

These guard two bugs that were silent — they produced a complete, plausible-looking
GeoPackage with wrong values in two columns, on every one of its 2,762 rows:

* ``andamal1`` is compound, ``"<Type>;<Purpose>"``, but the lookup table is keyed on
  the purpose half alone. Every value came back untranslated and every row landed in
  category ``"Other"``.
* ``insamlingslage`` arrives capitalised while its table is keyed lowercase, so that
  lookup matched nothing at all.

The counts below are the real distribution of the Helsingborg extract, so a
regression here is measured against the actual data rather than an invented case.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from footprint_extraction.byggnad_pipeline import (  # noqa: E402
    purpose_category,
    split_purpose,
    translate_collection_level,
    translate_purpose,
)

# (raw value, expected English, expected category, rows in the sample extract)
PURPOSES = [
    ("Komplementbyggnad;", "Ancillary building", "Ancillary", 1763),
    ("Bostad;Småhus friliggande", "Single-family detached house", "Residence", 493),
    ("Bostad;Småhus kedjehus", "Townhouse/chain house", "Residence", 228),
    ("Bostad;Småhus radhus", "Row house", "Residence", 160),
    ("Bostad;Småhus med flera lägenheter", "Multi-unit small building", "Residence", 53),
    ("Samhällsfunktion;Ospecificerad", "Public facility", "Public", 26),
    ("Bostad;Flerfamiljshus", "Multi-family apartment building", "Residence", 19),
    ("Övrig byggnad;", "Other building", "Other", 9),
]

COLLECTION_LEVELS = [
    ("Fasad", "Facade", 2108),
    ("Ospecificerad", "Unspecified", 618),
    ("Takkant", "Roof edge", 36),
]


def test_purpose_translation():
    """Every observed compound value translates, and none falls through."""
    for raw, expected_en, expected_cat, _ in PURPOSES:
        assert translate_purpose(raw) == expected_en, (
            f"{raw!r} -> {translate_purpose(raw)!r}, expected {expected_en!r}"
        )
        assert purpose_category(raw) == expected_cat, (
            f"{raw!r} -> {purpose_category(raw)!r}, expected {expected_cat!r}"
        )


def test_purpose_is_actually_translated():
    """The regression itself: output must not be the untranslated input.

    The original bug was not a crash. It returned the raw Swedish string, which
    looks like data until you read it.
    """
    for raw, _, _, _ in PURPOSES:
        assert translate_purpose(raw) != raw, f"{raw!r} came back untranslated"


def test_no_blanket_other_category():
    """No more than one observed value may land in 'Other'.

    Before the fix all 2,762 rows were categorised 'Other'. Only the genuine
    "Övrig byggnad" (other building) should be.
    """
    categories = [purpose_category(raw) for raw, _, _, _ in PURPOSES]
    assert categories.count("Other") == 1, f"too many 'Other': {categories}"

    # Of the 2,751 sample rows, only the 9 genuine "Övrig byggnad" rows are
    # uncategorised. Before the fix this number was 0.
    covered = sum(n for (raw, _, _, n) in PURPOSES if purpose_category(raw) != "Other")
    assert covered == 2742, f"unexpected covered-row count {covered}"


def test_collection_level_casefolds():
    """Capitalised source values must resolve; a direct lookup matches nothing."""
    for raw, expected, _ in COLLECTION_LEVELS:
        assert translate_collection_level(raw) == expected, (
            f"{raw!r} -> {translate_collection_level(raw)!r}, expected {expected!r}"
        )
        assert translate_collection_level(raw) != raw


def test_split_purpose_edges():
    """Splitting is total: no input shape raises."""
    assert split_purpose("Bostad;Flerfamiljshus") == ("Bostad", "Flerfamiljshus")
    # Type-only, trailing semicolon: the purpose half is absent, not empty-string.
    assert split_purpose("Komplementbyggnad;") == ("Komplementbyggnad", None)
    # "Unspecified" is a non-answer and defers to the type half.
    assert split_purpose("Samhällsfunktion;Ospecificerad") == ("Samhällsfunktion", None)
    assert split_purpose("") == (None, None)
    assert split_purpose(None) == (None, None)
    assert split_purpose(float("nan")) == (None, None)


def test_unknown_values_pass_through():
    """An unrecognised value is returned as-is, never silently blanked."""
    assert translate_purpose("Nonsens;Påhittat") == "Påhittat"
    assert purpose_category("Nonsens;Påhittat") == "Other"
    assert translate_collection_level("Okänt") == "Okänt"
    assert translate_purpose(None) is None


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL  {test.__name__}: {exc}")

    total_rows = sum(n for *_, n in PURPOSES)
    print(f"\n{len(tests) - failed}/{len(tests)} passed "
          f"({total_rows:,} rows of the sample extract covered)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
