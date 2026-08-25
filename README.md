# Harris County Business Patterns — 2023

A cleaned, validated analysis of the U.S. Census Bureau's County Business
Patterns data for Harris County, Texas (FIPS 48201) — 1,709 industry records
covering 111,215 business establishments.

Every establishment, employment, and annual payroll figure in the output has
been verified row-by-row against the Census Bureau's own API.

---

## Why this project exists

I wanted a portfolio project built on genuinely messy real-world data rather
than a pre-cleaned teaching dataset, and I wanted to practise the part of data
work that actually matters: knowing whether a number is true.

The starting code for the cleaning pipeline was AI-generated. I'm saying that
up front because the interesting work turned out to be auditing it — the
generated code contained a defect that produced plausible, wrong output, and
the quality checks it shipped with were incapable of catching it.

That audit is the substance of this project.

---

## The defect

CBP reports establishment counts in employment size brackets. Nine of those
brackets are mutually exclusive:

```
n_lt_5, n5_9, n10_19, n20_49, n50_99, n100_249, n250_499, n500_999, n1000
```

Four more columns — `n1000_1` through `n1000_4` — break the `n1000` bracket
into finer bands. They are **children of `n1000`, not siblings of it.** The
record layout says so, but nothing in the data announces it.

The original `SIZE_CLASS_COLUMNS` constant listed all thirteen as one flat
group. Every downstream sum therefore counted the 1,000+ establishments twice.

**How it surfaced:** the percentage column in
`output/summary_size_distribution.csv` summed to **100.12%**. Nothing can be
more than 100% of itself.

**Confirmed in the data:**

```
n1000                = 135
n1000_1..4 summed    = 135     ← identical, because they ARE n1000

est                  = 111,215
sum of 9 real buckets= 111,215  ✓ exact
sum of all 13        = 111,350  ✗ 135 too many
```

**The fix** was to split the constant into two — `SIZE_CLASS_COLUMNS` (the
nine that may be summed) and `SIZE_CLASS_1000_DETAIL` (the four that are a
drill-down and must never be summed alongside them). The detail bands moved
into their own output file, `summary_size_1000_detail.csv`, where percentages
are expressed against `n1000` rather than the county total.

After the fix, the nine buckets reconcile to `est` **exactly**, with zero
drift.

## The second defect: quality checks that could not fail

The pipeline shipped a QA report with 41 checks. All 41 passed — including the
one that had already detected the bug above. It recorded

```
est=111215, size_sum=111350.0    passed: True
```

because its pass condition was `pd.notna(expected) and pd.notna(actual)`. It
compared nothing. A check that reports a discrepancy and calls it a pass is
worse than no check, because it manufactures confidence.

The QA layer was rebuilt around three ideas:

- **Real assertions.** Every check now compares values. The size-class check
  is `est_total == size_sum`.
- **Separation of tests from observations.** Null counts and flag
  distributions describe the data; they cannot pass or fail. They moved to
  `harris_cbp_2023_data_profile.csv`.
- **Honest labelling of evidence.** Checks are named `regression_*` when they
  compare against a previous run, and `independent_*` when the expected value
  came from outside the pipeline. A regression test detects *change*, not
  *correctness* — a constant derived from your own output can enshrine an
  error permanently.

Result: 10 real checks and 35 profile rows, instead of 41 rows that always
said yes.

---

## Verification

Everything above is internal consistency — the pipeline agreeing with itself.
That is not proof. A wrong filter agrees with itself too.

`verify_full.py` compares the output against the Census Bureau API, which
computes these figures independently on Census's own servers.

| check | method | result |
|---|---|---|
| **Every row, every measure** | All 1,709 industry codes pulled from the API; 1,706 join directly on the code, the other 3 are handled below | **0 mismatches** on establishments, employment, and annual payroll |
| **Size classes** | `EMPSZES` dimension queried separately | **exact match** on all 9 brackets |
| **Industry levels** | Compared against Census's own `INDLEVEL` | agreement on all 1,706 joined rows, with one documented difference |
| **Range sectors** | Value comparison on 3 join-key mismatches | resolved — see below |

