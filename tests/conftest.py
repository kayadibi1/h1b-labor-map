"""Test fixtures for the pipeline. Synthetic data is generated in-tree so the
tests run offline; the fixtures mirror the real schemas the ingest modules
emit after parsing.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import polars as pl
import pytest


REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def staging_dir(tmp_path, monkeypatch):
    """Redirect /data paths into a tmp tree so tests are hermetic."""
    src_common = pl.Series([])  # placeholder so the import order is fine
    base = tmp_path / "data"
    raw = base / "raw"
    staging = base / "staging"
    marts = base / "marts"
    manifest = base / "manifest"
    for p in (raw, staging, marts, manifest):
        p.mkdir(parents=True, exist_ok=True)

    import src.common as common

    monkeypatch.setattr(common, "DATA", base)
    monkeypatch.setattr(common, "RAW", raw)
    monkeypatch.setattr(common, "STAGING", staging)
    monkeypatch.setattr(common, "MARTS", marts)
    monkeypatch.setattr(common, "MANIFEST", manifest)
    monkeypatch.setattr(common, "SOURCES_MANIFEST", manifest / "sources.json")

    # Mirror manifest into modules that imported the constants directly
    import src.join as join_mod
    import src.scoring as scoring_mod
    import src.views as views_mod
    import src.geo_normalize as geo_mod
    import src.entity_resolve as er_mod
    import src.cap_exempt as ce_mod

    monkeypatch.setattr(join_mod, "STAGING", staging)
    monkeypatch.setattr(join_mod, "MARTS", marts)
    monkeypatch.setattr(scoring_mod, "MARTS", marts)
    monkeypatch.setattr(views_mod, "MARTS", marts)
    monkeypatch.setattr(geo_mod, "MANIFEST", manifest)
    monkeypatch.setattr(geo_mod, "GEO_REVIEW_CSV", manifest / "geo_review.csv")
    monkeypatch.setattr(er_mod, "MANIFEST", manifest)
    monkeypatch.setattr(er_mod, "EMPLOYER_MATCHES_CSV", manifest / "employer_matches.csv")
    monkeypatch.setattr(er_mod, "EMPLOYER_REVIEW_CSV", manifest / "employer_matches_review.csv")
    monkeypatch.setattr(
        er_mod,
        "CORPORATE_GROUPS_PATH",
        REPO / "data" / "manifest" / "corporate_groups.yaml",  # real overrides file
    )
    monkeypatch.setattr(ce_mod, "STAGING", staging)

    yield {
        "base": base,
        "raw": raw,
        "staging": staging,
        "marts": marts,
        "manifest": manifest,
    }


@pytest.fixture
def synthetic_dol(staging_dir):
    """Drop one synthetic DOL LCA parquet covering FY2024 + FY2025 employers."""
    dol_dir = staging_dir["staging"] / "dol" / "lca"
    dol_dir.mkdir(parents=True, exist_ok=True)

    rows = [
        # Cap-exempt example: Brookings DC, OR analyst, Level 2
        {
            "case_number": "I-200-24001-001",
            "case_status": "CERTIFIED",
            "decision_date": "2024-06-01",
            "employer_name": "BROOKINGS INSTITUTION",
            "employer_norm": "BROOKINGS INSTITUTION",
            "employer_state": "DC",
            "naics_code": "813920",
            "job_title": "Senior Research Assistant",
            "soc_code": "19-3011",
            "soc_title": "Economists",
            "wage_rate_from": "85000",
            "wage_unit_of_pay": "YEAR",
            "pw_wage": "78000",
            "pw_unit_of_pay": "YEAR",
            "pw_wage_level": "Level II",
            "pw_wage_level_digit": "2",
            "worksite_city": "WASHINGTON",
            "worksite_state": "DC",
            "full_time_position": "Y",
            "wage_rate_annual": 85000.0,
            "pw_wage_annual": 78000.0,
            "fiscal_year": 2024,
        },
        # Cap-subject mega-sponsor: Microsoft Seattle, OR analyst, Level 3
        {
            "case_number": "I-200-24001-002",
            "case_status": "CERTIFIED",
            "decision_date": "2024-06-02",
            "employer_name": "MICROSOFT CORPORATION",
            "employer_norm": "MICROSOFT",
            "employer_state": "WA",
            "naics_code": "541512",
            "job_title": "Senior Data Analyst",
            "soc_code": "15-2031",
            "soc_title": "Operations Research Analysts",
            "wage_rate_from": "165000",
            "wage_unit_of_pay": "YEAR",
            "pw_wage": "150000",
            "pw_unit_of_pay": "YEAR",
            "pw_wage_level": "Level III",
            "pw_wage_level_digit": "3",
            "worksite_city": "REDMOND",
            "worksite_state": "WA",
            "full_time_position": "Y",
            "wage_rate_annual": 165000.0,
            "pw_wage_annual": 150000.0,
            "fiscal_year": 2025,
        },
        # Body-shop: Infosys NJ, low-wage Level 1 mgmt analyst
        {
            "case_number": "I-200-24001-003",
            "case_status": "CERTIFIED",
            "decision_date": "2024-07-01",
            "employer_name": "INFOSYS LIMITED",
            "employer_norm": "INFOSYS",
            "employer_state": "NJ",
            "naics_code": "541512",
            "job_title": "Systems Analyst",
            "soc_code": "13-1111",
            "soc_title": "Management Analysts",
            "wage_rate_from": "75000",
            "wage_unit_of_pay": "YEAR",
            "pw_wage": "72000",
            "pw_unit_of_pay": "YEAR",
            "pw_wage_level": "Level I",
            "pw_wage_level_digit": "1",
            "worksite_city": "JERSEY CITY",
            "worksite_state": "NJ",
            "full_time_position": "Y",
            "wage_rate_annual": 75000.0,
            "pw_wage_annual": 72000.0,
            "fiscal_year": 2025,
        },
        # University: Johns Hopkins DC area
        {
            "case_number": "I-200-24001-004",
            "case_status": "CERTIFIED",
            "decision_date": "2024-09-01",
            "employer_name": "JOHNS HOPKINS UNIVERSITY",
            "employer_norm": "JOHNS HOPKINS UNIVERSITY",
            "employer_state": "MD",
            "naics_code": "611310",
            "job_title": "Research Associate",
            "soc_code": "19-3011",
            "soc_title": "Economists",
            "wage_rate_from": "92000",
            "wage_unit_of_pay": "YEAR",
            "pw_wage": "88000",
            "pw_unit_of_pay": "YEAR",
            "pw_wage_level": "Level II",
            "pw_wage_level_digit": "2",
            "worksite_city": "BALTIMORE",
            "worksite_state": "MD",
            "full_time_position": "Y",
            "wage_rate_annual": 92000.0,
            "pw_wage_annual": 88000.0,
            "fiscal_year": 2024,
        },
    ]
    df = pl.DataFrame(rows)
    df = df.with_columns(pl.lit(None).alias("employer_group"))
    (dol_dir / "fy2024.parquet").write_bytes(b"")
    (dol_dir / "fy2024.parquet").unlink()
    df.filter(pl.col("fiscal_year") == 2024).write_parquet(dol_dir / "fy2024.parquet")
    df.filter(pl.col("fiscal_year") == 2025).write_parquet(dol_dir / "fy2025.parquet")
    return df


@pytest.fixture
def synthetic_uscis(staging_dir):
    """Synthetic USCIS Employer Hub for the same employers."""
    uscis_dir = staging_dir["staging"] / "uscis"
    uscis_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        # Brookings: small but consistent cap-exempt sponsor
        {
            "fiscal_year": 2024,
            "employer": "BROOKINGS INSTITUTION",
            "employer_norm": "BROOKINGS INSTITUTION",
            "initial_approval": 6,
            "initial_denial": 1,
            "continuing_approval": 4,
            "continuing_denial": 0,
            "initial_approval_rate": 6 / 7,
            "naics_code": "813920",
            "city": "WASHINGTON",
            "state": "DC",
        },
        # Microsoft: huge initial counts
        {
            "fiscal_year": 2025,
            "employer": "MICROSOFT CORPORATION",
            "employer_norm": "MICROSOFT",
            "initial_approval": 1500,
            "initial_denial": 80,
            "continuing_approval": 4200,
            "continuing_denial": 30,
            "initial_approval_rate": 1500 / 1580,
            "naics_code": "541512",
            "city": "REDMOND",
            "state": "WA",
        },
        # Infosys: huge volume with elevated denials
        {
            "fiscal_year": 2025,
            "employer": "INFOSYS LIMITED",
            "employer_norm": "INFOSYS",
            "initial_approval": 3500,
            "initial_denial": 800,
            "continuing_approval": 6500,
            "continuing_denial": 200,
            "initial_approval_rate": 3500 / 4300,
            "naics_code": "541512",
            "city": "JERSEY CITY",
            "state": "NJ",
        },
        # JHU: solid cap-exempt
        {
            "fiscal_year": 2024,
            "employer": "JOHNS HOPKINS UNIVERSITY",
            "employer_norm": "JOHNS HOPKINS UNIVERSITY",
            "initial_approval": 90,
            "initial_denial": 5,
            "continuing_approval": 250,
            "continuing_denial": 2,
            "initial_approval_rate": 90 / 95,
            "naics_code": "611310",
            "city": "BALTIMORE",
            "state": "MD",
        },
    ]
    df = pl.DataFrame(rows)
    df.filter(pl.col("fiscal_year") == 2024).write_parquet(uscis_dir / "hub_fy2024.parquet")
    df.filter(pl.col("fiscal_year") == 2025).write_parquet(uscis_dir / "hub_fy2025.parquet")
    return df


@pytest.fixture
def synthetic_oews(staging_dir):
    """Synthetic OEWS metro × SOC wage data."""
    oews_dir = staging_dir["staging"] / "bls" / "oews"
    oews_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        # DC + Economists
        {"cbsa_code": "47900", "cbsa_name": "DC", "soc_code": "19-3011", "soc_title": "Economists",
         "tot_emp": "5000", "oews_mean_wage": 130000.0, "oews_median_wage": 125000.0,
         "oews_p10": 75000.0, "oews_p25": 95000.0, "oews_p75": 160000.0, "oews_p90": 200000.0},
        # Seattle + Ops Research
        {"cbsa_code": "42660", "cbsa_name": "Seattle", "soc_code": "15-2031", "soc_title": "OR Analyst",
         "tot_emp": "8000", "oews_mean_wage": 140000.0, "oews_median_wage": 135000.0,
         "oews_p10": 85000.0, "oews_p25": 105000.0, "oews_p75": 170000.0, "oews_p90": 210000.0},
        # NYC + Management Analysts
        {"cbsa_code": "35620", "cbsa_name": "NYC", "soc_code": "13-1111", "soc_title": "Mgmt Analyst",
         "tot_emp": "60000", "oews_mean_wage": 105000.0, "oews_median_wage": 95000.0,
         "oews_p10": 55000.0, "oews_p25": 70000.0, "oews_p75": 130000.0, "oews_p90": 175000.0},
        # Baltimore + Economists
        {"cbsa_code": "12580", "cbsa_name": "Baltimore", "soc_code": "19-3011", "soc_title": "Economists",
         "tot_emp": "1200", "oews_mean_wage": 110000.0, "oews_median_wage": 105000.0,
         "oews_p10": 65000.0, "oews_p25": 80000.0, "oews_p75": 135000.0, "oews_p90": 170000.0},
    ]
    df = pl.DataFrame(rows)
    df.write_parquet(oews_dir / "oews_may2024_msa.parquet")
    return df
