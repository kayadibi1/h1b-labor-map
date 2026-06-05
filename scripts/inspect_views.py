"""Sanity-check the generated mart views."""
from __future__ import annotations

from pathlib import Path

import polars as pl

MARTS = Path("data/marts")


def show(name: str, df: pl.DataFrame, cols: list[str] | None = None, n: int = 10) -> None:
    print(f"\n=== {name} ({df.height} rows) ===")
    if cols:
        cols = [c for c in cols if c in df.columns]
        df = df.select(cols)
    with pl.Config(tbl_rows=n, tbl_cols=len(df.columns), fmt_str_lengths=50):
        print(df.head(n))


def main() -> None:
    # Mart fact
    mf = pl.read_parquet(MARTS / "mart_fact.parquet")
    print(f"Total mart_fact rows: {mf.height}")
    print(f"Unique employers: {mf['employer_norm'].n_unique()}")
    print(f"Branch breakdown (cap_exempt_subcategory):")
    print(mf.group_by("cap_exempt_subcategory").len().sort("len", descending=True))

    scored = pl.read_parquet(MARTS / "mart_scored.parquet")
    print(f"\nScored rows by branch:")
    print(scored.group_by("branch").len().sort("len", descending=True))
    print(f"\nEvidence tier distribution:")
    print(scored.group_by("evidence_tier").len().sort("len", descending=True))
    print(f"\nStaffing-firm flag rows: {scored.filter(pl.col('staffing_firm_flag')).height}")

    # Headline view: personal_top_targets
    p = pl.read_parquet(MARTS / "personal_top_targets.parquet")
    show(
        "personal_top_targets",
        p,
        cols=[
            "employer_legal",
            "employer_group",
            "soc_code",
            "cbsa_code",
            "branch",
            "cap_exempt_subcategory",
            "uscis_initial_approvals_window",
            "initial_approval_rate",
            "median_wage_filed",
            "sponsorship_realism",
            "personal_score",
            "evidence_tier",
        ],
        n=20,
    )

    # ranked_employers_capexempt (target SOCs only)
    rcx = pl.read_parquet(MARTS / "ranked_employers_capexempt.parquet")
    show(
        "ranked_employers_capexempt",
        rcx,
        cols=[
            "employer_legal",
            "soc_code",
            "cbsa_code",
            "cap_exempt_subcategory",
            "uscis_initial_approvals_window",
            "initial_approval_rate",
            "median_wage_filed",
            "sponsorship_realism",
            "evidence_tier",
        ],
        n=20,
    )

    # cap_exempt_targets (all SOCs)
    cet = pl.read_parquet(MARTS / "cap_exempt_targets.parquet")
    show(
        "cap_exempt_targets (top 20 by realism, all SOCs)",
        cet.sort("sponsorship_realism", descending=True),
        cols=[
            "employer_legal",
            "soc_code",
            "soc_title",
            "cbsa_code",
            "cap_exempt_subcategory",
            "uscis_initial_approvals_window",
            "lca_filings_window",
            "sponsorship_realism",
            "evidence_tier",
        ],
        n=20,
    )

    # ranked_employers_capsubject
    rcs = pl.read_parquet(MARTS / "ranked_employers_capsubject.parquet")
    show(
        "ranked_employers_capsubject",
        rcs,
        cols=[
            "employer_legal",
            "soc_code",
            "cbsa_code",
            "lca_filings_window",
            "uscis_initial_approvals_window",
            "initial_approval_rate",
            "median_wage_filed",
            "pct_level_1",
            "staffing_firm_flag",
            "sponsorship_realism",
            "evidence_tier",
        ],
        n=20,
    )

    # red_flags
    rf = pl.read_parquet(MARTS / "red_flags.parquet")
    show(
        "red_flags",
        rf,
        cols=[
            "employer_legal",
            "soc_code",
            "lca_filings_window",
            "initial_approval_rate",
            "pct_level_1",
            "staffing_firm_flag",
        ],
        n=15,
    )


if __name__ == "__main__":
    main()
