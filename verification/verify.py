#!/usr/bin/env python3
"""Compare local Harris County totals against the Census CBP API."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

from pipeline.cbp_schema import INDEPENDENT_HARRIS_TOTAL_EMP, INDEPENDENT_HARRIS_TOTAL_EST

PROJECT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_DIR / ".env"
API_URL = "https://api.census.gov/data/2023/cbp"
INDEPENDENT_HARRIS_TOTAL_PAYANN = 175_822_349


def load_api_key() -> str:
    load_dotenv(ENV_FILE)
    key = os.getenv("CENSUS_API_KEY")
    if not key:
        raise RuntimeError(
            f"CENSUS_API_KEY not found. Add it to {ENV_FILE} as:\n"
            "CENSUS_API_KEY=your_key_here"
        )
    return key


def fetch_harris_totals(api_key: str) -> dict[str, str]:
    params = {
        "get": "NAME,ESTAB,EMP,PAYANN",
        "for": "county:201",
        "in": "state:48",
        "key": api_key,
    }
    response = requests.get(API_URL, params=params, timeout=30)
    response.raise_for_status()

    try:
        rows = response.json()
    except requests.exceptions.JSONDecodeError as exc:
        raise RuntimeError(f"Census API returned non-JSON response:\n{response.text}") from exc

    if not isinstance(rows, list) or len(rows) < 2:
        raise RuntimeError(f"Unexpected Census API response:\n{rows}")

    header, values = rows[0], rows[1]
    return dict(zip(header, values))


def main() -> int:
    api_key = load_api_key()
    api = fetch_harris_totals(api_key)

    checks = [
        ("establishments", INDEPENDENT_HARRIS_TOTAL_EST, int(api["ESTAB"])),
        ("employment", INDEPENDENT_HARRIS_TOTAL_EMP, int(api["EMP"])),
        ("annual_payroll", INDEPENDENT_HARRIS_TOTAL_PAYANN, int(api["PAYANN"])),
    ]

    print(f"Census returned: {api.get('NAME', 'Harris County, Texas')}")
    failed = False
    for name, mine, theirs in checks:
        status = "PASS" if mine == theirs else "FAIL"
        if status == "FAIL":
            failed = True
        print(f"[{status}] {name}: mine={mine:,} census={theirs:,}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
