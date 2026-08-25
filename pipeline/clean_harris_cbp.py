#!/usr/bin/env python3
"""Filter and clean Harris County rows from the 2023 CBP county file."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from pipeline.cbp_schema import (
    ALL_SIZE_CLASS_COLUMNS,
    BASELINE_HARRIS_ROW_COUNT,
    BASELINE_TOTAL_ROWS,
    BASELINE_TWO_DIGIT_ROWS,
    COLUMNS_2017_EXTRA,
    COLUMNS_2023,
    COLUMN_RENAMES,
    DATA_YEAR,
    HARRIS_COUNTY_NAME,
    HARRIS_FIPSCTY,
    HARRIS_FIPSTATE,
    HARRIS_FIPS_FULL,
    INDEPENDENT_HARRIS_TOTAL_EMP,
    INDEPENDENT_HARRIS_TOTAL_EST,
    NAICS_LEVEL_TOTAL,
    NOISE_FLAG_COLUMNS,
    NUMERIC_COLUMNS,
    SIZE_CLASS_1000_DETAIL,
    SIZE_CLASS_COLUMNS,
    noise_flag_label,
    naics_digits,
    parse_naics_level,
)

PROJECT_DIR = Path(__file__).resolve().parent.parent
RAW_FILE = PROJECT_DIR / "data" / "county_files.txt"
OUTPUT_DIR = PROJECT_DIR / "output"
CLEAN_OUTPUT = OUTPUT_DIR / "harris_cbp_2023_clean.csv"
QA_OUTPUT = OUTPUT_DIR / "harris_cbp_2023_data_quality.csv"
PROFILE_OUTPUT = OUTPUT_DIR / "harris_cbp_2023_data_profile.csv"


def load_harris_rows(raw_file: Path) -> pd.DataFrame:
    """Read the nationwide county file and return Harris County rows only."""
    if not raw_file.exists():
        raise FileNotFoundError(f"Raw file not found: {raw_file}")

    chunks: list[pd.DataFrame] = []
    for chunk in pd.read_csv(raw_file, chunksize=100_000, dtype=str):
        mask = (chunk["fipstate"].str.zfill(2) == HARRIS_FIPSTATE) & (
            chunk["fipscty"].str.zfill(3) == HARRIS_FIPSCTY
        )
        filtered = chunk.loc[mask]
        if not filtered.empty:
            chunks.append(filtered)

    if not chunks:
        raise ValueError("No Harris County rows found in the source file.")

    return pd.concat(chunks, ignore_index=True)


def validate_source_schema(df: pd.DataFrame) -> list[str]:
    """Validate that the raw file matches the 2023 layout."""
    issues: list[str] = []

    missing = [col for col in COLUMNS_2023 if col not in df.columns]
    if missing:
        issues.append(f"Missing expected 2023 columns: {missing}")

    unexpected_2017 = [col for col in COLUMNS_2017_EXTRA if col in df.columns]
    if unexpected_2017:
        issues.append(f"Unexpected 2017-only columns present: {unexpected_2017}")

    return issues


def coerce_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Convert numeric fields, treating Census 'N' sentinels as missing."""
    result = df.copy()
    for column in NUMERIC_COLUMNS:
        if column not in result.columns:
            continue
        cleaned = result[column].replace("N", pd.NA)
        result[column] = pd.to_numeric(cleaned, errors="coerce")
    return result


