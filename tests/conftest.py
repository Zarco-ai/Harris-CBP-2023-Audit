"""Shared test fixtures.

`conftest.py` is a pytest convention: anything defined here is available to
every test file in this directory without being imported. Fixtures are how you
avoid rebuilding the same setup in twenty tests.

The synthetic frame below deliberately does NOT use real Harris County data.
Unit tests should be fast, deterministic, and readable — if a test fails you
want to see the numbers that broke it, not scroll through 1,709 rows. Tests
that need the real data live in test_invariants.py and are marked `realdata`.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from pipeline.cbp_schema import COLUMNS_2023, COLUMN_RENAMES
from pipeline.clean_harris_cbp import add_derived_columns, coerce_numeric_columns

PROJECT_DIR = Path(__file__).resolve().parent.parent
REAL_CLEAN_FILE = PROJECT_DIR / "output" / "harris_cbp_2023_clean.csv"

def _row(naics: str, emp: str, est: str, buckets: list[str], detail: list[str]) -> dict:
    """Build one raw-shaped CBP row. Every value is a string, as read_csv(dtype=str) gives."""
    return dict(
        zip(
            COLUMNS_2023,
            ["48", "201", naics, "G", emp, "G", "100", "G", "400", est, *buckets, *detail],
        )
    )


@pytest.fixture
def source_frame() -> pd.DataFrame:
    """The file exactly as `read_csv` returns it — column names still `n<5`.

    The fixtures deliberately mirror the pipeline's real stages:

        source_frame  ->  raw_frame       ->  cleaned_frame
        (as read)         (renamed)           (typed + derived)

    `validate_source_schema` runs at the first stage, so it must be given the
    first-stage names. Collapsing these into one fixture is what made the very
    first run of this suite fail — a small illustration of why tests are worth
    writing: the shortcut looked harmless and wasn't.
    """
    return _base_frame(COLUMNS_2023)


@pytest.fixture
def raw_frame(source_frame: pd.DataFrame) -> pd.DataFrame:
    """`source_frame` after COLUMN_RENAMES, which is what the cleaning steps expect."""
    return source_frame.rename(columns=COLUMN_RENAMES)


def _base_frame(columns: list[str]) -> pd.DataFrame:
    """A tiny, hand-checkable stand-in for the raw county file.

    Every reconciliation identity the real data satisfies also holds here, so a
    test that fails against this frame is a real defect rather than a quirk of
    the sample:

        est (total)              = 100
        9 size buckets sum to    = 100
        two 2-digit sectors      = 40 + 60 = 100
        n1000                    = 1, and n1000_1..4 sum to 1

    The 6-digit row carries "N" in several size fields on purpose — that is the
    Census sentinel for "not available", and turning it into 0 is the exact
    mistake the pipeline is built to avoid.
    """
    rows = [
        # naics       emp     est   9 mutually exclusive buckets              n1000_1..4
        _row("------", "1000", "100", ["50", "25", "12", "6", "3", "2", "1", "0", "1"], ["1", "0", "0", "0"]),
        _row("11----", "400", "40", ["20", "10", "5", "3", "1", "1", "0", "0", "0"], ["0", "0", "0", "0"]),
        _row("62----", "600", "60", ["30", "15", "7", "3", "2", "1", "1", "0", "1"], ["1", "0", "0", "0"]),
        _row("621111", "300", "30", ["15", "8", "4", "2", "1", "N", "N", "N", "N"], ["N", "N", "N", "N"]),
    ]
    return pd.DataFrame(rows, columns=columns, dtype=str)


@pytest.fixture
def cleaned_frame(raw_frame: pd.DataFrame) -> pd.DataFrame:
    """`raw_frame` after the two real cleaning steps, so tests exercise actual code."""
    return add_derived_columns(coerce_numeric_columns(raw_frame))


@pytest.fixture
def real_clean_df() -> pd.DataFrame:
    """The genuine cleaned output, or skip if the pipeline hasn't been run.

    Skipping is deliberate: a fresh clone has no output/ directory and no 107 MB
    source file, so these tests cannot run there. A skip is honest. Making them
    fail would train you to ignore red, which is far more dangerous.
    """
    if not REAL_CLEAN_FILE.exists():
        pytest.skip(f"{REAL_CLEAN_FILE.name} not found — run the pipeline first")
    return pd.read_csv(REAL_CLEAN_FILE, dtype={"naics": str})
