# PROJECT: US Labor Market × H-1B Sponsorship Map

## CONTEXT
I'm a recent SAIS grad, international student, F-1 on OPT, and I will need H-1B
sponsorship to stay past OPT. Build me a data pipeline that maps the US labor
market AND employer sponsorship behavior so I can target my job search at
roles / companies / metros where (a) demand is real and (b) sponsorship is
realistic.

I'll supply two things you can't infer: my **degree CIP code** (to check STEM-OPT
eligibility against the live list) and a **manual list of cap-exempt / policy /
research orgs** I care about. Ask for these; propose sensible defaults for a
SAIS/policy/analyst profile in the meantime and let me edit.

The deliverable is a reproducible pipeline + a final ranked dataset and a few
summary views. Optimize for accuracy and re-runnability — new DOL data drops
quarterly, so I'll re-run this.

---

## PHASE 0: VERIFY & ADAPT (run this BEFORE any ingest; re-run each quarter)

Do NOT trust hardcoded URLs, schemas, cadences, or rules in this prompt. They
may be stale. Your first job is to verify each against live sources and adapt
the pipeline to what you actually find. Web-search and fetch as needed. Write
everything you discover to `/data/manifest/phase0_findings.md` with source URLs
and access dates, so the run is auditable. **Where this prompt and live findings
conflict, the live findings win — and tell me what changed.**

### 0.0 — STEM-OPT eligibility (literal first action)
Before resolving any source URL, do this:
- Ask me for my degree CIP code. While waiting, propose likely CIP codes for
  common SAIS programs and ask me to confirm.
- Pull the CURRENT STEM Designated Degree Program List from the official
  ICE/SEVP page. Record URL + access date in `phase0_findings.md`.
- Branch the pipeline:
  - **If STEM-CIP**: I have a ~36-month OPT runway and multiple cap shots.
    Pipeline runs in full mode.
  - **If non-STEM-CIP**: I have a ~12-month runway and likely *one* cap shot.
    Pipeline defaults to **cap-exempt-first mode** for headline rankings, with
    cap-subject as a secondary view. Surface this branch decision prominently
    in the README and at the 0.6 gate.
- Note: many SAIS programs (MA International Affairs, traditional MA
  International Economics, MA Strategic Studies) are **not** STEM-CIP. Some
  quant-track / energy / data-focused tracks are. Do not assume — verify from
  my actual CIP code against the live list.

### 0.1 — Resolve live source URLs
For each source (DOL OFLC disclosure data, USCIS H-1B Employer Data Hub, BLS
API + OEWS + Employment Projections downloads, IRS 990 bulk data /
ProPublica Nonprofit Explorer, state WARN Act portals, SEC EDGAR, Census
gazetteer + OMB CBSA delineation, and optionally Lightcast/Revelio):
- Search for the CURRENT official download/landing page. Prefer .gov/official.
- Confirm the latest available data period and the file format actually served.
- Record: resolved URL, latest period available, format, access date.
- If a source moved, was renamed, or was discontinued, note it and find the
  closest authoritative replacement before proceeding. Do not silently
  substitute a lower-quality aggregator for a primary source without flagging
  it to me.

### 0.2 — Discover schema instead of assuming it
For DOL LCA/PERM and the USCIS hub specifically:
- Download the most recent file FIRST and inspect actual column names, types,
  and the set of distinct case-status / wage-unit / wage-level values present.
- Generate the per-year column mapper FROM the real headers, not from this
  prompt's guesses. Build a mapper per fiscal year present, since schema
  drifts.
- Confirm the LCA file includes **prevailing wage level (I/II/III/IV)** — this
  is a load-bearing field for downstream scoring. If absent in some years,
  flag those years as missing this signal.
- Confirm the USCIS Hub file includes the four-way split: Initial Approvals,
  Initial Denials, Continuing Approvals, Continuing Denials. Headline metrics
  use Initial only.
