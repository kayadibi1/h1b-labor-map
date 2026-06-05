"""Generate the 8 output mart views (parquet + csv) per blueprint.

  1. ranked_employers
  2. metro_heatmap
  3. role_trends
  4. cap_exempt_targets
  5. red_flags
  6. green_card_friendly_employers
  7. personal_top_targets
  8. timing_calendar
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from .common import MARTS, load_config, load_user_profile

_log = logging.getLogger("h1b.views")

TIER_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}


def _write(df: pl.DataFrame, name: str) -> None:
    if df.is_empty():
        _log.warning("view %s is empty", name)
        return
    parquet_path = MARTS / f"{name}.parquet"
    csv_path = MARTS / f"{name}.csv"
    df = df.with_columns(pl.lit(datetime.now(timezone.utc).isoformat()).alias("generated_at"))
    df.write_parquet(parquet_path)
    df.write_csv(csv_path)
    _log.info("view %s -> %d rows", name, df.height)


_STEM_CIPS = {"45.0603", "30.4901", "30.7001", "30.7101", "30.7102", "30.7104"}


def build_views(scored_path: Path | None = None) -> None:
    cfg = load_config()
    profile = load_user_profile()
    target_socs = {s["code"] for s in cfg.get("target_socs", [])}
    target_metros = {m["cbsa"] for m in cfg.get("target_metros", [])}

    # cap_exempt_only auto-branches on STEM-CIP eligibility when null.
    cap_exempt_only_setting = profile["gates"].get("cap_exempt_only")
    if cap_exempt_only_setting is None:
        cip = profile.get("identity", {}).get("cip_code", "")
        cap_exempt_only = cip not in _STEM_CIPS
        _log.info("cap_exempt_only auto-branch (CIP=%s, STEM=%s) -> %s",
                  cip, cip in _STEM_CIPS, cap_exempt_only)
    else:
        cap_exempt_only = bool(cap_exempt_only_setting)

    exclude_staffing = bool(profile["gates"].get("exclude_staffing_firms", True))
    min_tier = profile["gates"].get("min_evidence_tier", "MEDIUM").upper()
    min_tier_rank = TIER_RANK.get(min_tier, 2)
    floor = profile["gates"].get("min_wage_floor_usd_annual", 0)

    scored = pl.read_parquet(scored_path or (MARTS / "mart_scored.parquet"))

    # --- 1. ranked_employers (bifurcated cap-exempt / cap-subject) ---------
    base = scored
    if target_socs:
        base = base.filter(pl.col("soc_code").is_in(list(target_socs)))

    cap_exempt = base.filter(pl.col("branch") == "CAP_EXEMPT").sort(
        ["sponsorship_realism"], descending=True
    )
    cap_subject = base.filter(pl.col("branch") == "CAP_SUBJECT").sort(
        ["sponsorship_realism"], descending=True
    )

    _write(cap_exempt, "ranked_employers_capexempt")
    _write(cap_subject, "ranked_employers_capsubject")

    # --- 2. metro_heatmap ---------------------------------------------------
    heat = base.group_by(["cbsa_code", "soc_code"]).agg(
        [
            pl.col("lca_filings_window").sum().alias("lca_total"),
            pl.col("uscis_initial_approvals_window").sum().alias("initial_approvals_total"),
            pl.col("sponsorship_realism").mean().alias("realism_mean"),
        ]
    )
    _write(heat, "metro_heatmap")

    # --- 3. role_trends -----------------------------------------------------
    trends = scored.group_by(["soc_code", "soc_title", "window_label"]).agg(
        [
            pl.col("lca_filings_window").sum().alias("lca_total"),
            pl.col("uscis_initial_approvals_window").sum().alias("initial_approvals_total"),
        ]
    )
    _write(trends, "role_trends")

    # --- 4. cap_exempt_targets ---------------------------------------------
    targets = scored.filter(
        (pl.col("branch") == "CAP_EXEMPT") & (pl.col("cap_exempt_subcategory") != "NONE")
    ).sort("sponsorship_realism", descending=True)
    _write(targets, "cap_exempt_targets")

    # --- 5. red_flags ------------------------------------------------------
    red = scored.filter(
        (pl.col("lca_filings_window") >= 100)
        & (
            (pl.col("initial_approval_rate") < 0.6)
            | (pl.col("staffing_firm_flag") == True)  # noqa: E712
            | (pl.col("pct_level_1").fill_null(0.0) >= 0.5)
        )
    ).sort("lca_filings_window", descending=True)
    _write(red, "red_flags")

    # --- 6. green_card_friendly_employers ---------------------------------
    # Placeholder for when PERM-window columns are wired in.
    if "perm_certifications_window" in scored.columns:
        green = scored.filter(pl.col("perm_certifications_window") > 0).sort(
            "perm_certifications_window", descending=True
        )
    else:
        green = scored.select(pl.col("employer_group")).unique().head(0)
    _write(green, "green_card_friendly_employers")

    # --- 7. personal_top_targets -------------------------------------------
    p = scored
    if cap_exempt_only:
        p = p.filter(pl.col("branch") == "CAP_EXEMPT")
    if exclude_staffing:
        p = p.filter(pl.col("staffing_firm_flag") == False)  # noqa: E712
    if floor:
        p = p.filter(pl.col("median_wage_filed").fill_null(0.0) >= float(floor))
    if target_socs:
        p = p.filter(pl.col("soc_code").is_in(list(target_socs)))
    if target_metros:
        p = p.filter(pl.col("cbsa_code").is_in(list(target_metros)) | pl.col("cbsa_code").is_null())
    p = p.with_columns(
        pl.col("evidence_tier")
        .map_elements(lambda t: TIER_RANK.get(t or "LOW", 1), return_dtype=pl.Int32)
        .alias("evidence_tier_rank")
    ).filter(pl.col("evidence_tier_rank") >= min_tier_rank)
    p = p.sort(["personal_score", "evidence_tier_rank"], descending=[True, True])
    _write(p.head(500), "personal_top_targets")

    # --- 8. timing_calendar ------------------------------------------------
    # FY2027 registration occurred March 4-19, 2026. FY2028 will be Mar 2027.
    rules = cfg["rules"]
    next_reg = "March 2027 (FY2028 lottery)"
    cal = scored.select(
        [
            "employer_name",
            "employer_group",
            "employer_norm",
            "soc_code",
            "soc_title",
            "cbsa_code",
            "branch",
            "cap_exempt_subcategory",
            "sponsorship_realism",
        ]
    ).with_columns(
        [
            pl.when(pl.col("branch") == "CAP_EXEMPT")
            .then(pl.lit("Outreach anytime; no lottery"))
            .otherwise(pl.lit(f"Outreach by Dec 2026 for {next_reg}; ideal start Oct 2027"))
            .alias("timing_guidance")
        ]
    )
    _write(cal, "timing_calendar")
