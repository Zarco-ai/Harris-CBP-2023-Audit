"""Tests for the cleaning stage.

Two of these are the most valuable tests in the project. `test_N_sentinel_...`
pins the missing-vs-zero invariant the README claims, and
`test_qa_check_fails_when_...` proves the QA layer can actually fail — the
defect that shipped in the original code was a check that reported a real
discrepancy and marked it `passed: True`.
"""

from __future__ import annotations

import pandas as pd

from pipeline.cbp_schema import SIZE_CLASS_COLUMNS
from pipeline.clean_harris_cbp import (
    add_derived_columns,
    coerce_numeric_columns,
    run_qa_checks,
    validate_source_schema,
)


def _check(qa_df: pd.DataFrame, name: str) -> pd.Series:
    """Pull one named check out of the QA table.

    Tests target a specific check by name rather than asserting "everything
    passed", because the regression baselines in cbp_schema are hardcoded to the
    real 1,709-row dataset and will not match a 4-row fixture. Asserting on the
    check you actually care about keeps the test honest about its own scope.
    """
    matches = qa_df.loc[qa_df["check"] == name]
    assert not matches.empty, f"no check named {name!r}; got {list(qa_df['check'])}"
    return matches.iloc[0]


class TestNumericCoercion:
    """Grouping related tests in a class is purely organisational — pytest
    collects methods here exactly as it collects module-level functions."""

    def test_N_sentinel_becomes_missing_not_zero(self, raw_frame: pd.DataFrame) -> None:
        """"N" must become NA. Turning it into 0 would be a silent data error.

        CBP writes "N" for *not available or not comparable*, and 0 for *we
        counted, there are none*. Conflating them converts "we won't tell you"
        into "there are none" — and every total still computes, so nothing
        looks wrong. That is what makes it dangerous enough to test.
        """
        result = coerce_numeric_columns(raw_frame)
        suppressed = result.loc[result["naics"] == "621111", "n100_249"].iloc[0]

        assert pd.isna(suppressed)
        assert suppressed != 0  # the failure mode this test exists to catch

    def test_real_values_survive_coercion(self, raw_frame: pd.DataFrame) -> None:
        """Coercion must not damage the values that were fine to begin with."""
        result = coerce_numeric_columns(raw_frame)
        total = result.loc[result["naics"] == "------"].iloc[0]

        assert total["est"] == 100
        assert total["emp"] == 1000

    def test_numeric_columns_are_actually_numeric(self, raw_frame: pd.DataFrame) -> None:
        """Strings that look like numbers still break arithmetic. Check the dtype."""
        result = coerce_numeric_columns(raw_frame)
        for column in ["emp", "qp1", "ap", "est", *SIZE_CLASS_COLUMNS]:
            assert pd.api.types.is_numeric_dtype(result[column]), f"{column} is not numeric"


class TestDerivedColumns:
    def test_payroll_is_converted_from_thousands_to_dollars(self, cleaned_frame) -> None:
        """CBP publishes payroll in $1,000s. The _usd columns make that explicit."""
        total = cleaned_frame.loc[cleaned_frame["naics"] == "------"].iloc[0]

        assert total["ap_usd"] == total["ap"] * 1_000
        assert total["qp1_usd"] == total["qp1"] * 1_000

    def test_fips_codes_keep_leading_zeros(self) -> None:
        """FIPS codes are identifiers, not quantities.

        Alabama is "01", not 1. If a state code ever loses its leading zero the
        join against any other geographic dataset breaks — so the zero-padding
        is asserted directly rather than assumed.
        """
        frame = pd.DataFrame(
            [{"fipstate": "1", "fipscty": "5", "naics": "------",
              "emp_nf": "G", "qp1_nf": "G", "ap_nf": "G", "qp1": 1, "ap": 1}]
        )
        result = add_derived_columns(frame)

        assert result["fipstate"].iloc[0] == "01"
        assert result["fipscty"].iloc[0] == "005"

    def test_noise_flags_gain_readable_labels(self, cleaned_frame) -> None:
        """The raw G/H/J is preserved *and* a human-readable label is added."""
        total = cleaned_frame.loc[cleaned_frame["naics"] == "------"].iloc[0]

        assert total["emp_nf"] == "G"
        assert total["emp_noise_label"] == "low"