On industry levels, the crosstab is a clean diagonal for 3-, 4-, 5-, and
6-digit codes. Two differences are worth stating rather than glossing: it
covers 1,706 rows, not 1,709, because the three range sectors don't join on
code; and Census classifies the all-industries `00` row as `INDLEVEL=2`,
alongside the two-digit sectors, while this pipeline labels it `total`. The
finer classification is deliberate — summing total-level rows alongside
sector rows would double count the county — but it is a difference from
Census, not a match.

### The join-key mismatch

The row-level join initially left three rows unmatched on each side:

```
unmatched (mine): ['31', '44', '48']
unmatched (API) : ['31-33', '44-45', '48-49']
```

NAICS has three sectors defined as ranges — Manufacturing (31-33), Retail
Trade (44-45), and Transportation & Warehousing (48-49). The bulk download
collapses each to its first number and pads it (`31----`); the API writes the
full range. Same sectors, two notations.

Rather than assume they paired, each was confirmed by explicit value
comparison — establishment, employment, and payroll figures were checked
across both representations, and all three sectors matched exactly. The join
key itself is unchanged; the pairing is verified separately rather than
normalised away, so the mismatch stays visible in the output instead of being
silently absorbed.

This was only visible because the join asked for **one-sided rows**, not just
value differences. A comparison that only checks matched rows will silently
ignore anything that failed to match.

### Reconciliation chain

```
est                             111,215   ← verified against Census API
├── 9 size buckets sum to       111,215   ✓
├── 20 sector rows sum to       111,215   ✓
└── n1000 = detail bands sum      135     ✓

emp                           2,182,164   ← verified against Census API
└── 20 sector rows sum to     2,182,164   ✓

annual payroll          $175,822,349,000  ← verified against Census API
└── 20 sector rows sum to  (identical)    ✓
```

---

## What the data says

**Harris County, 2023**

| measure | value |
|---|---|
| Establishments | 111,215 |
| Employment | 2,182,164 |
| Annual payroll | $175.8 billion |

**The county is overwhelmingly made of very small businesses.**
53.5% of all establishments have fewer than five employees; 83.0% have fewer
than twenty. Establishments with 1,000+ employees number 135 — about one in
every 824.

**Sector concentration.** Health Care & Social Assistance leads employment at
303,127, followed by Accommodation & Food Services (232,610) and Retail Trade
(213,745). Professional & Technical Services carries the highest total annual
payroll — $24.1B on 205,091 employees.

![Horizontal bar chart of 2023 employment across all 20 two-digit NAICS sectors in Harris County, ranging from Health Care & Social Assistance at 303,127 down to Agriculture at 163. Bars for Utilities and Transportation & Warehousing are outlined to mark medium-noise Census estimates.](output/charts/sector_employment.png)

*All 20 sectors sum to 2,182,164 — the county total verified against the
Census API. Outlined bars carry a medium-noise flag; see below.*

Payroll per employee tells a different story than payroll alone. Mining &
Oil/Gas Extraction leads at roughly $200,800 per employee on only 33,866
workers, followed by Management of Companies ($189,900) and Finance &
Insurance ($155,800). Professional & Technical Services ranks fifth at
$117,700. Accommodation & Food Services sits last at about $24,700 — the
second-largest employer in the county and the lowest paid.

**Plumbing and HVAC contractors (NAICS 238220)**

| measure | value |
|---|---|
| Establishments | 1,187 |
| Employment | 19,695 |
| Annual payroll | $1.49 billion |

Size distribution: 639 establishments have fewer than 5 employees, 227 have
5–9, 137 have 10–19, 112 have 20–49, 38 have 50–99, 21 have 100–249, 9 have
250–499, and 4 have 500–999. These sum to 1,187 exactly, matching `est`.

**Caveats on that figure, because they matter:** NAICS 238220 is *"Plumbing,
Heating, and Air-Conditioning Contractors"* — it bundles plumbing with HVAC,
so it overstates plumbing-only firms. Employment counts are not technician
counts; a nine-employee shop may run five technicians and four office staff.

---

## Working with noise-infused data

Census does not publish raw employment and payroll figures. Each value is
multiplied by a small random factor before release, so that no individual
business's confidential survey response can be reverse-engineered — a
requirement under Title 13 of the U.S. Code.

