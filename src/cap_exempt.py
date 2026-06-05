"""Cap-exempt subcategory determination.

Five outcomes (per 8 CFR 214.2(h)(19)(iii)(C), Dec 2024 modernization rule):
  HIGHER_ED, AFFILIATED_NONPROFIT, NONPROFIT_RESEARCH, GOVT_RESEARCH, NONE

Sources of evidence:
  - IPEDS Title-IV list                       -> HIGHER_ED HIGH
  - User's manual cap_exempt_orgs list        -> HIGH (overrides automation)
  - ProPublica 501(c)(3) subsection_code=3    -> NONPROFIT_RESEARCH MEDIUM
                                                 (under "fundamental activity"
                                                 test research orgs qualify
                                                 even when not primarily
                                                 research)
  - NTEE code starts with 'U' (research/sci)  -> NONPROFIT_RESEARCH MEDIUM
  - everything else                           -> NONE HIGH

The 2024 modernization rule loosened the test from "primary mission" to
"fundamental activity" — confidence raised from LOW to MEDIUM for nonprofit
research category.
"""

from __future__ import annotations

import logging
from pathlib import Path

import polars as pl

from .common import STAGING, load_user_profile, normalize_employer_name

_log = logging.getLogger("h1b.cap_exempt")


def _ipeds_set(path: Path | None) -> set[str]:
    if path is None or not path.exists():
        return set()
    df = pl.read_parquet(path)
    if "employer_norm" not in df.columns:
        return set()
    return set(df["employer_norm"].to_list())


def _propublica_lookup(path: Path | None) -> pl.DataFrame:
    if path is None or not path.exists():
        return pl.DataFrame()
    return pl.read_parquet(path)


def classify(
    employer_norm: str,
    *,
    ipeds_set: set[str],
    propublica_df: pl.DataFrame,
    manual_set: set[str],
) -> tuple[str, str]:
    """Return (subcategory, confidence) for an already-normalized employer name."""
    if not employer_norm:
        return ("NONE", "HIGH")
    if employer_norm in manual_set:
        return ("AFFILIATED_NONPROFIT", "HIGH")  # user-curated; manual list = trusted
    if employer_norm in ipeds_set:
        return ("HIGHER_ED", "HIGH")
    if propublica_df.height:
        match = propublica_df.filter(pl.col("employer_norm") == employer_norm)
        if match.height:
            row = match.row(0, named=True)
            subs = str(row.get("subsection_code") or "")
            ntee = str(row.get("ntee_code") or "").upper()
            if subs == "3":  # 501(c)(3)
                if ntee.startswith("U") or ntee.startswith("B"):
                    # U = Science & Tech research; B = Higher education-related
                    return ("NONPROFIT_RESEARCH", "MEDIUM")
                return ("AFFILIATED_NONPROFIT", "LOW")  # 501(c)(3) but unclear
    return ("NONE", "HIGH")


def classify_dataframe(
    df: pl.DataFrame,
    *,
    employer_norm_col: str = "employer_norm",
) -> pl.DataFrame:
    """Annotate df with `cap_exempt_subcategory` + `cap_exempt_confidence`."""
    ipeds_set = _ipeds_set(STAGING / "ipeds" / "title_iv_institutions.parquet")
    propublica_df = _propublica_lookup(STAGING / "irs" / "propublica_lookups.parquet")
    profile = load_user_profile()
    manual_raw = profile.get("manual_cap_exempt_orgs", []) or []
    manual_set = {normalize_employer_name(x) for x in manual_raw}

    def _classify_one(norm: str) -> dict:
        sub, conf = classify(
            norm,
            ipeds_set=ipeds_set,
            propublica_df=propublica_df,
            manual_set=manual_set,
        )
        return {"cap_exempt_subcategory": sub, "cap_exempt_confidence": conf}

    enriched = df.with_columns(
        pl.col(employer_norm_col)
        .map_elements(_classify_one, return_dtype=pl.Struct({"cap_exempt_subcategory": pl.String, "cap_exempt_confidence": pl.String}))
        .alias("_ce")
    )
    enriched = enriched.unnest("_ce")
    return enriched