class TestSchemaValidation:
    def test_accepts_a_valid_2023_frame(self, source_frame: pd.DataFrame) -> None:
        """Note this takes `source_frame`, not `raw_frame`.

        Schema validation runs against the file as read, before COLUMN_RENAMES.
        Handing it renamed columns reports `n<5` as missing — which is exactly
        what happened the first time this suite ran.
        """
        assert validate_source_schema(source_frame) == []

    def test_rejects_a_frame_missing_expected_columns(self, source_frame: pd.DataFrame) -> None:
        issues = validate_source_schema(source_frame.drop(columns=["emp"]))
        assert any("emp" in issue for issue in issues)

    def test_rejects_a_2017_shaped_file(self, source_frame: pd.DataFrame) -> None:
        """Feeding in the wrong data year should fail loudly, not half-work."""
        frame = source_frame.assign(empflag="A", censtate="01", cencty="001")
        issues = validate_source_schema(frame)
        assert any("2017" in issue for issue in issues)


class TestQualityGate:
    """The point of these tests is not that the checks pass. It is that they
    are *capable of failing*. A check that always says yes is worse than no
    check at all, because it manufactures confidence."""

    def test_size_class_check_passes_when_the_data_reconciles(self, cleaned_frame) -> None:
        _, qa_df, _ = run_qa_checks(cleaned_frame)
        assert _check(qa_df, "total_est_vs_size_classes")["passed"]

    def test_size_class_check_fails_when_the_data_does_not_reconcile(self, cleaned_frame) -> None:
        """Break the data on purpose and demand that the gate catches it.

        This is the single most important test here. The original QA layer had
        a pass condition of `pd.notna(expected) and pd.notna(actual)` — it
        compared nothing, so it reported `est=111215, size_sum=111350` and
        marked it passed. Corrupting one bucket and asserting `passed is False`
        makes that class of bug impossible to reintroduce unnoticed.
        """
        broken = cleaned_frame.copy()
        total_row = broken["naics_level"] == "total"
        broken.loc[total_row, "n_lt_5"] = broken.loc[total_row, "n_lt_5"] + 5

        issues, qa_df, _ = run_qa_checks(broken)

        assert not _check(qa_df, "total_est_vs_size_classes")["passed"]
        assert issues, "a failing check must also surface in the issues list"

    def test_duplicate_key_check_fails_on_duplicates(self, cleaned_frame) -> None:
        """One row per (state, county, NAICS). Duplicates would inflate every sum."""
        duplicated = pd.concat([cleaned_frame, cleaned_frame.iloc[[1]]], ignore_index=True)
        _, qa_df, _ = run_qa_checks(duplicated)

        assert not _check(qa_df, "duplicate_keys")["passed"]

    def test_unknown_naics_level_check_fails_on_bad_codes(self, cleaned_frame) -> None:
        """A future Census notation change must trip the gate, not slip through."""
        broken = cleaned_frame.copy()
        broken.loc[broken.index[-1], "naics_level"] = "unknown"
        _, qa_df, _ = run_qa_checks(broken)

        assert not _check(qa_df, "unknown_naics_levels")["passed"]

    def test_profile_rows_are_observations_not_assertions(self, cleaned_frame) -> None:
        """Null counts and flag tallies describe the data; they cannot pass or fail.

        Keeping them out of the QA table is what makes the `passed` column mean
        something. If observations lived there with a hardcoded True, the pass
        rate would always look excellent.
        """
        _, qa_df, profile_df = run_qa_checks(cleaned_frame)

        assert "passed" in qa_df.columns
        assert "passed" not in profile_df.columns
        assert set(profile_df["metric"]) <= {"null_count", "noise_flag", "suppressed_size_class"}