Three columns carry the noise tier for their corresponding value:

| flag | meaning |
|---|---|
| `G` | under 2% noise |
| `H` | 2% to under 5% |
| `J` | 5% or more |

These flags are independent within a single row: a record can carry `J` on
employment and `G` on payroll simultaneously.

Two consequences are reflected throughout this project:

1. **The flags are preserved, never dropped.** Discarding them would leave
   every figure with false precision and no way to know which ones deserve a
   caveat.
2. **Charts encode them.** In `top_industries_employment.png` and the sector
   charts, high-noise bars are hatched and medium-noise bars are outlined,
   with a footnote. A chart that draws a `J`-flagged value with the same
   visual confidence as a `G`-flagged one is misleading even when the number
   is correctly transcribed.

![Horizontal bar chart of the top 15 Harris County industries by 2023 employment, led by Corporate/Regional Managing Offices at 107,375. Specialty Hospitals is drawn with diagonal hatching to mark a high-noise estimate; General Medical & Surgical Hospitals and Warehouse Clubs & Supercenters are outlined to mark medium noise.](output/charts/top_industries_employment.png)

*The hatched bar is 622310 — Specialty Hospitals, where Census injected 5% or
more noise. It is the tenth-largest employer in the county and the least
certain figure on the chart, and the encoding says so at a glance.*

Establishment counts (`est`) carry no noise flag and are exact — which is why
the size-distribution chart has no noise annotation.

---

## Running it

Requires Python 3.11+, `pandas`, `matplotlib`, `seaborn`, `requests`, and
`python-dotenv`.

```bash
pip install -r requirements.txt

# 1. Download the 2023 county file and save as data/county_files.txt
#    https://www2.census.gov/programs-surveys/cbp/datasets/2023/cbp23co.zip

# 2. Clean and run quality checks
python -m pipeline.clean_harris_cbp

# 3. Build summary tables
python -m pipeline.summarize_harris_cbp

# 4. Build charts
python -m pipeline.visualize_harris_cbp

# 5. Verify against the Census API
#    Free key: api.census.gov/data/key_signup.html
export CENSUS_API_KEY=your_key_here
python -m verification.verify_full
```

Run these from the repository root with `-m`. The stages are packages, so
`python pipeline/clean_harris_cbp.py` would put `pipeline/` on the import path
instead of the root and fail to resolve `pipeline.cbp_schema`.

`verify_full.py` reads the key from the environment, so the `export` must
happen in the same shell session (IDE run configurations do not inherit it).
`verify.py`, the smaller county-totals check, loads a `.env` file instead.

## Project structure

```
pipeline/
├── cbp_schema.py              column definitions, NAICS parsing, constants
├── clean_harris_cbp.py        filter to Harris County, clean, run QA
├── summarize_harris_cbp.py    level-scoped summary tables
└── visualize_harris_cbp.py    charts with noise encoding

verification/
├── verify.py                  county totals vs the Census API (loads .env)
└── verify_full.py             row-level validation of all 1,709 records

tests/
├── conftest.py                shared fixtures
├── test_schema.py             NAICS parsing and noise-flag mapping
├── test_cleaning.py           type coercion, derived columns, the QA gate
├── test_summaries.py          level scoping and the size-class regression test
└── test_invariants.py         reconciliation against the real output

data/
├── county_files.txt           raw CBP county file (gitignored — 107 MB)
└── record_layout_2023.txt     Census data dictionary — the authority on field meaning

output/
├── harris_cbp_2023_clean.csv          1,709 cleaned rows
├── harris_cbp_2023_readable.csv       human-readable subset
├── harris_cbp_2023_data_quality.csv   10 assertions, pass/fail
├── harris_cbp_2023_data_profile.csv   35 descriptive rows, no pass/fail
├── summary_county_totals.csv
├── summary_by_sector.csv              20 two-digit sectors
├── summary_top_industries.csv         top 25 by employment/establishments/payroll
├── summary_size_distribution.csv      9 mutually exclusive brackets
├── summary_size_1000_detail.csv       the 1,000+ drill-down, kept separate
└── charts/                            5 PNGs
```

## Tests

```bash
pytest              # 61 tests, ~0.2s
pytest -m realdata  # only the checks that run against the real output
```

