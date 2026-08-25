"""Tests for the pure functions in cbp_schema.py.

These are the easiest functions in the project to test — no files, no network,
no DataFrames. Start a test suite here. A function that takes a value and
returns a value can be pinned down completely, and `@pytest.mark.parametrize`
lets you state twenty cases in the space of one.
"""

from __future__ import annotations

import pytest

from pipeline.cbp_schema import naics_digits, noise_flag_label, parse_naics_level


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("------", "total"),
        ("11----", "2-digit"),
        ("113///", "3-digit"),
        ("1133//", "4-digit"),
        ("11331/", "5-digit"),
        ("113310", "6-digit"),
    ],
)
def test_parse_naics_level_classifies_every_cbp_notation(code: str, expected: str) -> None:
    """Each of the six CBP code shapes maps to its own level.

    This matters more than it looks. If two shapes collapsed to the same level,
    a summary would aggregate across hierarchy levels and silently double count
    the county — the single biggest trap in this dataset.
    """
    assert parse_naics_level(code) == expected


@pytest.mark.parametrize("code", ["", "abc", "11", "1234567", "11-33", "11***"])
def test_parse_naics_level_rejects_anything_it_does_not_recognise(code: str) -> None:
    """Unrecognised input returns "unknown" rather than guessing.

    "unknown" is load-bearing: clean_harris_cbp asserts that zero rows are
    classified unknown, so a future Census notation change fails the QA gate
    instead of being quietly mis-filed into an existing level.
    """
    assert parse_naics_level(code) == "unknown"


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("------", "all"),
        ("11----", "11"),
        ("113///", "113"),
        ("1133//", "1133"),
        ("11331/", "11331"),
        ("113310", "113310"),
    ],
)
def test_naics_digits_strips_padding(code: str, expected: str) -> None:
    """The meaningful prefix comes back without dashes or slashes."""
    assert naics_digits(code) == expected


@pytest.mark.parametrize(
    ("flag", "expected"),
    [
        ("G", "low"),
        ("H", "medium"),
        ("J", "high"),
        (" G ", "low"),  # whitespace tolerated
        (None, None),
        (float("nan"), None),
        ("Z", None),  # unknown flag -> None, not a crash
        ("", None),
    ],
)
def test_noise_flag_label_maps_census_tiers(flag, expected) -> None:
    """G/H/J become readable labels; everything else becomes None.

    Note the last two cases. An unrecognised flag returns None rather than
    raising — the pipeline should not die on one odd cell — but it also does
    not invent a label, so a new Census flag shows up as missing data you can
    see instead of a wrong label you can't.
    """
    assert noise_flag_label(flag) == expected


def test_noise_flag_labels_are_exhaustive_for_the_2023_layout() -> None:
    """The mapping covers exactly the flags record_layout_2023.txt defines.

    A guard against drift in both directions: adding a flag the layout doesn't
    define, or dropping one it does.
    """
    from pipeline.cbp_schema import NOISE_FLAG_LABELS

    assert set(NOISE_FLAG_LABELS) == {"G", "H", "J"}
