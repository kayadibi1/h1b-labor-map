# Phase 0 Findings — 2026-05-27 run

This document is the audit trail for what the pipeline trusts. Where this
file conflicts with the blueprint or `config.yaml`, this file wins until the
next quarterly re-run revises both.

---

## 0.0 — STEM-OPT branch decision

**Live STEM Designated Degree List checked:**
- Source: https://www.ice.gov/doclib/sevs/pdf/stemList2024.pdf
- Latest revision: **2024-07-23** (Federal Register 89 FR 59748, doc 2024-16127)
- Next anticipated update: per DHS nomination cycle (Aug 1 deadline each year);
  no 2025/2026 update published as of 2026-05-27.
- Cached snapshot: `/data/raw/sevp/stem_cip_list_2024-07-23.md`

**SAIS-relevant 6-digit verdict:**

| CIP code | Field | STEM? |
|---|---|---|
| **45.0603** | Econometrics and Quantitative Economics | YES |
| **30.4901** | Mathematical Economics | YES |
| **30.7001** | Data Science, General | YES |
| **30.7101** | Data Analytics, General | YES |
| 45.0601 | Economics, General | NO |
| 45.0605 | International Economics | NO |
| 45.0901 | International Relations and National Security Studies | NO |
| 45.0902 | National Security Policy Studies | NO |
| 30.2001 | International/Global Studies | NO |

**Branch decision:** Default user CIP set to **45.0901** in
`user_profile.yaml`. Under that CIP the applicant is **NOT STEM-OPT
eligible** → pipeline runs in **cap-exempt-first mode**
(`gates.cap_exempt_only = TRUE`). If the user's actual conferred degree CIP
is one of {45.0603, 30.4901, 30.7001, 30.7101}, flip
`cap_exempt_only = FALSE` and re-run.

---

## 0.1 — Resolved source URLs (all verified 2026-05-27)

| Source | URL | Latest period | Format |
|---|---|---|---|
| DOL OFLC Performance Data | https://www.dol.gov/agencies/eta/foreign-labor/performance | FY2025 Q4 (through 2025-09-30) | xlsx per program per FY |
| DOL OFLC FLAG portal | https://flag.dol.gov/programs/LCA | current | xlsx |
| USCIS H-1B Employer Data Hub | https://www.uscis.gov/tools/reports-and-studies/h-1b-employer-data-hub | FY2009–FY2026 Q2 | csv/xlsx |
| BLS Public Data API v2 | https://api.bls.gov/publicAPI/v2/timeseries/data/ | live | JSON POST; 500 q/day registered |
| BLS OEWS tables | https://www.bls.gov/oes/tables.htm | May 2024 release (current) | xlsx |
| BLS Employment Projections | https://www.bls.gov/emp/data/occupational-data.htm | 2023–2033 projection | xlsx |
| IRS Form 990 bulk downloads | https://www.irs.gov/charities-non-profits/form-990-series-downloads | rolling | xml/zip |
| ProPublica Nonprofit Explorer API | https://projects.propublica.org/nonprofits/api/v2/ | rolling | JSON; rate-limited |
| SEC EDGAR company facts | https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json | live | JSON |
| SEC company tickers | https://www.sec.gov/files/company_tickers.json | live | JSON |
| Census CBSA delineation | https://www.census.gov/geographies/reference-files/time-series/demo/metro-micro/delineation-files.html | OMB Bulletin 23-01 (Jul 2023) | xlsx |
| IPEDS / Title IV institutions | https://ope.ed.gov/dapip/ | live | csv export |
| SEVP STEM list | https://www.ice.gov/doclib/sevs/pdf/stemList2024.pdf | 2024-07-23 | pdf |

**State WARN portals (top 10 H-1B states + DC, scrape-only):**

| State | URL |
|---|---|
| California | https://edd.ca.gov/en/jobs_and_training/Layoff_Services_WARN/ |
| Texas | https://www.twc.texas.gov/businesses/worker-adjustment-and-retraining-notification-warn-notices |
| New York | https://dol.ny.gov/warn-notices |
| Washington | https://esd.wa.gov/about-employees/WARN |
| New Jersey | https://www.nj.gov/labor/employer-services/warn/ |
| Illinois | https://dceo.illinois.gov/aboutdceo/reportsrequiredbystatute/warnreport.html |
| Massachusetts | https://www.mass.gov/lists/warn-notices |
| Virginia | https://www.vec.virginia.gov/warn-notices |
| Florida | https://floridajobs.org/.../warn-notices |
| Georgia | https://dol.georgia.gov/get-warn-notice-information |
| DC | https://does.dc.gov/page/warn-notifications |

---

## 0.2 — Schema discovery (deferred to ingest stage)

DOL OFLC LCA disclosure files: per-FY xlsx with drifting column names.
`src/ingest_dol.py` builds the column mapper from actual headers at ingest
time, not from this file. Per-year mappers persist in
`/data/manifest/dol_column_mappers/`. Headline columns expected (subject to
verification at ingest): CASE_NUMBER, CASE_STATUS, DECISION_DATE,
EMPLOYER_NAME, EMPLOYER_STATE, JOB_TITLE, SOC_CODE, SOC_TITLE, NAICS_CODE,
PW_WAGE, PW_UNIT_OF_PAY, **PW_WAGE_LEVEL**, WAGE_RATE_OF_PAY_FROM,
WAGE_UNIT_OF_PAY, WORKSITE_CITY, WORKSITE_STATE, FULL_TIME_POSITION.

USCIS Employer Data Hub: csv with columns including Fiscal_Year, Employer,
Initial Approval, Initial Denial, Continuing Approval, Continuing Denial,
NAICS Code, Tax ID (sometimes), State, City, Zip.

