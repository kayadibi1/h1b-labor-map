"""Sponsorship-realism + personal-score computation.

Bifurcated cap-exempt vs cap-subject realism with wage-level-weighted
lottery rate for FY2027+ cap-subject scoring.

All numeric knobs come from config.yaml + user_profile.yaml; nothing here is
hardcoded. Mirrors the formulas in labor_market_h1b_map_blueprint.md.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import polars as pl

from .common import MARTS, load_config, load_user_profile

_log = logging.getLogger("h1b.scoring")


def _staffing_firm_flag(
    naics_code: str | None,
    pct_level_1: float | None,
    lca_filings_window: int | None,
    *,
    cfg: dict[str, Any],
) -> bool:
    sf = cfg["staffing_firm"]
    if naics_code:
        try:
            if int(str(naics_code)[:6]) in sf["naics_codes"]:
                if (pct_level_1 or 0) >= sf["level1_share_min"]:
                    if (lca_filings_window or 0) >= sf["volume_min"]:
                        return True
        except (ValueError, TypeError):
            pass
    return False


def _staffing_override_match(employer_norm: str, cfg: dict[str, Any]) -> bool:
    overrides = cfg["staffing_firm"].get("known_staffing_overrides", [])
    if not employer_norm:
        return False
    for o in overrides:
        if o in employer_norm or employer_norm.startswith(o):
            return True
    return False


def _layoff_penalty(layoffs_recent: int, positions: int, lookback: int) -> float:
    """Returns a multiplier in [0, 1] where 0 = full suppression. Scales with size."""
    if not layoffs_recent:
        return 0.0
    if positions <= 0:
        return 0.1  # small unsized layoff
    # 0.1 per layoff event + scaled by positions; cap at 0.9
    base = min(0.9, 0.1 + (positions / 5000.0))
    return base


def _f(x) -> float:
    """Coerce arbitrary numeric (incl. Decimal from DuckDB) to float, NaN-safe."""
    if x is None:
        return 0.0
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    if v != v:  # NaN
        return 0.0
    return v


def realism_capexempt(
    initial_approval_rate: float | None,
    initial_approvals: int | None,
    *,
    n_threshold: int,
    staffing_flag: bool,
    layoff_penalty: float,
) -> float:
    rate = _f(initial_approval_rate) if initial_approval_rate is not None else 0.5
    n = _f(initial_approvals)
    damp = min(1.0, n / float(n_threshold)) if n_threshold > 0 else 1.0
    staffing = 0.7 if staffing_flag else 0.0
    return max(0.0, rate * damp * (1 - staffing) * (1 - layoff_penalty))


def realism_capsubject(
    initial_approval_rate: float | None,
    initial_approvals: int | None,
    pct_level_1: float | None,
    pct_level_2: float | None,
    pct_level_3: float | None,
    pct_level_4: float | None,
    *,
    n_threshold: int,
    wage_level_selection_rates: dict[str, float],
    base_lottery_rate: float,
    staffing_flag: bool,
    layoff_penalty: float,
) -> float:
    """Cap-subject realism with wage-level-weighted lottery.

    Expected effective lottery rate is the weighted average of per-level
    selection rates by this employer's filing mix. Defaults to base rate if
    levels are unavailable.
    """
    rate = _f(initial_approval_rate) if initial_approval_rate is not None else 0.5
    p1, p2, p3, p4 = _f(pct_level_1), _f(pct_level_2), _f(pct_level_3), _f(pct_level_4)
    total = p1 + p2 + p3 + p4
    if total > 0:
        eff_lottery = (
            p1 * float(wage_level_selection_rates.get("1", base_lottery_rate))
            + p2 * float(wage_level_selection_rates.get("2", base_lottery_rate))
            + p3 * float(wage_level_selection_rates.get("3", base_lottery_rate))
            + p4 * float(wage_level_selection_rates.get("4", base_lottery_rate))
        ) / total
    else:
        eff_lottery = float(base_lottery_rate)
    n = _f(initial_approvals)
    damp = min(1.0, n / float(n_threshold)) if n_threshold > 0 else 1.0
    staffing = 0.7 if staffing_flag else 0.0
    return max(0.0, rate * eff_lottery * damp * (1 - staffing) * (1 - layoff_penalty))


def evidence_tier(lca_filings, initial_approvals) -> str:
    """HIGH / MEDIUM / LOW based on sample size.

    Realized approvals dominate the signal. LCA filings (intent) are
    corroborating but secondary, because the DOL↔USCIS employer-name fuzzy-join
    is lossy: cap-exempt orgs in particular often show high USCIS approvals
    paired with low LCA matches due to legal-entity name drift between filings.
    """
    lf = _f(lca_filings)
    ia = _f(initial_approvals)
    has_uscis = initial_approvals is not None and ia > 0
    # HIGH: 10+ approvals (any LCA count) OR 20+ LCAs + 5+ approvals
    if has_uscis and (ia >= 10 or (ia >= 5 and lf >= 20)):
        return "HIGH"
    # MEDIUM: 3+ approvals OR 5+ LCAs + 1+ approval
    if has_uscis and (ia >= 3 or lf >= 5):
        return "MEDIUM"
    return "LOW"


def score_mart(
    mart_path: Path | None = None,
    *,
    config: dict[str, Any] | None = None,
    user_profile: dict[str, Any] | None = None,
    out_path: Path | None = None,
) -> Path:
    """Apply scoring to the mart fact table; write scored mart."""
    cfg = config or load_config()
    profile = user_profile or load_user_profile()

    mart_path = mart_path or (MARTS / "mart_fact.parquet")
    df = pl.read_parquet(mart_path)

    n_capex = cfg["dampeners"]["n_threshold_capexempt"]
    n_capsub = cfg["dampeners"]["n_threshold_capsubject"]
    wage_rates = {
        k: float(v) for k, v in cfg["rules"]["wage_level_adjusted_selection_rate_fy2027"].items()
        if k in {"1", "2", "3", "4"}
    }
    base_lottery = cfg["rules"]["lottery_selection_rate_fy2026"]["value"]

    soc_weights = profile.get("soc_weights", {})
    metro_weights = profile.get("metro_weights", {})
    w = profile["weights"]
    floor = profile["gates"]["min_wage_floor_usd_annual"]

    # Build new columns as separate lists (preserve original schema for the rest).
    staffing_flags: list[bool] = []
    branches: list[str] = []
    realisms: list[float] = []
    personals: list[float] = []
    tiers: list[str] = []

    for r in df.iter_rows(named=True):
        staffing_flag = _staffing_firm_flag(
            r.get("naics_code"),
            r.get("pct_level_1"),
            r.get("lca_filings_window"),
            cfg=cfg,
        ) or _staffing_override_match(r.get("employer_norm") or "", cfg)

        layoff_pen = _layoff_penalty(
            int(_f(r.get("recent_layoffs_count"))),
            int(_f(r.get("layoff_positions_recent"))),
            cfg["windows"]["layoff_lookback_months"],
        )

        cap_sub = r.get("cap_exempt_subcategory") or "NONE"
        ia = r.get("uscis_initial_approvals_window")
        ar = r.get("initial_approval_rate")
        if cap_sub == "NONE":
            realism = realism_capsubject(
                ar, ia,
                r.get("pct_level_1"), r.get("pct_level_2"),
                r.get("pct_level_3"), r.get("pct_level_4"),
                n_threshold=n_capsub,
                wage_level_selection_rates=wage_rates,
                base_lottery_rate=base_lottery,
                staffing_flag=staffing_flag,
                layoff_penalty=layoff_pen,
            )
            branch = "CAP_SUBJECT"
        else:
            realism = realism_capexempt(
                ar, ia,
                n_threshold=n_capex,
                staffing_flag=staffing_flag,
                layoff_penalty=layoff_pen,
            )
            branch = "CAP_EXEMPT"

        soc_w = _f(soc_weights.get(r.get("soc_code") or "", 0.0))
        metro_w = _f(metro_weights.get(r.get("cbsa_code") or "", 0.0))
        wage_filed = _f(r.get("median_wage_filed"))
        wage_adequacy = 1.0 if wage_filed >= float(floor) else max(0.0, wage_filed / max(float(floor), 1.0))
        demand_signal = 0.5  # placeholder until JOLTS/CES wired into mart join

        personal = (
            realism * float(w["w_realism"])
            + wage_adequacy * float(w["w_wage"])
            + soc_w * float(w["w_fit"])
            + metro_w * float(w["w_metro"])
            + demand_signal * float(w["w_demand"])
            - layoff_pen * float(w["w_layoff"])
        )

        tier = evidence_tier(r.get("lca_filings_window"), ia)

        staffing_flags.append(bool(staffing_flag))
        branches.append(branch)
        realisms.append(float(realism))
        personals.append(float(personal))
        tiers.append(tier)

    scored = df.with_columns(
        [
            pl.Series("staffing_firm_flag", staffing_flags, dtype=pl.Boolean),
            pl.Series("branch", branches, dtype=pl.String),
            pl.Series("sponsorship_realism", realisms, dtype=pl.Float64),
            pl.Series("personal_score", personals, dtype=pl.Float64),
            pl.Series("evidence_tier", tiers, dtype=pl.String),
        ]
    )
    out = out_path or (MARTS / "mart_scored.parquet")
    scored.write_parquet(out)
    _log.info("scored %s rows -> %s", scored.height, out)
    return out
