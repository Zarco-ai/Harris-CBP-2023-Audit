"""Integration tests against the real cleaned output.

Everything else in this suite runs on a 4-row synthetic frame — fast, and it
proves the *logic* is right. These tests prove the logic was right *on the
actual data*, which is a different claim.

They are marked `realdata` and skip cleanly when output/ hasn't been built, so
`pytest` still works on a fresh clone. Run just these with:

    pytest -m realdata

The expected values here come from two independent sources: `awk` over the raw
county file, and the Census Bureau API. That matters — a constant copied out of
your own pipeline's output only detects *change*, never *error*.
"""

from __future__ import annotations

import pandas as pd
import pytest

from pipeline.cbp_schema import (
    INDEPENDENT_HARRIS_ROW_COUNT,
    INDEPENDENT_HARRIS_TOTAL_EMP,
    INDEPENDENT_HARRIS_TOTAL_EST,
    SIZE_CLASS_1000_DETAIL,
    SIZE_CLASS_COLUMNS,
)

pytestmark = pytest.mark.realdata  # applies the marker to every test in this file


@pytest.fixture
def total_row(real_clean_df: pd.DataFrame) -> pd.Series:
    return real_clean_df.loc[real_clean_df["naics_level"] == "total"].iloc[0]


def test_row_count_matches_independent_count(real_clean_df: pd.DataFrame) -> None:
    """1,709 rows, counted with awk against the raw file, not read off the output."""
    assert len(real_clean_df) == INDEPENDENT_HARRIS_ROW_COUNT


def test_headline_totals_match_the_census_api(total_row: pd.Series) -> None:
    """These two constants came from api.census.gov, outside this pipeline entirely."""
    assert total_row["est"] == INDEPENDENT_HARRIS_TOTAL_EST
    assert total_row["emp"] == INDEPENDENT_HARRIS_TOTAL_EMP


def test_size_buckets_reconcile_to_establishment_total(total_row: pd.Series) -> None:
    """111,215 establishments, and the nine buckets sum to exactly that."""
    assert total_row[SIZE_CLASS_COLUMNS].sum() == total_row["est"]


def test_thousand_plus_detail_reconciles_to_its_parent(total_row: pd.Series) -> None:
    assert total_row[SIZE_CLASS_1000_DETAIL].sum() == total_row["n1000"]


def test_sectors_partition_the_county(real_clean_df: pd.DataFrame, total_row: pd.Series) -> None:
    """All 20 two-digit sectors sum to the county total on all three measures.

    This holds because CBP publishes 31----, 44---- and 48---- as the full
    ranges 31-33, 44-45 and 48-49 — the sum would come up short otherwise.
    """
    sectors = real_clean_df.loc[real_clean_df["naics_level"] == "2-digit"]

    assert len(sectors) == 20
    for measure in ["est", "emp", "ap"]:
        assert sectors[measure].sum() == total_row[measure], f"{measure} does not reconcile"


def test_every_row_is_classified(real_clean_df: pd.DataFrame) -> None:
    """No row may land in "unknown" — that would mean an unrecognised code shape."""
    assert (real_clean_df["naics_level"] == "unknown").sum() == 0


def test_no_duplicate_industry_keys(real_clean_df: pd.DataFrame) -> None:
    assert not real_clean_df.duplicated(subset=["fipstate", "fipscty", "naics"]).any()


def test_only_harris_county_rows_survived_the_filter(real_clean_df: pd.DataFrame) -> None:
    """A filter bug is invisible in the totals if it lets in a neighbouring county."""
    assert set(real_clean_df["fipstate"]) == {48}
    assert set(real_clean_df["fipscty"]) == {201}


def test_noise_flags_are_only_the_documented_tiers(real_clean_df: pd.DataFrame) -> None:
    """record_layout_2023.txt defines G, H and J. Anything else is a surprise."""
    for column in ["emp_nf", "qp1_nf", "ap_nf"]:
        assert set(real_clean_df[column].dropna()) <= {"G", "H", "J"}


def test_suppressed_size_classes_are_missing_rather_than_zero(real_clean_df: pd.DataFrame) -> None:
    """The "N" sentinel must have survived the round-trip through CSV as NaN.

    Worth testing on the real data specifically: pandas writes NA as an empty
    field, and a careless `read_csv(...).fillna(0)` downstream would undo the
    whole point without changing any total you'd notice.
    """
    assert real_clean_df["n1000"].isna().sum() > 0
    assert (real_clean_df["n1000"] == 0).sum() == 0