- Fail loudly (raise, don't drop) if a column you need has no resolvable
  match, and surface the unmatched columns to me for a decision.

### 0.3 — Verify the rules that drive logic, not just the data
These change and are load-bearing for accuracy. Search authoritative sources
(USCIS, DOL, ICE/SEVP, Federal Register) for the CURRENT state and write
findings + dates:
- H-1B cap, registration process, and current/most-recent lottery selection
  odds (selections / eligible beneficiaries). Note the FY they apply to.
- Current cap-exempt criteria. Decompose into the **four statutory
  subcategories** (institutions of higher education; nonprofits affiliated
  with such institutions; nonprofit research organizations; governmental
  research organizations) and record the *test* for each — particularly
  8 CFR 214.2(h)(8)(ii)(F)(2) for "nonprofit research organization." A
  generic 501(c)(3) is NOT automatically cap-exempt; verify the definition
  rather than relying on my summary.
- OPT and STEM-OPT duration + the current STEM CIP code list (already pulled
  in 0.0; record again here with rule citation).
- Initial vs. Continuing approval definitions from the USCIS Employer Data
  Hub data dictionary, so the pipeline uses them correctly.
- Any recent rule changes (e.g., beneficiary-centric selection effective
  FY2025 registration, wage-level weighting proposals, RFE/denial trends)
  that should change how we rank or deflate.
Put every rule the pipeline depends on into `config.yaml` as a dated, sourced
value with a comment — never hardcode a rule inline in logic.

### 0.3.5 — Account for the FY2025 beneficiary-centric regime change
The March 2024 final rule moved lottery selection from registrations to
unique beneficiaries. This materially changes the meaning of historical
filing data:
- Pre-FY2025: multi-employer registrations gamed the lottery; employer-level
  filing volume systematically *overstated* unique-beneficiary demand.
- FY2025+: registrations ≈ unique beneficiaries; volume reflects real intent.
- The pipeline MUST compute employer-level metrics for BOTH windows
  separately and surface the delta. An employer whose filings collapsed in
  FY2025+ may have been gaming, not retreating from sponsorship — surface
  that distinction explicitly rather than averaging it away.

### 0.4 — Determine optimal time windows empirically, don't inherit mine
I originally said "past 2 years." Don't take that as fixed. Pull what's
readily available and recommend windows per layer, then confirm with me:
- Demand signal (JOLTS/CES): short window, recency-weighted.
- Sponsorship behavior: longer (likely 3–4 yrs) to separate consistent
  sponsors from one-off filers. The window MUST span the pre/post-2024
  regime change so both regimes can be compared.
- Report what's actually available and propose the window.

### 0.5 — Probe the freshness gap and try to close it
Government sources lag (JOLTS ~weeks-to-months, OEWS/Projections annual). The
forward-looking "what roles are being created NOW" layer is the weakest part
of this build. Before accepting that limitation:
- Check whether a current, accessible real-time job-postings source exists
  (Lightcast open data, Revelio public releases, or similar). If yes, wire
  it in.
- If none is accessible, state plainly in the README that the map is most
  reliable about the recent past and weakest about the near future, and
  label every forward-looking claim with its data lag. Do not paper over
  the gap.

### 0.6 — Gate
Produce `phase0_findings.md` and a one-screen summary of: STEM-OPT branch
decision (0.0), resolved sources, schema surprises (including wage-level
availability), rule values found (with dates), regime-change handling
decision, recommended time windows, and the freshness verdict. STOP and show
me this before building ingest. If anything material conflicts with this
prompt's assumptions, the live findings win — and tell me what changed.

At this gate, also ask me for: target SOC codes (or accept the SAIS defaults
proposed below), target metros, confirmation of my degree CIP code (closes
0.0), and my manual cap-exempt org list.

---

## ARCHITECTURE
- Python 3.11.x (pinned), DuckDB as the analytical store (fast joins on
  multi-GB files, no server). polars for wrangling (pandas where needed).
  Parquet for intermediate storage, partitioned by FY + state where files are
  multi-GB.
- Dependency management: `uv` with `pyproject.toml` + locked `uv.lock`. Data
  validation: `pandera` schemas at every staging→marts gate.
- Directory layout:
  ```
  /data/raw        # untouched downloads, dated subfolders, sha256-tracked
  /data/staging    # cleaned, typed, standardized to SOC/NAICS/CBSA
  /data/marts     # final joined tables + summary views
  /data/manifest   # phase0_findings.md, run manifests, review CSVs,
                   # sources.json (URL + ETag + sha256 for incremental runs),
                   # employer_matches.csv, corporate_groups.yaml,
                   # cap_exempt_review.csv, geo_review.csv
  /src             # ingest_*.py, clean_*.py, entity_resolve.py, geo_normalize.py,
                   # join.py, scoring.py, views.py
  /tests           # fixture-based unit + smoke tests
  /notebooks       # exploration only, nothing canonical lives here
  ```
- `config.yaml`: years to pull, target SOC codes, target metros, scoring
  thresholds, weight defaults, and all dated/sourced rule values from
  Phase 0.3 (cap size, lottery selection rate, cap-exempt subcategory tests,
  STEM CIP list version).
- `user_profile.yaml`: CIP code, SOC weights, metro preferences,
  cap-exempt-only toggle, min wage floor, exclude-staffing toggle, manual
  cap-exempt org list, custom employer allow/deny lists.
- A `Makefile` or single `run.py` that executes
  verify → ingest → clean → entity-resolve → join → score → views.
  Support `--incremental`, `--force-refresh`, and `--dry-run` flags.

---

## DATA SOURCES (ingest each as its own module; cache raw)

1. **DOL OFLC Disclosure Data** — LCA (H-1B) + PERM. Window per Phase 0.4.
   - Source: DOL OFLC performance data page (xlsx per program per fiscal
     year).
   - Keep: employer name, worksite city/state, SOC code, job title,
     **prevailing wage level (I/II/III/IV)**, prevailing wage rate, wage rate
     + wage unit filed, full/part time, case status, decision date, NAICS if
     present.
   - **PERM is ingested for its own downstream use** (green-card sponsorship
     signal), not just as a side note — see mart schema and view 6 below.
   - GOTCHA: column names and schema change YEAR TO YEAR. Use the per-year
     mappers built in Phase 0.2; don't assume stability. Normalize wages to
     annual (handle hourly/weekly/monthly units). Filter to CERTIFIED status.

2. **USCIS H-1B Employer Data Hub** — approvals + denials by employer × FY.
   - Pull all four counts: `Initial Approvals`, `Initial Denials`,
     `Continuing Approvals`, `Continuing Denials`.
   - **Initial Approvals is the headline "new sponsorship" signal.**
     Continuing counts are renewals and largely irrelevant for an OPT
     job-seeker (kept as context only).
   - Compute `initial_approval_rate = Initial Approvals /
     (Initial Approvals + Initial Denials)`.
   - GOTCHA: employer names won't match DOL exactly. See Entity Resolution
     section below — this is a tiered pipeline, not just rapidfuzz.

3. **BLS** — pull via the public BLS API (register for a free key; store in
   `.env`, never commit):
   - JOLTS: openings/hires/quits by industry (NAICS). Granularity is
     supersector; not occupation × metro. Use as industry-level demand
     context only.
   - CES: employment level + change by industry.
   - Employment Projections: 10yr growth by SOC (download, not API).
   - OEWS: wages + employment by SOC × metro (download). Acknowledge
     suppression of small cells — flag missing OEWS data in the mart rather
     than imputing.

4. **WARN Act notices** (replaces Layoffs.fyi as the primary layoff signal) —
   federally mandated layoff notices, published per-state by state DOLs. Cover
   at minimum the top 10 H-1B-volume states (CA, TX, NY, WA, NJ, IL, MA, VA,
   FL, GA) plus DC. Cache scraped HTML; many state portals are scrape-only.
   Tag employers with recent layoff events + total positions affected.
   Optionally augment with Layoffs.fyi for tech-startup coverage that misses
   WARN thresholds.

5. **IRS 990 bulk data / ProPublica Nonprofit Explorer** — for cap-exempt
   subcategory determination. Prefer the IRS 990 Form bulk data dumps over
   the ProPublica API (API is rate-limited; you'll be hitting many
   employers). Use to verify 501(c)(3) status; subcategory tests beyond that
   require additional evidence (e.g., "affiliated with institution of higher
   education" requires looking at the org's relationship statement). See
   Cap-Exempt section.

6. **SEC EDGAR company-facts API** — for corporate entity resolution (public
   companies). Free, no key. Gets parent CIK + subsidiary list for
   parent↔subsidiary consolidation.

7. **Census gazetteer + OMB CBSA delineation file** — for canonical
   city/state → MSA (CBSA code) normalization. LCA worksite strings are
   messy ("Wash. DC", "Washington, District of Columbia"); normalize in
   `geo_normalize.py`. Critical for DC, NY, Bay Area, Boston metros where
   commute sheds cross state lines.

8. **Federal IPEDS / Title IV list** — for `HIGHER_ED` cap-exempt
   determination (HIGH-confidence flag).

9. **(OPTIONAL, flag if unavailable)** Lightcast open job-postings dataset
   for real-time role-creation signal. Skip gracefully if no access (see
   Phase 0.5).

---

## ENTITY RESOLUTION (between ingest and join)

Employer name matching across DOL ↔ USCIS ↔ WARN ↔ IRS is the most
error-prone step. Implement as a tiered pipeline, persist all decisions, and
re-use them across quarterly runs.

### Normalization (always)
- Uppercase, strip punctuation, collapse whitespace.
- Strip legal-form suffixes: INC, LLC, CORP, CORPORATION, LTD, LP, LLP, CO,
  COMPANY, PLLC, PC, GROUP, HOLDINGS, USA, NA, NORTH AMERICA.
- Strip DBA prefixes ("DOING BUSINESS AS", "DBA").

### Tiered matcher (in order)
1. **Exact** on normalized name → auto-accept.
2. **Token-sort ratio (rapidfuzz) ≥ 95** → auto-accept.
3. **Token-sort ratio 85–94** → write to
   `manifest/employer_matches_review.csv`; accept manually-confirmed matches
   on next run.
4. **< 85** → reject (treat as distinct employers).
5. **Curated corporate-group overrides** (`manifest/corporate_groups.yaml`)
   applied LAST, overriding tiers 1–4. This is where Meta/Facebook, X/Twitter,
   Alphabet/Google subsidiaries, big-bank holdings, etc. get consolidated.

### Outputs at two levels
- **Legal-entity ranking**: each LLC/Inc. ranked separately (preserves
  precision).
- **Corporate-group ranking**: subsidiaries rolled up via overrides + EDGAR
  parent-CIK lookup (preserves recall — "who really sponsors here").
Both levels appear in mart views; the user can pick which they want per view.

### Quarterly re-run
- Past decisions in `employer_matches.csv` are loaded first; only NEW
  unmatched names hit the review queue. The reviewer never re-decides
  resolved cases.

---

## GEOGRAPHIC NORMALIZATION

All LCA worksites get normalized to **CBSA (Core-Based Statistical Area)
code** via the Census gazetteer + OMB delineation file. The DC metro spans
DC + parts of MD, VA, WV — without CBSA normalization, "DC metro" rankings
are wrong. Unmatched localities log to `manifest/geo_review.csv` for
decision and re-use.

---

## THE KEY JOIN (this is the whole point)
Standardize EVERYTHING to SOC (occupation), NAICS (industry), and CBSA
(metro) before joining. Job titles are too noisy to join on.
- Build a title→SOC crosswalk. Use the O*NET/BLS SOC structure; for
  unmatched DOL titles, fuzzy-map to SOC, log misses for review.
- Final mart table, one row per (employer_resolved × SOC × CBSA × window):

  | Field | Meaning |
  |-------|---------|
  | `employer_legal` | resolved legal entity name |
  | `employer_group` | resolved corporate group (parent rollup) |
  | `cbsa_code`, `cbsa_name` | normalized metro |
  | `soc_code`, `soc_title` | occupation key + label |
  | `naics_code` | industry key |
  | `window_label` | e.g., "FY2025+" or "FY2022-2024" — regime-split aware |
  | `lca_filings_window` | certified LCA count (INTENT signal, not hires) |
  | `pct_level_1` | share of LCA filings at PW Level I (body-shop tell) |
  | `pct_level_4` | share of LCA filings at PW Level IV (senior-hire tell) |
  | `median_wage_filed` | median wage on certified filings |
  | `oews_median_wage` | OEWS market wage for SOC×CBSA (NULL if suppressed) |
  | `oews_p10`, `oews_p25` | OEWS lower percentiles for within-level comparison |
  | `wage_gap_within_level` | filed wage vs. OEWS percentile matching the level |
  | `uscis_initial_approvals_window` | NEW sponsorships actually realized |
  | `uscis_initial_denials_window` | denied initial petitions |
  | `initial_approval_rate` | initial approvals / (initial approvals + denials) |
  | `uscis_continuing_approvals_window` | renewals (context only — not for ranking) |
  | `perm_certifications_window` | green-card sponsorship count |
  | `perm_to_lca_ratio` | green-card seriousness signal |
  | `demand_growth_naics` | JOLTS/CES change for the NAICS |
  | `soc_10yr_growth` | BLS projections |
  | `cap_exempt_subcategory` | HIGHER_ED / AFFILIATED_NONPROFIT / NONPROFIT_RESEARCH / GOVT_RESEARCH / NONE |
  | `cap_exempt_confidence` | HIGH / MEDIUM / LOW / MANUAL_REVIEW |
  | `staffing_firm_flag` | TRUE if heuristic identifies as body shop / IT staffing |
  | `recent_layoffs_flag` | recent WARN notice tagged |
  | `layoff_positions_recent` | total positions in recent WARN notices |
  | `evidence_tier` | HIGH / MEDIUM / LOW — confidence based on sample size + multi-source corroboration |

- **Forbidden**: a single combined `est_real_sponsorship = volume × rate`
  column. The two metrics have different denominators and combining them
  is dimensionally wrong. Realism is computed in `scoring.py` separately for
  cap-exempt and cap-subject branches — see Realism Scoring section.

---

## REALISM SCORING (compute explicitly; do not combine mismatched metrics)

Sponsorship realism is bifurcated. Never average across the two branches; the
mechanics are different.

Thresholds and weights are dual-channel: defaults live in `config.yaml` /
`user_profile.yaml` and are listed in the DEFAULTS REFERENCE at the end of
this document. Pipeline reads from the YAML — never hardcode in `scoring.py`.

### For cap-exempt employers (no lottery)
```
sponsorship_realism_capex =
    initial_approval_rate
    × min(1.0, uscis_initial_approvals_window / N_threshold_capexempt)   # sample-size dampener
    × (1 - staffing_firm_penalty)
    × (1 - layoff_penalty_if_recent)
```
The dampener prevents tiny-sample employers from topping rankings on a single
approval. The cap-exempt threshold is set LOWER than cap-subject because
think tanks, university centers, and policy research orgs legitimately
operate at lower absolute volumes than commercial sponsors — a too-high
threshold would mask the very lane this pipeline is built to surface.

### For cap-subject employers (lottery applies)
```
sponsorship_realism_capsub =
    initial_approval_rate
    × lottery_selection_rate         # from config.yaml, sourced + dated
    × min(1.0, uscis_initial_approvals_window / N_threshold_capsubject)
    × (1 - staffing_firm_penalty)
    × (1 - layoff_penalty_if_recent)
```
The cap-subject threshold is set HIGHER because cap-subject sponsorship at
low volume usually indicates one-off accommodation of a specific candidate,
not systematic sponsorship behavior a new applicant can rely on.

### Personal score (per row, given `user_profile.yaml`)
```
personal_score =
    sponsorship_realism × w_realism
  + wage_adequacy       × w_wage           # filed wage vs. user's floor
  + soc_fit             × w_fit            # user's per-SOC weight
  + metro_fit           × w_metro          # user's preferred metros
  + demand_signal       × w_demand
  - layoff_penalty      × w_layoff
```
Positive weights (`w_realism + w_wage + w_fit + w_metro + w_demand`) sum to
1.0; `w_layoff` is applied separately as a penalty so a layoff signal can
fully suppress a row when severe. Score is computed per
(employer × SOC × CBSA) row, then aggregated as needed for views. Filters
(cap-exempt-only, exclude staffing, wage floor) are applied BEFORE scoring,
so the score reflects only candidates that passed the gates.

### Staffing-firm heuristic
`staffing_firm_flag = TRUE` if ALL of:
- NAICS in {541512, 541513, 541519} OR known-staffing override list, AND
- `pct_level_1 >= 0.50` (most filings at entry-level wage), AND
- `lca_filings_window >= 100` (volume threshold for "shop" scale).

Plus a manually curated override allow/deny list for the top ~50 known firms
(Cognizant, Infosys, TCS, Wipro, HCL, Tech Mahindra, LTI, Capgemini, etc.).
User can toggle inclusion in `user_profile.yaml`.

---

## CAP-EXEMPT IS A FIRST-CLASS DIMENSION

Universities, nonprofits affiliated with institutions of higher education,
nonprofit research organizations, and governmental research organizations can
sponsor H-1B OUTSIDE the lottery — no cap, file anytime. For a SAIS grad this
is a major underexploited lane (think tanks, university research centers,
some NGOs/policy orgs). It is **critical** for non-STEM-CIP graduates
(Phase 0.0) because they likely get only one cap shot.

### Subcategory determination (per 0.3 verification of 8 CFR 214.2(h)(8)(ii)(F))

| Subcategory | Test | Confidence floor |
|---|---|---|
| `HIGHER_ED` | Accredited institution of higher education (Title IV / IPEDS list) | HIGH if matched |
| `AFFILIATED_NONPROFIT` | 501(c)(3) + documented affiliation with institution of higher education | MEDIUM (needs affiliation evidence) |
| `NONPROFIT_RESEARCH` | 501(c)(3) + meets 8 CFR 214.2(h)(8)(ii)(F)(2) research-org test | MEDIUM/LOW (test is restrictive) |
| `GOVT_RESEARCH` | Governmental entity with research mandate | MEDIUM |
| `NONE` | Cap-subject | HIGH |

### Flag build sources
- Federal IPEDS / Title IV list → `HIGHER_ED` HIGH-confidence.
- IRS 990 bulk data → 501(c)(3) status (necessary but not sufficient for any
  subcategory besides HIGHER_ED).
- `.edu` domain matching → secondary signal for `HIGHER_ED` /
  `AFFILIATED_NONPROFIT`.
- User's manual cap-exempt org list (`user_profile.yaml`) → HIGH confidence,
  overrides automation.
- Everything else → MANUAL_REVIEW with `manifest/cap_exempt_review.csv` the
  user can correct; decisions persisted across quarterly runs.

A generic 501(c)(3) (e.g., an advocacy nonprofit) is **not** automatically
cap-exempt. Do not ship a boolean.

---

## OUTPUT VIEWS (write to /data/marts as parquet + csv)

1. **`ranked_employers`** — sponsors filtered to my target SOCs, sorted by
   `sponsorship_realism` (within-branch), with wage + initial-approval-rate +
   cap-exempt subcategory + staffing-firm + layoff + evidence-tier flags.
   Bifurcated files for cap-exempt vs. cap-subject — never averaged.
2. **`metro_heatmap`** — sponsorship volume × demand by CBSA for my target
   roles.
3. **`role_trends`** — which SOC codes are growing in BOTH demand and
   sponsorship (pre/post-2024 regime-aware).
4. **`cap_exempt_targets`** — the no-lottery lane, ranked by realism, broken
   out by subcategory.
5. **`red_flags`** — employers with high LCA volume but low initial-approval
   rate, large negative within-level wage gap, or staffing-firm + Level 1
   pattern (mills / risky sponsors to avoid).
6. **`green_card_friendly_employers`** — ranked by
   `perm_certifications_window` and `perm_to_lca_ratio`. An employer that
   PERMs is committed beyond H-1B — higher long-term value.
7. **`personal_top_targets`** — applies the `personal_score` formula and the
   `user_profile.yaml` filters (SOC weights, metro preferences,
   cap-exempt-only toggle, wage floor, exclude staffing). This is the
   actionable answer to "where do I apply?"
8. **`timing_calendar`** — operational view per employer: cap-exempt →
   "outreach anytime"; cap-subject → "outreach by Dec for March FYxxxx
   registration; ideal start Oct FYxxxx". Drives the actual outreach
   schedule.

Every view carries `evidence_tier` and a generated-at timestamp. Headline
sorts use realism as primary, evidence_tier as secondary — tiny-sample
employers never reach the top by accident.

---

## ACCURACY GUARDRAILS (enforce in code + comment)
- **LCA filings ≠ petitions ≠ approvals.** Never report LCA volume as
  "hiring." Use `uscis_initial_approvals_window` for realized sponsorship.
  Use LCA volume only as forward intent, labeled as such.
- **Initial vs. Continuing approvals are distinct.** Headline rankings use
  Initial only. Continuing is renewal context.
- **Bifurcate cap-exempt vs. cap-subject scoring.** Never combine into a
  single ranking without showing the split.
- **Pre/post-2024 regime windows are reported separately.** Don't average
  across the FY2025 selection-rule change.
- **Date-stamp everything.** Record source URL + download date + sha256 in
  `manifest/sources.json` for every dataset.
- **Per-year schema mappers for DOL files;** fail loudly if an expected
  column is missing rather than silently dropping it.
- **Wage gaps computed within wage level**, not against the gross median —
  Level I attestations are legitimately below median.
- **Keep a `/data/raw` immutable copy;** all transforms reproducible from raw.
- **Log every fuzzy-match decision** above/below threshold to a review CSV;
  re-runs reuse prior decisions.
- **H-1B rules change yearly** — keep all rule values in `config.yaml` as
  dated, sourced entries (from Phase 0.3); don't hardcode them in logic.
- **Forward-looking claims carry their data lag** as a label (Phase 0.5).
- **Suppress single-filing employers from headline views.** Sample-size
  dampening in scoring + `evidence_tier` filtering in sort.
- **Cap-exempt is a subcategory, not a boolean.** Display the subcategory
  and confidence.
- **OEWS suppression is preserved as NULL, never imputed.** A missing market
  wage flags low confidence; don't manufacture one.

---

## ENVIRONMENT & TESTS

### Environment
- Python 3.11.x pinned.
- `uv` for resolution; `pyproject.toml` + `uv.lock` committed.
- `.env` for secrets (BLS API key); `.env.example` committed; `.env`
  gitignored.
- `make verify-env` checks that the live environment matches the lockfile.

### Validation gates (between staging → marts)
- `pandera` schemas per source: wage range $15K–$1M, SOC codes ∈ official
  list, NAICS codes ∈ official list, decision dates within plausible window,
  wage-level ∈ {1,2,3,4} where present.
- Distribution sanity: <1% null in load-bearing columns; reject ingest if a
  file is >80% nulls in critical fields (likely corrupt).

### Tests
- **Unit**: per parser, against a 100-row fixture per source committed to
  `/tests/fixtures`.
- **Integration**: small synthetic LCA + USCIS + WARN datasets join
  end-to-end to a known mart shape.
- **Smoke**: each quarterly run alerts if any mart's row count deviates >20%
  from last quarter's snapshot (`manifest/snapshots/`).
- **Lineage check**: no orphaned keys in joins; every LCA-only entity that
  fails to match a USCIS entity is logged with its normalized name for
  review.

### Incremental runs
- `manifest/sources.json` carries URL + ETag/Last-Modified + sha256 of last
  download per source. `run.py --incremental` skips unchanged sources.
- `--force-refresh` re-downloads everything.
- `--dry-run` reports what would be downloaded/processed, runs no
  transforms.

---

## DELIVERABLES
- Working pipeline runnable via `python run.py` (or `make all`), with
  `--incremental`, `--force-refresh`, `--dry-run` flags.
- The 8 mart views above.
- `phase0_findings.md` (STEM branch, sources, schemas, rules, regime split,
  windows, freshness verdict).
- `user_profile.yaml` (CIP, SOC weights, metros, toggles, manual cap-exempt
  list, custom employer allow/deny lists).
- `config.yaml` (windows, target SOCs/metros, dated rule values, scoring
  thresholds, weight defaults).
- A short README: what each source is, known limitations, STEM/non-STEM
  branch consequences, how to re-run next quarter, where to update column
  mappers when DOL changes schema, how to review the fuzzy-match, geo, and
  cap-exempt queues.
- A data manifest auto-generated each run (sources, dates, sha256, row
  counts, schema diffs vs. prior quarter, deltas in headline metrics).
- Tests + fixtures runnable via `pytest`.

---

## SAIS DEFAULT TARGETING (propose at the 0.6 gate, let me edit)

If I haven't given you SOC codes yet, propose these as a starting set, each
tagged with STEM-OPT eligibility (verify against the live CIP→SOC linkage)
and historical H-1B volume so I can see which are even viable markets:

- **19-3011** Economists — strong SAIS fit, low H-1B volume; quality > quantity.
- **15-2031** Operations Research Analysts — STEM, high H-1B volume.
- **15-2041** Statisticians — STEM, high H-1B volume.
- **13-1111** Management Analysts — large pool, mixed quality (some staffing).
- **13-1161** Market Research Analysts — high volume, often Level I.
- **13-2051** Financial / Investment Analysts — high volume.
- **13-1041** Compliance Officers — policy-adjacent, moderate volume.
- **11-9151** Social / Community Service Managers — policy/NGO fit.
- **19-3094** Political Scientists — strong SAIS fit, very thin H-1B market.
- **19-3022** Survey Researchers — research-org friendly.

Default target metros (CBSA codes to be confirmed against the live OMB
delineation file): DC, NYC, Boston, SF Bay, Seattle. Edit at 0.6 gate.

---

## DEFAULTS REFERENCE (single source of truth for numeric knobs)

Every default below is set for a no-compromise SAIS / international-student
OPT profile. They live in `config.yaml` and `user_profile.yaml`; nothing in
`scoring.py` hardcodes them. The user can override at the 0.6 gate.

### Sample-size dampeners (`config.yaml`)

| Key | Default | Rationale |
|---|---|---|
| `n_threshold_capexempt` | **3** | Over a 4-yr window = ~0.75/yr. A think tank or university center with 3 initial approvals across 4 years is a real, repeat sponsor; setting this higher would mask the cap-exempt lane that's specifically the strategic value for non-STEM-CIP / lottery-averse applicants. Sponsorship rate from 2 → 3 approvals shifts the dampener from 0.67 → 1.0 — a meaningful but not punishing step. |
| `n_threshold_capsubject` | **10** | Over a 4-yr window = ~2.5/yr. With current ~25–30% lottery selection that's still only ~0.6–0.75 realized new hires/yr post-lottery. Below this, a cap-subject employer's H-1B usage typically reflects one-off accommodation of a specific candidate, not a systematic sponsorship program a new applicant can rely on. |
| `window_years_lca` | **4** | Spans the FY2025 beneficiary-centric regime change so pre/post can be compared per 0.3.5. Re-check at 0.4 against what DOL actually serves. |
| `window_years_uscis` | **4** | Same span; ensures the dampeners and approval-rate calculations operate on a consistent window. |
| `lottery_selection_rate` | **DERIVE in 0.3** | Do not hardcode. Pull current FY USCIS-published selection rate (selections / eligible beneficiaries under the beneficiary-centric rule) and cite the source. Fail loudly if not found rather than guessing. |

### Personal-score weights (`user_profile.yaml`)

Positive weights sum to 1.0; `w_layoff` is a separate penalty multiplier.

| Weight | Default | Rationale |
|---|---|---|
| `w_realism` | **0.45** | Dominant. For an F-1 → H-1B applicant, an employer that won't or can't sponsor is a zero regardless of fit. Realism is the binding constraint, weighted accordingly. |
| `w_fit` | **0.20` | SOC fit matters but a SAIS grad can reasonably target several adjacent SOCs (econ, OR, management analyst, policy). Soft-secondary to realism. |
| `w_wage` | **0.15** | DC living cost floor is real but wage_adequacy is a step function (above floor / below floor) more than a smooth gradient. Smaller weight; the floor filter does most of the work before scoring. |
| `w_metro` | **0.10** | Treated as a preference, not a constraint. A great cap-exempt sponsor in an unlisted metro shouldn't be excluded — just down-weighted. |
| `w_demand` | **0.10** | Macro industry-growth context. Weighted lowest because at the individual job-search scale, it's a tiebreaker, not a primary signal. |
| `w_layoff` | **0.25** | Applied as a subtractive penalty, scaled by recency and `layoff_positions_recent` magnitude. Heavy enough that a recent large WARN filing can flip an otherwise-attractive row to negative. |

### Filtering gates (applied BEFORE scoring; `user_profile.yaml`)

| Gate | Default | Rationale |
|---|---|---|
| `cap_exempt_only` | **FALSE if STEM-CIP, TRUE if non-STEM-CIP** | Branch per Phase 0.0. Non-STEM applicants have one cap shot — cap-exempt-only as the headline view avoids burning attention on rolls of a single die. STEM applicants get both lanes by default. |
| `exclude_staffing_firms` | **TRUE** | A SAIS / policy / analyst profile is essentially never the intended hire for Cognizant/Infosys/TCS/Wipro-class employers. Including them inflates the cap-subject ranking with noise. Toggle off only if specifically targeting consulting. |
| `min_wage_floor` | **$75,000** | DC / NYC / Boston cost-of-living floor for a single recent grad. Acts as a hard filter for `personal_top_targets` view; rows below the floor are dropped pre-scoring, not just penalized. |
| `min_evidence_tier` | **MEDIUM** | Headline `personal_top_targets` view suppresses LOW-evidence rows (e.g., single-filing employers, USCIS-Hub-absent employers). LOW-evidence rows still appear in `ranked_employers` for exploratory browsing. |

### Staffing-firm heuristic (`config.yaml`)

| Component | Default | Rationale |
|---|---|---|
| `staffing_naics` | **{541512, 541513, 541519}** | Computer systems design / facilities mgmt / other related services — the NAICS codes the major IT staffing shops file under. Plus the curated override list (Cognizant, Infosys, TCS, Wipro, HCL, Tech Mahindra, LTI, Capgemini, Accenture Federal, Deloitte Consulting US LLP). |
| `staffing_level1_share_min` | **0.50** | ≥50% of an employer's LCAs at PW Level I is a strong tell for staff augmentation rather than direct hire of differentiated talent. |
| `staffing_volume_min` | **100** | Volume threshold for "shop scale" — distinguishes a body-shop pattern from a small business that happens to file at Level I. |

### Schema validation bounds (`config.yaml`, used by pandera)

| Bound | Default | Rationale |
|---|---|---|
| `wage_min_annual` | **$15,000** | Below this is almost certainly a parsing error (e.g., misread hourly rate). Reject the row, log to `manifest/wage_outliers.csv`. |
| `wage_max_annual` | **$1,000,000** | Above this is rare but legitimate for very senior tech / finance roles. Cap at $1M for outlier detection; do not drop. |
| `decision_date_min` | **2010-01-01** | Per-window plausibility; reject earlier dates as parse errors. |
| `null_rate_critical_max` | **0.01** | <1% nulls allowed in load-bearing columns (employer, SOC, wage, decision_date). |
| `null_rate_file_corrupt` | **0.80** | If a file is >80% nulls in critical fields, reject the entire ingest as corrupt. |

### Smoke-test alert threshold (`config.yaml`)

| Key | Default | Rationale |
|---|---|---|
| `mart_row_count_delta_alert` | **0.20** | Any mart whose row count deviates >20% from the prior quarter's snapshot triggers an alert before publishing. Catches schema regressions, ingest failures, and unannounced source changes. |

### What is NOT defaulted (must be supplied or derived)

- `cip_code` — user must provide at Phase 0.0.
- `manual_cap_exempt_orgs` — user provides at 0.6 gate.
- `target_socs` — user confirms or accepts SAIS defaults at 0.6 gate.
- `target_metros_cbsa` — user confirms or accepts defaults at 0.6 gate.
- `lottery_selection_rate` — derived live in Phase 0.3 from USCIS, never
  hardcoded.
- `stem_cip_list` — pulled live in Phase 0.0 from ICE/SEVP, never hardcoded.
- `n_corporate_groups` — corporate-group override list is curated and grows
  per quarterly review; no default seed beyond the FAANG / big-bank /
  consultancy top tier.

---

## START BY
1. Phase 0.0: ask for my CIP code, pull the live STEM list, branch the
   pipeline. State the branch decision explicitly.
2. Phase 0.1–0.5: verify sources, schemas, rules (with regime-change check),
   windows, freshness.
3. Stop at the 0.6 gate. Show me `phase0_findings.md` + one-screen summary +
   STEM/non-STEM branch decision + proposed SOC/metro defaults.
4. Confirm with me. Adjust `config.yaml` and `user_profile.yaml`.
5. Ingest and validate ONE DOL year end-to-end (including wage-level
   capture, geographic normalization, and entity resolution against a USCIS
   slice) before building the rest, so we catch schema and matching issues
   early.
6. Build the rest. Run the smoke + validation tests. Generate views.
