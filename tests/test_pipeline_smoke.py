"""Smoke test: full join -> score -> views on synthetic data."""

import polars as pl
import pytest

from src.cap_exempt import classify_dataframe
from src.entity_resolve import attach_canonical_to_df
from src.geo_normalize import attach_cbsa
from src.join import build_mart
from src.scoring import score_mart
from src.views import build_views


def _enrich_dol_staging(staging_dir):
    """Apply entity resolve + geo + cap-exempt enrichment to staged DOL parquets."""
    for p in (staging_dir["staging"] / "dol" / "lca").glob("*.parquet"):
        df = pl.read_parquet(p)
        df = attach_canonical_to_df(df, employer_col="employer_name", norm_col="employer_norm")
        df = attach_cbsa(df, city_col="worksite_city", state_col="worksite_state")
        df = classify_dataframe(df)
        df.write_parquet(p)


def test_full_pipeline_smoke(staging_dir, synthetic_dol, synthetic_uscis, synthetic_oews):
    _enrich_dol_staging(staging_dir)
    mart = build_mart()
    assert mart.exists()
    df = pl.read_parquet(mart)
    assert df.height >= 4, "expected >=4 mart rows for 4 synthetic employers"
    assert "employer_group" in df.columns
    assert "window_label" in df.columns

    # Sponsorship branch + scoring
    scored = score_mart()
    assert scored.exists()
    sdf = pl.read_parquet(scored)
    assert "sponsorship_realism" in sdf.columns
    assert "branch" in sdf.columns
    branches = set(sdf["branch"].to_list())
    assert "CAP_EXEMPT" in branches
    assert "CAP_SUBJECT" in branches

    # Brookings (cap-exempt) should outscore Infosys (cap-subject + staffing)
    brk = sdf.filter(pl.col("employer_norm") == "BROOKINGS INSTITUTION")
    inf = sdf.filter(pl.col("employer_norm") == "INFOSYS")
    if brk.height and inf.height:
        assert brk["sponsorship_realism"].max() > inf["sponsorship_realism"].max()

    # Views generation
    build_views()
    capex = staging_dir["marts"] / "ranked_employers_capexempt.parquet"
    capsub = staging_dir["marts"] / "ranked_employers_capsubject.parquet"
    cal = staging_dir["marts"] / "timing_calendar.parquet"
    assert capex.exists()
    assert capsub.exists()
    assert cal.exists()