Most of the suite runs on a four-row synthetic frame rather than the real file,
so it is fast, deterministic, and readable — when a test fails you see the
numbers that broke it. The `realdata` tests exercise the genuine 1,709-row
output and skip cleanly on a fresh clone, where neither the 107 MB source file
nor `output/` exists.

The suite is built around one idea: **encode the bugs you already found so they
cannot come back.** Both documented defects have dedicated tests.

- `test_N_sentinel_becomes_missing_not_zero` pins the missing-vs-zero
  invariant. Turning `"N"` into `0` converts "we won't tell you" into "there
  are none", and every total still computes — which is precisely what makes it
  worth a test.
- `test_size_class_check_fails_when_the_data_does_not_reconcile` corrupts a
  bucket on purpose and asserts the QA gate returns `passed: False`. The
  original defect was a check that reported a real discrepancy and called it a
  pass. This test makes that class of bug impossible to reintroduce quietly.
- `TestSizeDistributionDoubleCount` is a regression test for the double count
  itself: nine buckets, not thirteen, and percentages that cannot exceed 100%.

Verified by mutation. Reintroducing the `"N"` → `0` bug fails exactly one test;
reintroducing the size-class double count fails five across three files. A test
you have never watched fail is not yet evidence of anything.

### Design notes

**NAICS codes are hierarchical and must not be summed across levels.** CBP
reports the same establishments at six levels of detail — `------` (county
total), `11----` (sector), `113///`, `1133//`, `11331/`, `113310`. A
`groupby().sum()` across the raw file inflates every figure. Every summary
here filters to exactly one level before aggregating, and `naics_level` is
derived on load so the constraint is explicit rather than remembered.

**`"N"` becomes missing, never zero.** CBP writes `"N"` in size-class fields
meaning *not available or not comparable*. `0` means *we counted, there are
none*. Filling one with the other converts "we won't tell you" into "there are
none" — invisibly, since every total still computes.

**FIPS codes stay strings.** `"48"`, `"201"`. Allowing pandas to infer them as
integers drops leading zeros and silently breaks any geographic join.

**Payroll is published in thousands.** `ap = 175822349` is $175.8 *billion*.
Derived `_usd` columns make the unit explicit rather than relying on the
reader to remember.

---

## Limitations

- **A single year.** This is a 2023 snapshot. Nothing here supports a trend
  claim, and no year-over-year comparison has been built.
- **Six-digit rows do not sum to the county total.** They reach 110,874
  against 111,215. This is expected — not every establishment classifies to
  full six-digit depth — but the residual has not been independently
  explained.
- **First-quarter payroll was not externally verified.** `verify_full.py`
  compares establishments, employment, and annual payroll. `qp1` and the
  per-row size-class columns were not checked against the API; size classes
  were confirmed only at the county-total level.
- **Noise limits what can be claimed.** A year-over-year change smaller than
  the noise band on the underlying cells is not a finding. Any future
  comparison needs to respect that.
- **NAICS 238220 is not "plumbers."** See the caveat above.
- **The pipeline was AI-generated and then audited.** The defects documented
  here were found in review, not avoided in authorship.

## What I would do differently

**Read the record layout before writing any code.** The size-class bug is
invisible in Python — `["n1000", "n1000_1"]` looks fine. It's only wrong if
you know what those fields mean, and that lives in the data dictionary. The
documentation outranks the code.

**Write assertions before writing checks.** The original QA layer was built to
report, not to test. Deciding what failure looks like *first* would have
caught the defect on the first run.

**Get external validation early.** Every check I ran for the first several
days was internal. The Census API call took twenty minutes to set up and was
worth more than all of them combined — it is the only evidence that came from
outside my own pipeline.

---

## Source

U.S. Census Bureau, [County Business Patterns 2023](https://www.census.gov/programs-surveys/cbp/data/datasets.html)
· [record layouts](https://www.census.gov/programs-surveys/cbp/technical-documentation/record-layouts.html)
· [API documentation](https://api.census.gov/data/2023/cbp/variables.html)

Note: the 2023 CBP API publishes industry codes under the `NAICS2017`
variable, not `NAICS2022`.