def add_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add semantic helper columns for analysis."""
    result = df.copy()
    result["data_year"] = DATA_YEAR
    result["county_name"] = HARRIS_COUNTY_NAME
    result["fips_full"] = HARRIS_FIPS_FULL
    result["fipstate"] = result["fipstate"].str.zfill(2)
    result["fipscty"] = result["fipscty"].str.zfill(3)
    result["naics_level"] = result["naics"].map(parse_naics_level)
    result["naics_prefix"] = result["naics"].map(naics_digits)
    result["qp1_usd"] = result["qp1"] * 1_000
    result["ap_usd"] = result["ap"] * 1_000

    for column in NOISE_FLAG_COLUMNS:
        label_column = column.replace("_nf", "_noise_label")
        result[label_column] = result[column].map(noise_flag_label)

    return result


def _append_check(
    checks: list[dict[str, object]],
    issues: list[str],
    *,
    name: str,
    expected: object,
    actual: object,
    passed: bool,
) -> None:
    checks.append(
        {
            "check": name,
            "expected": expected,
            "actual": actual,
            "passed": passed,
        }
    )
    if not passed:
        issues.append(f"{name}: expected {expected!r}, got {actual!r}")


def run_qa_checks(
    df: pd.DataFrame,
) -> tuple[list[str], pd.DataFrame, pd.DataFrame]:
    """Run validation checks and build separate check vs profile tables."""
    issues: list[str] = []
    checks: list[dict[str, object]] = []
    profile_rows: list[dict[str, object]] = []

    row_count = len(df)
    _append_check(
        checks,
        issues,
        name="regression_harris_row_count",
        expected=BASELINE_HARRIS_ROW_COUNT,
        actual=row_count,
        passed=row_count == BASELINE_HARRIS_ROW_COUNT,
    )

    total_rows = int((df["naics_level"] == NAICS_LEVEL_TOTAL).sum())
    _append_check(
        checks,
        issues,
        name="regression_total_level_rows",
        expected=BASELINE_TOTAL_ROWS,
        actual=total_rows,
        passed=total_rows == BASELINE_TOTAL_ROWS,
    )

    two_digit_rows = int((df["naics_level"] == "2-digit").sum())
    _append_check(
        checks,
        issues,
        name="regression_two_digit_rows",
        expected=BASELINE_TWO_DIGIT_ROWS,
        actual=two_digit_rows,
        passed=two_digit_rows == BASELINE_TWO_DIGIT_ROWS,
    )

    duplicate_keys = int(df.duplicated(subset=["fipstate", "fipscty", "naics"]).sum())
    _append_check(
        checks,
        issues,
        name="duplicate_keys",
        expected=0,
        actual=duplicate_keys,
        passed=duplicate_keys == 0,
    )

    unknown_levels = int((df["naics_level"] == "unknown").sum())
    _append_check(
        checks,
        issues,
        name="unknown_naics_levels",
        expected=0,
        actual=unknown_levels,
        passed=unknown_levels == 0,
    )

    total_row = df.loc[df["naics_level"] == NAICS_LEVEL_TOTAL]
    if total_row.empty:
        _append_check(
            checks,
            issues,
            name="county_total_row_present",
            expected=1,
            actual=0,
            passed=False,
        )
    else:
        row = total_row.iloc[0]
        est_total = row["est"]
        emp_total = row["emp"]
        size_sum = row[SIZE_CLASS_COLUMNS].sum(skipna=True)
        detail_sum = row[SIZE_CLASS_1000_DETAIL].sum(skipna=True)
        n1000 = row["n1000"]

        _append_check(
            checks,
            issues,
            name="independent_total_establishments",
            expected=INDEPENDENT_HARRIS_TOTAL_EST,
            actual=int(est_total) if pd.notna(est_total) else None,
            passed=pd.notna(est_total) and int(est_total) == INDEPENDENT_HARRIS_TOTAL_EST,
        )
        _append_check(
            checks,
            issues,
            name="independent_total_employment",
            expected=INDEPENDENT_HARRIS_TOTAL_EMP,
            actual=int(emp_total) if pd.notna(emp_total) else None,
            passed=pd.notna(emp_total) and int(emp_total) == INDEPENDENT_HARRIS_TOTAL_EMP,
        )
        _append_check(
            checks,
            issues,
            name="total_est_vs_size_classes",
            expected=f"est={int(est_total)}",
            actual=f"size_sum={int(size_sum)}",
            passed=pd.notna(est_total) and pd.notna(size_sum) and est_total == size_sum,
        )
        _append_check(
            checks,
            issues,
            name="n1000_vs_detail_breakdown",
            expected=int(n1000) if pd.notna(n1000) else None,
            actual=int(detail_sum) if pd.notna(detail_sum) else None,
            passed=pd.notna(n1000) and pd.notna(detail_sum) and n1000 == detail_sum,
        )

        sector_est_sum = df.loc[df["naics_level"] == "2-digit", "est"].sum(skipna=True)
        _append_check(
            checks,
            issues,
            name="two_digit_est_sum_vs_county_total",
            expected=int(est_total) if pd.notna(est_total) else None,
            actual=int(sector_est_sum) if pd.notna(sector_est_sum) else None,
            passed=pd.notna(est_total) and pd.notna(sector_est_sum) and est_total == sector_est_sum,
        )

    for column in df.columns:
        null_count = int(df[column].isna().sum())
        if null_count:
            profile_rows.append(
                {
                    "metric": "null_count",
                    "field": column,
                    "value": null_count,
                }
            )

    for column in NOISE_FLAG_COLUMNS:
        for flag, count in df[column].value_counts(dropna=False).items():
            profile_rows.append(
                {
                    "metric": "noise_flag",
                    "field": column,
                    "value": f"{flag}={int(count)}",
                }
            )

    for column in ALL_SIZE_CLASS_COLUMNS:
        suppressed = int(df[column].isna().sum())
        profile_rows.append(
            {
                "metric": "suppressed_size_class",
                "field": column,
                "value": suppressed,
            }
        )

    return issues, pd.DataFrame(checks), pd.DataFrame(profile_rows)


def clean_harris_cbp(raw_file: Path = RAW_FILE) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    """End-to-end cleaning pipeline."""
    raw_df = load_harris_rows(raw_file)
    schema_issues = validate_source_schema(raw_df)
    if schema_issues:
        raise ValueError("; ".join(schema_issues))

    renamed = raw_df.rename(columns=COLUMN_RENAMES)
    typed = coerce_numeric_columns(renamed)
    cleaned = add_derived_columns(typed)
    issues, qa_df, profile_df = run_qa_checks(cleaned)
    return cleaned, qa_df, profile_df, issues


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    cleaned, qa_df, profile_df, issues = clean_harris_cbp()
    cleaned.to_csv(CLEAN_OUTPUT, index=False)
    qa_df.to_csv(QA_OUTPUT, index=False)
    profile_df.to_csv(PROFILE_OUTPUT, index=False)

    print(f"Wrote {len(cleaned):,} cleaned rows to {CLEAN_OUTPUT}")
    print(f"Wrote QA checks to {QA_OUTPUT}")
    print(f"Wrote data profile to {PROFILE_OUTPUT}")

    failed_checks = qa_df.loc[~qa_df["passed"]]
    if not failed_checks.empty or issues:
        print(f"\n{len(failed_checks)} QA check(s) failed:")
        for _, check in failed_checks.iterrows():
            print(f"  - {check['check']}: expected {check['expected']}, got {check['actual']}")
        return 1

    print("\nAll QA checks passed.")

    total_row = cleaned.loc[cleaned["naics_level"] == NAICS_LEVEL_TOTAL].iloc[0]
    size_sum = total_row[SIZE_CLASS_COLUMNS].sum(skipna=True)
    print("\nHarris County headline totals:")
    print(f"  Establishments: {int(total_row['est']):,}")
    print(f"  Employment: {int(total_row['emp']):,}")
    print(f"  Annual payroll (USD): ${total_row['ap_usd']:,.0f}")
    print(f"  Size-class reconciliation: {int(size_sum):,} == {int(total_row['est']):,}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
