"""Tests for the summary builders.

The first class is a regression test for the bug this project is named after.
A regression test is one written *after* a defect is found, whose only job is
to fail if that exact defect ever returns. It is the highest-value test you can
write, because unlike a hypothetical bug, this one has already proven it can
happen here.
"""

from __future__ import annotations

import pandas as pd

from pipeline.cbp_schema import SIZE_CLASS_1000_DETAIL, SIZE_CLASS_COLUMNS
from pipeline.summarize_harris_cbp import (
    build_sector_summary,
    build_size_1000_detail,
    build_size_distribution,
    build_top_industries,
)


class TestSizeDistributionDoubleCount:
    """The original defect: `n1000_1`..`n1000_4` are subdivisions *of* `n1000`,
    not additional buckets beside it. Summing all thirteen counted every
    1,000+ establishment twice."""

    def test_only_the_nine_mutually_exclusive_buckets_appear(self, cleaned_frame) -> None:
        """The detail bands must not be in the distribution table at all."""
        distribution = build_size_distribution(cleaned_frame)

        assert len(distribution) == 9
        assert list(distribution["size_column"]) == SIZE_CLASS_COLUMNS
        assert not set(distribution["size_column"]) & set(SIZE_CLASS_1000_DETAIL)

    def test_buckets_sum_to_the_establishment_total(self, cleaned_frame) -> None:
        """The identity that exposed the bug: parts must equal the whole.

        Every dataset has at least one relationship like this. Find it, assert
        it, and any drift becomes a failing test instead of a plausible number.
        """
        distribution = build_size_distribution(cleaned_frame)
        total_est = cleaned_frame.loc[cleaned_frame["naics_level"] == "total", "est"].iloc[0]

        assert distribution["establishments"].sum() == total_est

    def test_percentages_never_exceed_one_hundred(self, cleaned_frame) -> None:
        """The symptom that surfaced the defect: the column summed to 100.12%.

        Nothing can be more than 100% of itself. Cheap to check, and it points
        straight at a double count.
        """
        distribution = build_size_distribution(cleaned_frame)
        assert distribution["pct_of_total_establishments"].sum() <= 100.0

    def test_detail_bands_are_a_percentage_of_n1000_not_the_county(self, cleaned_frame) -> None:
        """The drill-down uses its own denominator, so its percentages sum to 100.

        Getting this wrong is the mirror image of the original bug: correct
        numerator, wrong denominator, and the output looks reasonable either way.
        """
        detail = build_size_1000_detail(cleaned_frame)

        assert list(detail["size_column"]) == SIZE_CLASS_1000_DETAIL
        assert detail["pct_of_n1000_establishments"].sum() == 100.0

    def test_detail_bands_sum_back_to_n1000(self, cleaned_frame) -> None:
        detail = build_size_1000_detail(cleaned_frame)
        n1000 = cleaned_frame.loc[cleaned_frame["naics_level"] == "total", "n1000"].iloc[0]

        assert detail["establishments"].sum() == n1000


class TestLevelScoping:
    """CBP reports the same establishments at six levels of detail. Every
    summary must filter to exactly one level before aggregating, or it inflates
    every figure it produces."""

    def test_sector_summary_contains_only_two_digit_rows(self, cleaned_frame) -> None:
        sectors = build_sector_summary(cleaned_frame)

        assert len(sectors) == 2
        assert set(sectors["naics"]) == {"11----", "62----"}

    def test_sector_rows_reconcile_to_the_county_total(self, cleaned_frame) -> None:
        """Sectors partition the county, so they must sum back to it exactly."""
        sectors = build_sector_summary(cleaned_frame)
        total = cleaned_frame.loc[cleaned_frame["naics_level"] == "total"].iloc[0]

        assert sectors["est"].sum() == total["est"]
        assert sectors["emp"].sum() == total["emp"]

    def test_top_industries_contains_only_six_digit_rows(self, cleaned_frame) -> None:
        """A 2-digit row leaking in here would rank an entire sector against
        one industry — and it would look like a plausible result."""
        top = build_top_industries(cleaned_frame, top_n=5)

        assert set(top["naics"]) == {"621111"}

    def test_top_industries_produces_all_three_rankings(self, cleaned_frame) -> None:
        top = build_top_industries(cleaned_frame, top_n=5)
        assert set(top["rank_metric"]) == {"employment", "establishments", "annual_payroll"}

    def test_each_ranking_is_ordered_descending(self) -> None:
        """Rank 1 must be the largest. Ordering bugs are easy to miss by eye."""
        frame = pd.DataFrame(
            {
                "naics": ["111111", "222222", "333333"],
                "naics_prefix": ["111111", "222222", "333333"],
                "naics_level": ["6-digit"] * 3,
                "est": [1, 2, 3],
                "emp": [10, 300, 200],
                "ap_usd": [5, 15, 10],
                "emp_nf": ["G"] * 3,
                "emp_noise_label": ["low"] * 3,
            }
        )
        top = build_top_industries(frame, top_n=3)

        by_employment = top.loc[top["rank_metric"] == "employment"].sort_values("rank")
        assert list(by_employment["emp"]) == [300, 200, 10]
        assert list(by_employment["rank"]) == [1, 2, 3]
