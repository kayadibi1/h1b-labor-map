"""Print the top results for a SAIS / non-STEM applicant."""
from __future__ import annotations

from pathlib import Path

import polars as pl

pl.Config.set_tbl_rows(30)
pl.Config.set_tbl_cols(30)
pl.Config.set_fmt_str_lengths(70)

MARTS = Path("data/marts")
TARGET_SOCS = {"19-3011", "15-2031", "15-2041", "13-1111", "13-1161",
               "13-2051", "13-1041", "11-9151", "19-3094", "19-3022"}

p = pl.read_parquet(MARTS / "personal_top_targets.parquet")
print(f"\n=== personal_top_targets ({p.height} rows) ===")
keep = [c for c in [
    "employer_name", "employer_group", "soc_code", "cbsa_code",
    "branch", "cap_exempt_subcategory",
    "uscis_initial_approvals_window", "initial_approval_rate",
    "median_wage_filed", "sponsorship_realism", "personal_score",
    "evidence_tier",
] if c in p.columns]
print(p.select(keep))

cet = pl.read_parquet(MARTS / "cap_exempt_targets.parquet")
print(f"\n=== cap_exempt_targets all SOCs ({cet.height} rows total) ===")
keep2 = [c for c in [
    "employer_name", "employer_group", "soc_code", "soc_title",
    "cbsa_code", "cap_exempt_subcategory",
    "uscis_initial_approvals_window", "lca_filings_window",
    "initial_approval_rate", "median_wage_filed",
    "sponsorship_realism", "evidence_tier",
] if c in cet.columns]

# Top by realism, all SOCs
print("\n-- top 20 by realism (all SOCs) --")
print(cet.sort("sponsorship_realism", descending=True).select(keep2).head(20))

# Restricted to target SOCs
cet_sais = cet.filter(pl.col("soc_code").is_in(list(TARGET_SOCS)))
print(f"\n-- cap-exempt filtered to SAIS target SOCs ({cet_sais.height} rows) --")
print(cet_sais.sort("sponsorship_realism", descending=True).select(keep2).head(30))

# Show distribution of cap-exempt SOCs to understand the market
print("\n-- top 20 cap-exempt SOCs by approval count --")
agg = (
    cet.group_by(["soc_code", "soc_title"])
    .agg(
        [
            pl.col("uscis_initial_approvals_window").sum().alias("total_approvals"),
            pl.col("employer_name").n_unique().alias("n_employers"),
        ]
    )
    .sort("total_approvals", descending=True)
    .head(20)
)
print(agg)
