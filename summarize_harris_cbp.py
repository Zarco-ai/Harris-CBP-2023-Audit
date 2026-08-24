#!/usr/bin/env python3
"""Generate level-scoped summary tables from the cleaned Harris County CBP file."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from cbp_schema import (
    ALL_SIZE_CLASS_COLUMNS,
    NAICS_LEVEL_TOTAL,
    NOISE_FLAG_COLUMNS,
    SIZE_CLASS_1000_DETAIL,
    SIZE_CLASS_COLUMNS,
)

PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_DIR / "output"
CLEAN_INPUT = OUTPUT_DIR / "harris_cbp_2023_clean.csv"

SUMMARY_COUNTY_TOTALS = OUTPUT_DIR / "summary_county_totals.csv"
SUMMARY_BY_SECTOR = OUTPUT_DIR / "summary_by_sector.csv"
SUMMARY_TOP_INDUSTRIES = OUTPUT_DIR / "summary_top_industries.csv"
SUMMARY_SIZE_DISTRIBUTION = OUTPUT_DIR / "summary_size_distribution.csv"
SUMMARY_SIZE_1000_DETAIL = OUTPUT_DIR / "summary_size_1000_detail.csv"
SUMMARY_DATA_QUALITY = OUTPUT_DIR / "summary_data_quality.csv"

TOP_N = 25

SIZE_BUCKET_LABELS = {
    "n_lt_5": "Less than 5",
    "n5_9": "5-9",
    "n10_19": "10-19",
    "n20_49": "20-49",
    "n50_99": "50-99",
    "n100_249": "100-249",
    "n250_499": "250-499",
    "n500_999": "500-999",
    "n1000": "1,000+",
}

SIZE_1000_DETAIL_LABELS = {
    "n1000_1": "1,000-1,499",
    "n1000_2": "1,500-2,499",
    "n1000_3": "2,500-4,999",
    "n1000_4": "5,000+",
}


def load_clean_data(clean_file: Path = CLEAN_INPUT) -> pd.DataFrame:
    if not clean_file.exists():
        raise FileNotFoundError(
            f"Clean file not found: {clean_file}. Run clean_harris_cbp.py first."
        )
    return pd.read_csv(clean_file)


def build_county_totals(df: pd.DataFrame) -> pd.DataFrame:
    total = df.loc[df["naics_level"] == NAICS_LEVEL_TOTAL].copy()
    columns = [
        "data_year",
        "county_name",
        "fips_full",
        "naics",
        "naics_level",
        "est",
        "emp",
        "qp1",
        "ap",
        "qp1_usd",
        "ap_usd",
        "emp_nf",
        "emp_noise_label",
        "qp1_nf",
        "qp1_noise_label",
        "ap_nf",
        "ap_noise_label",
        *ALL_SIZE_CLASS_COLUMNS,
    ]
    return total[columns]


def build_sector_summary(df: pd.DataFrame) -> pd.DataFrame:
    sectors = df.loc[df["naics_level"] == "2-digit"].copy()
    columns = [
        "naics",
        "naics_prefix",
        "est",
        "emp",
        "ap_usd",
        "emp_nf",
        "emp_noise_label",
        "ap_nf",
        "ap_noise_label",
    ]
    return sectors[columns].sort_values("emp", ascending=False)


def build_top_industries(df: pd.DataFrame, top_n: int = TOP_N) -> pd.DataFrame:
    detail = df.loc[df["naics_level"] == "6-digit"].copy()
    columns = [
        "naics",
        "naics_prefix",
        "est",
        "emp",
        "ap_usd",
        "emp_nf",
        "emp_noise_label",
    ]

    top_emp = detail.nlargest(top_n, "emp")[columns].assign(rank_metric="employment")
    top_est = detail.nlargest(top_n, "est")[columns].assign(rank_metric="establishments")
    top_ap = detail.nlargest(top_n, "ap_usd")[columns].assign(rank_metric="annual_payroll")

    combined = pd.concat([top_emp, top_est, top_ap], ignore_index=True)
    combined["rank"] = combined.groupby("rank_metric").cumcount() + 1
    return combined.sort_values(["rank_metric", "rank"])


def build_size_distribution(df: pd.DataFrame) -> pd.DataFrame:
    """Build mutually exclusive size-bucket percentages (excludes n1000 detail columns)."""
    total = df.loc[df["naics_level"] == NAICS_LEVEL_TOTAL].iloc[0]
    rows: list[dict[str, object]] = []
    est_total = total["est"]

    for column in SIZE_CLASS_COLUMNS:
        establishments = total[column]
        rows.append(
            {
                "size_bucket": SIZE_BUCKET_LABELS[column],
                "size_column": column,
                "establishments": establishments,
                "pct_of_total_establishments": (
                    round(establishments / est_total * 100, 2)
                    if pd.notna(establishments) and est_total
                    else pd.NA
                ),
            }
        )

    return pd.DataFrame(rows)


def build_size_1000_detail(df: pd.DataFrame) -> pd.DataFrame:
    """Drill-down within the n1000 bucket — percentages are of n1000, not county total."""
    total = df.loc[df["naics_level"] == NAICS_LEVEL_TOTAL].iloc[0]
    n1000_total = total["n1000"]
    rows: list[dict[str, object]] = []

    for column in SIZE_CLASS_1000_DETAIL:
        establishments = total[column]
        rows.append(
            {
                "size_bucket": SIZE_1000_DETAIL_LABELS[column],
                "size_column": column,
                "establishments": establishments,
                "pct_of_n1000_establishments": (
                    round(establishments / n1000_total * 100, 2)
                    if pd.notna(establishments) and n1000_total
                    else pd.NA
                ),
            }
        )

    return pd.DataFrame(rows)


def build_data_quality_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    for level, group in df.groupby("naics_level", sort=False):
        row: dict[str, object] = {
            "naics_level": level,
            "row_count": len(group),
            "high_noise_emp_rows": int((group["emp_nf"] == "J").sum()),
            "high_noise_emp_pct": round((group["emp_nf"] == "J").mean() * 100, 2),
        }

        suppressed_counts = {
            column: int(group[column].isna().sum()) for column in ALL_SIZE_CLASS_COLUMNS
        }
        row["avg_suppressed_size_fields_per_row"] = round(
            sum(suppressed_counts.values()) / len(group), 2
        )
        row["total_suppressed_size_fields"] = sum(suppressed_counts.values())
        rows.append(row)

    quality = pd.DataFrame(rows)

    for column in NOISE_FLAG_COLUMNS:
        flag_counts = (
            df.groupby("naics_level")[column]
            .value_counts(dropna=False)
            .rename("count")
            .reset_index()
        )
        flag_counts["metric"] = column
        flag_counts = flag_counts.rename(columns={column: "flag_value"})
        quality = quality.merge(
            flag_counts.pivot(index="naics_level", columns="flag_value", values="count").add_prefix(
                f"{column}_"
            ),
            left_on="naics_level",
            right_index=True,
            how="left",
        )

    return quality


def summarize_harris_cbp(clean_file: Path = CLEAN_INPUT) -> dict[str, pd.DataFrame]:
    df = load_clean_data(clean_file)
    return {
        "county_totals": build_county_totals(df),
        "by_sector": build_sector_summary(df),
        "top_industries": build_top_industries(df),
        "size_distribution": build_size_distribution(df),
        "size_1000_detail": build_size_1000_detail(df),
        "data_quality": build_data_quality_summary(df),
    }


def main() -> int:
    summaries = summarize_harris_cbp()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summaries["county_totals"].to_csv(SUMMARY_COUNTY_TOTALS, index=False)
    summaries["by_sector"].to_csv(SUMMARY_BY_SECTOR, index=False)
    summaries["top_industries"].to_csv(SUMMARY_TOP_INDUSTRIES, index=False)
    summaries["size_distribution"].to_csv(SUMMARY_SIZE_DISTRIBUTION, index=False)
    summaries["size_1000_detail"].to_csv(SUMMARY_SIZE_1000_DETAIL, index=False)
    summaries["data_quality"].to_csv(SUMMARY_DATA_QUALITY, index=False)

    total = summaries["county_totals"].iloc[0]
    size_pct_sum = summaries["size_distribution"]["pct_of_total_establishments"].sum()

    print("Summary files written to output/:")
    print(f"  {SUMMARY_COUNTY_TOTALS.name}")
    print(f"  {SUMMARY_BY_SECTOR.name}")
    print(f"  {SUMMARY_TOP_INDUSTRIES.name}")
    print(f"  {SUMMARY_SIZE_DISTRIBUTION.name}")
    print(f"  {SUMMARY_SIZE_1000_DETAIL.name}")
    print(f"  {SUMMARY_DATA_QUALITY.name}")

    print("\nHarris County headline totals:")
    print(f"  Establishments: {int(total['est']):,}")
    print(f"  Employment: {int(total['emp']):,}")
    print(f"  Annual payroll (USD): ${total['ap_usd']:,.0f}")
    print(f"  Size distribution pct sum: {size_pct_sum:.2f}%")

    return 0


if __name__ == "__main__":
    sys.exit(main())
