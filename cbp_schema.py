"""CBP county file schema helpers for 2023 (and 2017 reference)."""

from __future__ import annotations

import re
from typing import Final # A type that lets you keep a value at a fixed 'final' value

# 2023 county file columns (record_layout_2023.txt)
COLUMNS_2023: Final[list[str]] = [
    "fipstate",
    "fipscty",
    "naics",
    "emp_nf",
    "emp",
    "qp1_nf",
    "qp1",
    "ap_nf",
    "ap",
    "est",
    "n<5",
    "n5_9",
    "n10_19",
    "n20_49",
    "n50_99",
    "n100_249",
    "n250_499",
    "n500_999",
    "n1000",
    "n1000_1",
    "n1000_2",
    "n1000_3",
    "n1000_4",
]

# 2017-only columns removed in 2023 (record_layout_2017.txt)
COLUMNS_2017_EXTRA: Final[list[str]] = ["empflag", "censtate", "cencty"]

COLUMN_RENAMES: Final[dict[str, str]] = {"n<5": "n_lt_5"}

# Mutually exclusive establishment size buckets — safe to sum for reconciliation.
SIZE_CLASS_COLUMNS: Final[list[str]] = [
    "n_lt_5",
    "n5_9",
    "n10_19",
    "n20_49",
    "n50_99",
    "n100_249",
    "n250_499",
    "n500_999",
    "n1000",
]

# Breakdown within n1000 — never sum alongside SIZE_CLASS_COLUMNS.
SIZE_CLASS_1000_DETAIL: Final[list[str]] = [
    "n1000_1",
    "n1000_2",
    "n1000_3",
    "n1000_4",
]

ALL_SIZE_CLASS_COLUMNS: Final[list[str]] = [
    *SIZE_CLASS_COLUMNS,
    *SIZE_CLASS_1000_DETAIL,
]

NUMERIC_COLUMNS: Final[list[str]] = ["emp", "qp1", "ap", "est", *ALL_SIZE_CLASS_COLUMNS]

NOISE_FLAG_COLUMNS: Final[list[str]] = ["emp_nf", "qp1_nf", "ap_nf"]

NOISE_FLAG_LABELS: Final[dict[str, str]] = {
    "G": "low",
    "H": "medium",
    "J": "high"
}

NAICS_LEVEL_TOTAL: Final[str] = "total"
NAICS_LEVELS: Final[list[str]] = [
    NAICS_LEVEL_TOTAL,
    "2-digit",
    "3-digit",
    "4-digit",
    "5-digit",
    "6-digit",
]

_NAICS_PATTERNS: Final[list[tuple[str, re.Pattern[str]]]] = [   # This is just a list that holds the patterns of the NAICS codes
    (NAICS_LEVEL_TOTAL, re.compile(r"^------$")),   # Checks for the same pattern, just ---
                                                    # This is the combination of the entire industry, not including sub-sectors
    ("2-digit", re.compile(r"^\d{2}----$")), # Checks for this pattern, 2 digits and then 4 -'s
    ("3-digit", re.compile(r"^\d{3}///$")),
    ("4-digit", re.compile(r"^\d{4}//$")),
    ("5-digit", re.compile(r"^\d{5}/$")),
    ("6-digit", re.compile(r"^\d{6}$")),
]

HARRIS_FIPSTATE: Final[str] = "48"
HARRIS_FIPSCTY: Final[str] = "201"
HARRIS_FIPS_FULL: Final[str] = "48201"
HARRIS_COUNTY_NAME: Final[str] = "Harris County, TX"
DATA_YEAR: Final[int] = 2023

# --- Independent validation (verified outside the pipeline via awk on county_files.txt) ---
INDEPENDENT_HARRIS_ROW_COUNT: Final[int] = 1709
INDEPENDENT_HARRIS_TOTAL_EST: Final[int] = 111_215
INDEPENDENT_HARRIS_TOTAL_EMP: Final[int] = 2_182_164

# --- Regression baselines (detect future change; not proof of correctness) ---
BASELINE_HARRIS_ROW_COUNT: Final[int] = INDEPENDENT_HARRIS_ROW_COUNT
BASELINE_TOTAL_ROWS: Final[int] = 1
BASELINE_TWO_DIGIT_ROWS: Final[int] = 20


def parse_naics_level(naics: str) -> str:
    """Classify a CBP NAICS code into its hierarchy level."""
    for level, pattern in _NAICS_PATTERNS:
        if pattern.match(naics):
            return level
    return "unknown"


def naics_digits(naics: str) -> str:
    """Return the meaningful digit prefix from a hierarchical NAICS code."""
    if naics == "------":
        return "all"
    return naics.split("-")[0].split("/")[0]


def noise_flag_label(flag: str | float | None) -> str | None:
    """Map a noise flag code to a readable label."""
    if flag is None or (isinstance(flag, float) and str(flag) == "nan"):
        return None
    return NOISE_FLAG_LABELS.get(str(flag).strip())