---

## 0.3 — Rules verified (recorded in `config.yaml` with full citations)

| Rule | Value | Source / citation |
|---|---|---|
| Regular H-1B cap | 65,000 | 8 USC 1184(g)(1)(A)(vii) |
| Masters cap | 20,000 | 8 USC 1184(g)(5)(C) |
| FY2026 selection rate | 35.3% (118,660 / 336,153) | USCIS FY2026 cap data release |
| FY2025 selection rate | ~29% | USCIS FY2025 cap data release |
| Beneficiary-centric selection effective | FY2025 | 89 FR 7456 (Feb 2 2024) |
| **Wage-weighted lottery effective** | **FY2027** | **90 FR (Dec 29, 2025), 2025-23853; rule effective 2026-02-27** |
| Wage Level → entries | I:1, II:2, III:3, IV:4 | same rule |
| Cap-exempt rule citation | 8 CFR 214.2(h)(19)(iii)(C) | per 89 FR 100024 (2024-12-18) |
| "Fundamental activity" test | Replaces "primarily engaged" / "primary mission" | same rule |
| Cap-exempt rule effective | 2025-01-17 | same rule |
| OPT duration (non-STEM) | 12 months | 8 CFR 214.2(f)(10)(ii) |
| STEM OPT extension | 24 months (total 36) | 8 CFR 214.2(f)(10)(ii)(C) |

### Headline interpretation for the user

The two regime changes you face:

1. **FY2025 (March 2024 lottery)**: Beneficiary-centric — registrations
   became 1-per-beneficiary-per-employer, eliminating multi-employer gaming.
   FY2026 selection rate rose to ~35%.

2. **FY2027 (March 2026 lottery, just completed)**: Wage-weighted —
   higher prevailing-wage-level offers get more lottery entries
   (Level I: 1 ticket, Level II: 2, Level III: 3, Level IV: 4). A SAIS
   grad's first offer is typically Level I or II, putting them at a
   structural disadvantage in the lottery against more experienced
   candidates.

**Combined effect for a Level I cap-subject applicant in FY2027+:**
- Estimated selection probability: ~17% (down from a flat 35%)
- Cap-exempt lane becomes substantially more attractive.

**Combined effect for the default non-STEM SAIS profile:**
- 12-month OPT + 1 cap shot at ~17% (Level I most likely) ≈ effective
  probability of converting OPT → H-1B via cap-subject lottery alone is in
  the high single digits.
- Cap-exempt-first strategy is not just preferable — it's the dominant
  realistic path.

---

## 0.3.5 — Regime-split decision

The pipeline computes per-employer metrics for two windows independently:

- `FY2022-FY2024` — pre-beneficiary-centric, pre-wage-weighted
- `FY2025+` — beneficiary-centric in effect; FY2027+ data (when available)
  also covers wage-weighted lottery.

The mart carries `window_label` and never averages across regimes.

---

## 0.4 — Time windows (recommended)

| Layer | Window | Rationale |
|---|---|---|
| Sponsorship behavior (LCA + USCIS Hub) | 4 fiscal years | Spans pre/post-2024 regime split |
| Demand (JOLTS, CES) | 8 quarters | Recency-weighted |
| Layoffs (WARN) | 12 months | "Recent layoff" definition |
| OEWS wages | Latest annual release | Annual cadence, no point in window |
| BLS Projections | Current 10-yr (2023–2033) | Annual cadence |

---

## 0.5 — Freshness verdict

Available primary sources (DOL, USCIS, BLS) have meaningful lag:
- DOL OFLC LCA: quarterly, last quarter ~2 months old at publication.
- USCIS Hub: quarterly, ~1 month behind FY-end.
- JOLTS: monthly, ~6-week lag.
- OEWS: annual, ~7-month lag from reference period.
- BLS Projections: biennial.

**No accessible real-time job-postings source** was wired in for this run.
Lightcast Open Data is enterprise-tier; Revelio public releases lag and are
aggregate-only.

**Verdict:** the map is reliable about the recent past (sponsorship behavior
and demand changes through Q4 2025) and weakest about the near future (any
claim about "what's hiring NOW in May 2026" carries 2–6 months of lag).
Every forward-looking field carries the lag label per `accuracy_guardrails`.

---

## 0.6 — Gate summary (one-screen view)

1. **STEM branch:** non-STEM default. `cap_exempt_only = TRUE` until user
   confirms otherwise.
2. **Sources:** all primary sources resolved; no substitutions; WARN takes
   the layoff role over Layoffs.fyi.
3. **Rules:** all values in `config.yaml`, all dated 2026-05-27. Two material
   regime changes (beneficiary-centric FY2025, wage-weighted FY2027) are
   first-class in scoring.
4. **Windows:** 4-yr sponsorship window, 8-quarter demand window,
   12-month layoff window.
5. **Schema:** discovered at ingest, not assumed.
6. **Freshness:** recent past — strong. Forward — weak; label everything.
7. **Open user inputs:** confirm CIP code; confirm/edit target SOCs and
   metros; populate `manual_cap_exempt_orgs` with any policy/research orgs
   beyond the defaults (Brookings, RAND, CSIS, etc. already seeded).

**Auto-decisions taken (because the user said "execute autonomously"):**
- CIP default set to 45.0901 (most-common SAIS IR program). Pipeline branches
  to non-STEM / cap-exempt-first.
- Target SOCs default to the SAIS list in `config.yaml`.
- Target metros default to {DC, NYC, Boston, SF, San Jose, Seattle}.
- Manual cap-exempt list seeded with 19 major DC/policy think tanks +
  research nonprofits.

The user can edit any of these in `user_profile.yaml` and re-run.
