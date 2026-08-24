#!/usr/bin/env python3
"""Verify every row of the cleaned 2023 file against the Census API."""

import os
import requests
import pandas as pd
from cbp_schema import naics_digits, SIZE_CLASS_COLUMNS

KEY = os.environ["CENSUS_API_KEY"]
BASE = "https://api.census.gov/data/2023/cbp"


def fetch(params):
    """Call the API and return a DataFrame."""
    params = {**params, "for": "county:201", "in": "state:48", "key": KEY}
    r = requests.get(BASE, params=params, timeout=60)
    r.raise_for_status()
    rows = r.json()
    df = pd.DataFrame(rows[1:], columns=rows[0])
    return df.loc[:, ~df.columns.duplicated()] 


# ---------------------------------------------------------------- setup
mine = pd.read_csv("output/harris_cbp_2023_clean.csv", dtype={"naics": str})
mine["key"] = mine["naics"].map(naics_digits).replace({"all": "00"})


# ---------------------------------------------------------------- CHECK A
print("=" * 60)
print("CHECK A — every row, every measure")
print("=" * 60)

api = fetch({"get": "NAICS2017,NAICS2017_LABEL,ESTAB,EMP,PAYANN,INDLEVEL",
             "NAICS2017": "*"})
api["key"] = api["NAICS2017"].astype(str)
print(f"API returned {len(api)} rows | my file has {len(mine)} rows\n")

m = mine.merge(api, on="key", how="outer", indicator=True)
print("only in my file :", (m["_merge"] == "left_only").sum())
print("only in API     :", (m["_merge"] == "right_only").sum())

both = m[m["_merge"] == "both"].copy()
for mine_col, api_col in [("est", "ESTAB"), ("emp", "EMP"), ("ap", "PAYANN")]:
    theirs = pd.to_numeric(both[api_col], errors="coerce")
    ours = pd.to_numeric(both[mine_col], errors="coerce")
    bad = both[(ours != theirs) & ours.notna() & theirs.notna()]
    status = "PASS" if len(bad) == 0 else "FAIL"
    print(f"[{status}] {mine_col:4s}: {len(bad)} mismatches of {len(both)}")
    if len(bad):
        print(bad[["naics", mine_col, api_col]].head(10).to_string(index=False))

print("columns:", list(api.columns))
# ---------------------------------------------------------------- CHECK B
print("\n" + "=" * 60)
print("CHECK B — size classes (inspect labels first)")
print("=" * 60)

sz = fetch({"get": "EMPSZES,EMPSZES_LABEL,ESTAB", "NAICS2017": "00",
            "EMPSZES": "*"})
print(sz[["EMPSZES", "EMPSZES_LABEL", "ESTAB"]].to_string(index=False))

total_row = mine[mine["naics_level"] == "total"].iloc[0]
print("\nMy columns for comparison:")
for c in SIZE_CLASS_COLUMNS:
    print(f"  {c:12s} {total_row[c]}")


# ---------------------------------------------------------------- CHECK C
print("\n" + "=" * 60)
print("CHECK C — my naics_level vs Census INDLEVEL")
print("=" * 60)
print(pd.crosstab(both["naics_level"], both["INDLEVEL"]))


# ---------------------------------------------------------------- CHECK D
print("=" * 60)
print("CHECK D — range sector pairing")
print("=" * 60)

RANGE_PAIRS = [("31----", "31-33"), ("44----", "44-45"), ("48----", "48-49")]

all_ok = True
for my_code, api_code in RANGE_PAIRS:
    mrow = mine[mine["naics"] == my_code]
    arow = api[api["NAICS2017"] == api_code]

    if mrow.empty or arow.empty:
        print(f"MISSING  {my_code} / {api_code}")
        all_ok = False
        continue

    mrow, arow = mrow.iloc[0], arow.iloc[0]
    label = arow["NAICS2017_LABEL"]

    pairs = [
        ("establishments", mrow["est"], arow["ESTAB"]),
        ("employment",     mrow["emp"], arow["EMP"]),
        ("annual payroll", mrow["ap"],  arow["PAYANN"]),
    ]

    print(f"\n{my_code}  <-->  {api_code}   {label}")
    for name, mine_val, api_val in pairs:
        mine_val, api_val = int(float(mine_val)), int(api_val)
        ok = mine_val == api_val
        all_ok &= ok
        flag = "OK " if ok else "DIFF"
        print(f"  [{flag}] {name:15s} mine={mine_val:>12,}  api={api_val:>12,}")

print(f"\nAll three range sectors pair correctly: {all_ok}")
