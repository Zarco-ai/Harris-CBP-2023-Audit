#!/usr/bin/env python3
"""Build a human-readable table and charts from the cleaned Harris County CBP file."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path

# Use a project-local matplotlib config dir so font/cache writes work in restricted environments.
os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(__file__).resolve().parent.parent / ".mplconfig")
)

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from pipeline.summarize_harris_cbp import (
    build_county_totals,
    build_sector_summary,
    build_size_distribution,
    build_top_industries,
    load_clean_data,
)

PROJECT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_DIR / "output"
CLEAN_INPUT = OUTPUT_DIR / "harris_cbp_2023_clean.csv"
READABLE_TABLE = OUTPUT_DIR / "harris_cbp_2023_readable.csv"
CHART_DIR = OUTPUT_DIR / "charts"

NAICS_SECTOR_NAMES: dict[str, str] = {
    "11": "Agriculture, Forestry, Fishing & Hunting",
    "21": "Mining & Oil/Gas Extraction",
    "22": "Utilities",
    "23": "Construction",
    "31": "Manufacturing",
    "32": "Manufacturing",
    "33": "Manufacturing",
    "42": "Wholesale Trade",
    "44": "Retail Trade",
    "45": "Retail Trade",
    "48": "Transportation & Warehousing",
    "49": "Transportation & Warehousing",
    "51": "Information",
    "52": "Finance & Insurance",
    "53": "Real Estate & Rental",
    "54": "Professional & Technical Services",
    "55": "Management of Companies",
    "56": "Administrative & Support Services",
    "61": "Educational Services",
    "62": "Health Care & Social Assistance",
    "71": "Arts, Entertainment & Recreation",
    "72": "Accommodation & Food Services",
    "81": "Other Services",
    "99": "Unclassified",
}

NAICS_INDUSTRY_NAMES: dict[str, str] = {
    "551114": "Corporate/Regional Managing Offices",
    "722511": "Full-Service Restaurants",
    "722513": "Limited-Service Restaurants",
    "622110": "General Medical & Surgical Hospitals",
    "541330": "Engineering Services",
    "445110": "Supermarkets & Grocery Stores",
    "621111": "Offices of Physicians",
    "561320": "Temporary Help Services",
    "621610": "Home Health Care Services",
    "622310": "Specialty Hospitals",
    "541110": "Offices of Lawyers",
    "561720": "Janitorial Services",
    "813110": "Religious Organizations",
    "611310": "Colleges & Universities",
    "452311": "Warehouse Clubs & Supercenters",
    "611110": "Elementary & Secondary Schools",
    "237120": "Oil & Gas Pipeline Construction",
    "238220": "Plumbing, Heating & AC Contractors",
    "441110": "New Car Dealers",
    "522110": "Commercial Banking",
    "811310": "Automotive Repair & Maintenance",
    "238210": "Electrical Contractors",
    "493110": "General Warehousing & Storage",
    "481111": "Scheduled Passenger Air Transportation",
    "561612": "Security Guards & Patrol Services",
    "541611": "Administrative Management Consulting",
    "523120": "Securities Brokerage",
    "211120": "Crude Petroleum Extraction",
    "213112": "Support Activities for Oil & Gas",
    "423830": "Industrial Machinery Wholesalers",
    "541211": "Offices of Certified Public Accountants",
    "541715": "R&D in Physical/Engineering Sciences",
    "561110": "Office Administrative Services",
}

TOP_N = 15
NOISE_FOOTNOTE_HIGH = (
    "Hatched bars: Census high-noise estimate (≥5% noise injected per CBP)."
)
NOISE_FOOTNOTE_MEDIUM = (
    "Bold outline: Census medium-noise estimate (2–5% noise injected per CBP)."
)
NOISE_FOOTNOTE_BOTH = (
    "Hatched = high noise (≥5%); bold outline = medium noise (2–5%) per Census CBP."
)
SMALL_BAR_LABEL_THRESHOLD = 0.01


def format_currency(value: float | int | None) -> str:
    if pd.isna(value):
        return ""
    return f"${value:,.0f}"


def format_count(value: float | int | None) -> str:
    if pd.isna(value):
        return ""
    return f"{int(value):,}"


def sector_label(prefix: str) -> str:
    name = NAICS_SECTOR_NAMES.get(prefix, "Unknown sector")
    return f"{prefix} — {name}"


def industry_label(code: str) -> str:
    name = NAICS_INDUSTRY_NAMES.get(code, "Unknown industry")
    return f"{code} — {name}"


def apply_noise_styling(
    ax: plt.Axes,
    rows: pd.DataFrame,
    noise_col: str = "emp_nf",
) -> tuple[bool, bool]:
    """Visually distinguish medium- and high-noise Census estimates."""
    has_high_noise = False
    has_medium_noise = False

    for patch, (_, row) in zip(ax.patches, rows.iterrows()):
        flag = row.get(noise_col)
        if flag == "J":
            patch.set_hatch("///")
            patch.set_edgecolor("#333333")
            patch.set_linewidth(1.2)
            has_high_noise = True
        elif flag == "H":
            patch.set_edgecolor("#555555")
            patch.set_linewidth(2.0)
            has_medium_noise = True

    return has_high_noise, has_medium_noise


def add_noise_footnote(
    fig: plt.Figure,
    has_high_noise: bool,
    has_medium_noise: bool,
) -> None:
    if has_high_noise and has_medium_noise:
        text = NOISE_FOOTNOTE_BOTH
    elif has_high_noise:
        text = NOISE_FOOTNOTE_HIGH
    elif has_medium_noise:
        text = NOISE_FOOTNOTE_MEDIUM
    else:
        return

    fig.text(
        0.01,
        0.01,
        text,
        ha="left",
        va="bottom",
        fontsize=9,
        style="italic",
        color="#444444",
    )


def declutter_labels(
    fig: plt.Figure,
    annotations: list,
    *,
    max_passes: int = 80,
    pad_points: float = 1.5,
) -> None:
    """Nudge overlapping point labels apart vertically until none collide.

    Annotations must use textcoords="offset points" so their offset can be
    adjusted in place. Only the vertical offset moves, so each label stays on
    the side of its marker that the caller chose.
    """
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    px_to_points = 72.0 / fig.dpi

    def shift(annotation, delta_points: float) -> None:
        offset_x, offset_y = annotation.xyann
        annotation.xyann = (offset_x, offset_y + delta_points)

    for _ in range(max_passes):
        boxes = [ann.get_window_extent(renderer=renderer) for ann in annotations]
        collided = False

        for i in range(len(annotations)):
            for j in range(i + 1, len(annotations)):
                if not boxes[i].overlaps(boxes[j]):
                    continue

                overlap_px = min(boxes[i].y1, boxes[j].y1) - max(boxes[i].y0, boxes[j].y0)
                step = (overlap_px * px_to_points) / 2 + pad_points
                lower, upper = (i, j) if boxes[i].y0 <= boxes[j].y0 else (j, i)
                shift(annotations[lower], -step)
                shift(annotations[upper], step)

                boxes[lower] = annotations[lower].get_window_extent(renderer=renderer)
                boxes[upper] = annotations[upper].get_window_extent(renderer=renderer)
                collided = True

        if not collided:
            return


def label_small_horizontal_bars(
    ax: plt.Axes,
    rows: pd.DataFrame,
    value_col: str,
    *,
    threshold_ratio: float = SMALL_BAR_LABEL_THRESHOLD,
    value_formatter: Callable[[float], str] | None = None,
) -> None:
    """Add value labels for bars too small to read at chart scale."""
    max_value = rows[value_col].max()
    if not max_value:
        return

    threshold = max_value * threshold_ratio
    offset = max_value * 0.012
    formatter = value_formatter or (lambda value: f"{int(value):,}")

    for patch, (_, row) in zip(ax.patches, rows.iterrows()):
        value = row[value_col]
        if value > threshold:
            continue
        ax.text(
            patch.get_width() + offset,
            patch.get_y() + patch.get_height() / 2,
            formatter(value),
            va="center",
            ha="left",
            fontsize=8.5,
            color="#333333",
        )


def build_readable_table(df: pd.DataFrame) -> pd.DataFrame:
    """Create a presentation-friendly table from sector and industry detail rows."""
    county = build_county_totals(df).iloc[0]
    sectors = build_sector_summary(df).copy()
    top_industries = build_top_industries(df, top_n=TOP_N)
    top_industries = top_industries.loc[top_industries["rank_metric"] == "employment"].copy()

    county_row = pd.DataFrame(
        [
            {
                "section": "County total",
                "industry": "All industries",
                "naics_code": county["naics"],
                "detail_level": county["naics_level"],
                "establishments": county["est"],
                "employment": county["emp"],
                "q1_payroll_usd": county["qp1_usd"],
                "annual_payroll_usd": county["ap_usd"],
                "employment_data_quality": county["emp_noise_label"],
                "payroll_data_quality": county["ap_noise_label"],
            }
        ]
    )

    sector_rows = pd.DataFrame(
        {
            "section": "Sector (2-digit NAICS)",
            "industry": sectors["naics_prefix"].map(sector_label),
            "naics_code": sectors["naics"],
            "detail_level": "2-digit",
            "establishments": sectors["est"],
            "employment": sectors["emp"],
            "q1_payroll_usd": pd.NA,
            "annual_payroll_usd": sectors["ap_usd"],
            "employment_data_quality": sectors["emp_noise_label"],
            "payroll_data_quality": sectors["ap_noise_label"],
        }
    )

    industry_rows = pd.DataFrame(
        {
            "section": f"Top {TOP_N} industries by employment",
            "industry": top_industries["naics_prefix"].map(industry_label),
            "naics_code": top_industries["naics"],
            "detail_level": "6-digit",
            "establishments": top_industries["est"],
            "employment": top_industries["emp"],
            "q1_payroll_usd": pd.NA,
            "annual_payroll_usd": top_industries["ap_usd"],
            "employment_data_quality": top_industries["emp_noise_label"],
            "payroll_data_quality": pd.NA,
        }
    )

    readable = pd.concat([county_row, sector_rows, industry_rows], ignore_index=True)

    display = readable.copy()
    display["establishments"] = display["establishments"].map(format_count)
    display["employment"] = display["employment"].map(format_count)
    display["q1_payroll_usd"] = display["q1_payroll_usd"].map(format_currency)
    display["annual_payroll_usd"] = display["annual_payroll_usd"].map(format_currency)

    display = display.rename(
        columns={
            "section": "Section",
            "industry": "Industry",
            "naics_code": "NAICS code",
            "detail_level": "Detail level",
            "establishments": "Establishments",
            "employment": "Employment",
            "q1_payroll_usd": "Q1 payroll",
            "annual_payroll_usd": "Annual payroll",
            "employment_data_quality": "Employment quality",
            "payroll_data_quality": "Payroll quality",
        }
    )

    return display


def configure_plot_style() -> None:
    sns.set_theme(style="whitegrid", context="talk", font_scale=0.9)
    plt.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.titlesize": 16,
            "axes.titleweight": "bold",
            "hatch.linewidth": 0.8,
        }
    )


def plot_sector_employment(df: pd.DataFrame) -> Path:
    sectors = build_sector_summary(df).copy()
    sectors["sector"] = sectors["naics_prefix"].map(sector_label)
    sectors = sectors.sort_values("emp", ascending=True).reset_index(drop=True)

    fig, ax = plt.subplots(figsize=(12, 9))
    sns.barplot(
        data=sectors,
        y="sector",
        x="emp",
        hue="sector",
        dodge=False,
        palette="crest",
        legend=False,
        ax=ax,
    )
    has_high_noise, has_medium_noise = apply_noise_styling(ax, sectors)
    label_small_horizontal_bars(ax, sectors, "emp")

    ax.set_title("Employment by Sector\nHarris County, TX — 2023 CBP")
    ax.set_xlabel("Employment")
    ax.set_ylabel("")
    ax.xaxis.set_major_formatter(lambda x, _pos: f"{x:,.0f}")
    add_noise_footnote(fig, has_high_noise, has_medium_noise)

    output = CHART_DIR / "sector_employment.png"
    fig.subplots_adjust(bottom=0.12)
    fig.savefig(output, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return output


def plot_sector_payroll(df: pd.DataFrame) -> Path:
    sectors = build_sector_summary(df).copy()
    sectors["sector"] = sectors["naics_prefix"].map(sector_label)
    sectors["annual_payroll_billions"] = sectors["ap_usd"] / 1_000_000_000
    sectors = sectors.sort_values("annual_payroll_billions", ascending=True).reset_index(drop=True)

    fig, ax = plt.subplots(figsize=(12, 9))
    sns.barplot(
        data=sectors,
        y="sector",
        x="annual_payroll_billions",
        hue="sector",
        dodge=False,
        palette="flare",
        legend=False,
        ax=ax,
    )
    has_high_noise, has_medium_noise = apply_noise_styling(ax, sectors, noise_col="ap_nf")
    label_small_horizontal_bars(
        ax,
        sectors,
        "annual_payroll_billions",
        value_formatter=lambda value: f"${value:.2f}B",
    )

    ax.set_title("Annual Payroll by Sector\nHarris County, TX — 2023 CBP")
    ax.set_xlabel("Annual payroll (billions USD)")
    ax.set_ylabel("")
    ax.xaxis.set_major_formatter(lambda x, _pos: f"${x:,.1f}B")
    add_noise_footnote(fig, has_high_noise, has_medium_noise)

    output = CHART_DIR / "sector_annual_payroll.png"
    fig.subplots_adjust(bottom=0.12)
    fig.savefig(output, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return output


def plot_size_distribution(df: pd.DataFrame) -> Path:
    sizes = build_size_distribution(df).copy()
    sizes = sizes.sort_values("establishments", ascending=False).reset_index(drop=True)

    fig, ax = plt.subplots(figsize=(12, 7))
    sns.barplot(
        data=sizes,
        x="size_bucket",
        y="establishments",
        hue="size_bucket",
        dodge=False,
        palette="viridis",
        legend=False,
        ax=ax,
    )
    ax.set_title("Establishments by Size Class\nHarris County, TX — 2023 CBP")
    ax.set_xlabel("Establishment size (employees)")
    ax.set_ylabel("Number of establishments")
    ax.yaxis.set_major_formatter(lambda x, _pos: f"{x:,.0f}")
    plt.setp(ax.get_xticklabels(), rotation=35, ha="right")

    output = CHART_DIR / "establishment_size_distribution.png"
    fig.tight_layout()
    fig.savefig(output, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return output


def plot_top_industries(df: pd.DataFrame) -> Path:
    top = build_top_industries(df, top_n=TOP_N)
    top = top.loc[top["rank_metric"] == "employment"].copy()
    top["industry"] = top["naics_prefix"].map(industry_label)
    top = top.sort_values("emp", ascending=True).reset_index(drop=True)

    fig, ax = plt.subplots(figsize=(13, 9))
    sns.barplot(
        data=top,
        y="industry",
        x="emp",
        hue="industry",
        dodge=False,
        palette="mako",
        legend=False,
        ax=ax,
    )
    has_high_noise, has_medium_noise = apply_noise_styling(ax, top)
    add_noise_footnote(fig, has_high_noise, has_medium_noise)

    ax.set_title(f"Top {TOP_N} Industries by Employment\nHarris County, TX — 2023 CBP")
    ax.set_xlabel("Employment")
    ax.set_ylabel("")
    ax.xaxis.set_major_formatter(lambda x, _pos: f"{x:,.0f}")

    output = CHART_DIR / "top_industries_employment.png"
    fig.subplots_adjust(bottom=0.12)
    fig.savefig(output, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return output


def plot_sector_scatter(df: pd.DataFrame) -> Path:
    sectors = build_sector_summary(df).copy()
    sectors["sector"] = sectors["naics_prefix"].map(sector_label)
    sectors["annual_payroll_billions"] = sectors["ap_usd"] / 1_000_000_000

    fig, ax = plt.subplots(figsize=(11, 8))
    sns.scatterplot(
        data=sectors,
        x="emp",
        y="annual_payroll_billions",
        hue="sector",
        s=180,
        alpha=0.85,
        ax=ax,
        legend=False,
    )

    # Widen the data limits so labels have room instead of running off the axes.
    emp_span = sectors["emp"].max() - sectors["emp"].min()
    pay_span = sectors["annual_payroll_billions"].max() - sectors["annual_payroll_billions"].min()
    ax.set_xlim(sectors["emp"].min() - emp_span * 0.10, sectors["emp"].max() + emp_span * 0.22)
    ax.set_ylim(
        min(0.0, sectors["annual_payroll_billions"].min() - pay_span * 0.08),
        sectors["annual_payroll_billions"].max() + pay_span * 0.10,
    )

    # Points past this line get their label on the left so it stays inside the axes.
    flip_threshold = sectors["emp"].min() + emp_span * 0.62
    annotations = []

    for _, row in sectors.iterrows():
        short_name = NAICS_SECTOR_NAMES.get(row["naics_prefix"], "Unknown")
        if len(short_name) > 28:
            short_name = short_name[:25] + "..."
        label = f"{row['naics_prefix']} — {short_name}"
        fontweight = "bold" if row["emp_nf"] in {"H", "J"} else "normal"
        flip = row["emp"] > flip_threshold
        annotations.append(
            ax.annotate(
                label,
                (row["emp"], row["annual_payroll_billions"]),
                textcoords="offset points",
                xytext=(-10, 4) if flip else (10, 4),
                ha="right" if flip else "left",
                va="center",
                fontsize=8,
                fontweight=fontweight,
                # Leader line so a label that gets nudged stays traceable to its point.
                arrowprops={
                    "arrowstyle": "-",
                    "color": "#9a9a9a",
                    "linewidth": 0.7,
                    "shrinkA": 0,
                    "shrinkB": 4,
                },
            )
        )
        if row["emp_nf"] == "J":
            ax.scatter(
                row["emp"],
                row["annual_payroll_billions"],
                s=260,
                facecolors="none",
                edgecolors="#333333",
                linewidths=1.5,
                zorder=5,
            )
        elif row["emp_nf"] == "H":
            ax.scatter(
                row["emp"],
                row["annual_payroll_billions"],
                s=260,
                facecolors="none",
                edgecolors="#555555",
                linewidths=2.0,
                zorder=5,
            )

    has_high_noise = (sectors["emp_nf"] == "J").any()
    has_medium_noise = (sectors["emp_nf"] == "H").any()
    add_noise_footnote(fig, has_high_noise, has_medium_noise)

    ax.set_title("Sector Employment vs. Annual Payroll\nHarris County, TX — 2023 CBP")
    ax.set_xlabel("Employment")
    ax.set_ylabel("Annual payroll (billions USD)")
    ax.xaxis.set_major_formatter(lambda x, _pos: f"{x:,.0f}")
    ax.yaxis.set_major_formatter(lambda x, _pos: f"${x:,.1f}B")

    declutter_labels(fig, annotations)

    output = CHART_DIR / "sector_employment_vs_payroll.png"
    fig.subplots_adjust(bottom=0.12)
    fig.savefig(output, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return output


def visualize_harris_cbp(clean_file: Path = CLEAN_INPUT) -> tuple[pd.DataFrame, list[Path]]:
    df = load_clean_data(clean_file)
    readable = build_readable_table(df)

    CHART_DIR.mkdir(parents=True, exist_ok=True)
    charts = [
        plot_sector_employment(df),
        plot_sector_payroll(df),
        plot_size_distribution(df),
        plot_top_industries(df),
        plot_sector_scatter(df),
    ]
    return readable, charts


def main() -> int:
    if not CLEAN_INPUT.exists():
        print(f"Clean file not found: {CLEAN_INPUT}. Run clean_harris_cbp.py first.", file=sys.stderr)
        return 1

    configure_plot_style()
    readable, charts = visualize_harris_cbp()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    readable.to_csv(READABLE_TABLE, index=False)

    total_row = readable.loc[readable["Section"] == "County total"].iloc[0]
    print("Human-readable table written to:")
    print(f"  {READABLE_TABLE}")
    print("\nCounty headline (formatted):")
    print(f"  Establishments: {total_row['Establishments']}")
    print(f"  Employment:     {total_row['Employment']}")
    print(f"  Annual payroll: {total_row['Annual payroll']}")

    print("\nCharts written to output/charts/:")
    for chart in charts:
        print(f"  {chart.name}")

    print("\nPreview (first 12 rows):")
    preview = readable.head(12).to_string(index=False)
    print(preview)

    return 0


if __name__ == "__main__":
    sys.exit(main())
