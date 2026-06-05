"""DuckDB-driven join of staged sources into the mart fact table.

Output: /data/marts/mart_fact.parquet — one row per
(employer_group x soc x cbsa x window).
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb
import polars as pl

from .common import MARTS, STAGING

_log = logging.getLogger("h1b.join")


def _window_label(fy: int, post_fy: int) -> str:
    return "FY2025+" if fy >= post_fy else "FY2022-FY2024"


def build_mart(
    *,
    regime_post_fy: int = 2025,
    out_path: Path | None = None,
) -> Path:
    """Build the mart fact table from /data/staging parquet files.

    Inputs expected (any missing => degrade gracefully with NULL columns):
      /data/staging/dol/lca/fy{YYYY}.parquet
      /data/staging/uscis/hub_fy{YYYY}.parquet
      /data/staging/bls/oews/oews_may{YYYY}_msa.parquet
    """
    con = duckdb.connect()

    dol_glob = str((STAGING / "dol" / "lca" / "*.parquet").as_posix())
    uscis_glob = str((STAGING / "uscis" / "*.parquet").as_posix())
    oews_glob = str((STAGING / "bls" / "oews" / "*.parquet").as_posix())

    # Resolve glob existence
    dol_files = sorted((STAGING / "dol" / "lca").glob("*.parquet"))
    uscis_files = sorted((STAGING / "uscis").glob("*.parquet"))
    oews_files = sorted((STAGING / "bls" / "oews").glob("*.parquet"))

    if not dol_files:
        raise FileNotFoundError("No DOL LCA staging files found — run ingest_dol first")

    # ---- LCA aggregation: employer × SOC × CBSA × window ----------------
    con.execute(
        f"""
        CREATE TEMP VIEW lca_raw AS
        SELECT *,
               CASE WHEN fiscal_year >= {regime_post_fy}
                    THEN 'FY{regime_post_fy}+'
                    ELSE 'pre-FY{regime_post_fy}'
               END AS window_label
        FROM read_parquet('{dol_glob}', union_by_name=true)
        WHERE wage_rate_annual IS NOT NULL
        """
    )

    # Inspect lca_raw columns to decide which enrichment fields survived ingest
    raw_cols = {r[0] for r in con.execute("DESCRIBE lca_raw").fetchall()}
    ce_sub_expr = (
        "COALESCE(MAX(cap_exempt_subcategory), 'NONE')"
        if "cap_exempt_subcategory" in raw_cols
        else "'NONE'"
    )
    ce_conf_expr = (
        "COALESCE(MAX(cap_exempt_confidence), 'HIGH')"
        if "cap_exempt_confidence" in raw_cols
        else "'HIGH'"
    )

    con.execute(
        f"""
        CREATE TEMP VIEW lca_agg AS
        SELECT
            employer_name,
            employer_norm,
            employer_group,
            cbsa_code,
            soc_code,
            COALESCE(MAX(soc_title), 'Unknown') AS soc_title,
            COALESCE(MAX(naics_code), '')      AS naics_code,
            {ce_sub_expr} AS cap_exempt_subcategory,
            {ce_conf_expr} AS cap_exempt_confidence,
            window_label,
            COUNT(*) AS lca_filings_window,
            APPROX_QUANTILE(wage_rate_annual, 0.5) AS median_wage_filed,
            COUNT(*) FILTER (WHERE pw_wage_level_digit = '1')::DOUBLE / NULLIF(COUNT(*),0) AS pct_level_1,
            COUNT(*) FILTER (WHERE pw_wage_level_digit = '2')::DOUBLE / NULLIF(COUNT(*),0) AS pct_level_2,
            COUNT(*) FILTER (WHERE pw_wage_level_digit = '3')::DOUBLE / NULLIF(COUNT(*),0) AS pct_level_3,
            COUNT(*) FILTER (WHERE pw_wage_level_digit = '4')::DOUBLE / NULLIF(COUNT(*),0) AS pct_level_4
        FROM lca_raw
        WHERE employer_norm IS NOT NULL AND employer_norm <> ''
        GROUP BY employer_name, employer_norm, employer_group, cbsa_code,
                 soc_code, window_label
        """
    )

    # ---- USCIS Hub aggregation: employer × window -----------------------
    if uscis_files:
        con.execute(
            f"""
            CREATE TEMP VIEW uscis_raw AS
            SELECT *,
                   CASE WHEN fiscal_year >= {regime_post_fy}
                        THEN 'FY{regime_post_fy}+'
                        ELSE 'pre-FY{regime_post_fy}'
                   END AS window_label
            FROM read_parquet('{uscis_glob}', union_by_name=true)
            """
        )
        con.execute(
            """
            CREATE TEMP VIEW uscis_agg AS
            SELECT
                employer_norm,
                window_label,
                SUM(initial_approval)   AS uscis_initial_approvals_window,
                SUM(initial_denial)     AS uscis_initial_denials_window,
                SUM(continuing_approval) AS uscis_continuing_approvals_window,
                CASE WHEN SUM(initial_approval + initial_denial) > 0
                     THEN SUM(initial_approval)::DOUBLE / SUM(initial_approval + initial_denial)
                     ELSE NULL
                END AS initial_approval_rate
            FROM uscis_raw
            WHERE employer_norm IS NOT NULL AND employer_norm <> ''
            GROUP BY employer_norm, window_label
            """
        )
    else:
        _log.warning("No USCIS Hub files staged — proceeding without approval data")
        con.execute(
            """
            CREATE TEMP VIEW uscis_agg AS
            SELECT NULL::VARCHAR AS employer_norm,
                   NULL::VARCHAR AS window_label,
                   NULL::BIGINT  AS uscis_initial_approvals_window,
                   NULL::BIGINT  AS uscis_initial_denials_window,
                   NULL::BIGINT  AS uscis_continuing_approvals_window,
                   NULL::DOUBLE  AS initial_approval_rate
            WHERE false
            """
        )

    # ---- OEWS join: SOC × CBSA -----------------------------------------
    if oews_files:
        con.execute(
            f"""
            CREATE TEMP VIEW oews AS
            SELECT
                cbsa_code,
                soc_code,
                CAST(oews_median_wage AS DOUBLE) AS oews_median_wage,
                CAST(oews_p10 AS DOUBLE) AS oews_p10,
                CAST(oews_p25 AS DOUBLE) AS oews_p25,
                CAST(oews_p75 AS DOUBLE) AS oews_p75
            FROM read_parquet('{oews_glob}', union_by_name=true)
            """
        )
    else:
        _log.warning("No OEWS files staged — wage_gap_within_level will be NULL")
        con.execute(
            """
            CREATE TEMP VIEW oews AS
            SELECT NULL::VARCHAR AS cbsa_code,
                   NULL::VARCHAR AS soc_code,
                   NULL::DOUBLE AS oews_median_wage,
                   NULL::DOUBLE AS oews_p10,
                   NULL::DOUBLE AS oews_p25,
                   NULL::DOUBLE AS oews_p75
            WHERE false
            """
        )

    # ---- Final join ----------------------------------------------------
    con.execute(
        """
        CREATE TEMP VIEW mart_fact AS
        SELECT
            l.employer_name,
            l.employer_norm,
            l.employer_group,
            l.cbsa_code,
            l.soc_code,
            l.soc_title,
            l.naics_code,
            l.cap_exempt_subcategory,
            l.cap_exempt_confidence,
            l.window_label,
            l.lca_filings_window,
            l.median_wage_filed,
            l.pct_level_1, l.pct_level_2, l.pct_level_3, l.pct_level_4,
            u.uscis_initial_approvals_window,
            u.uscis_initial_denials_window,
            u.uscis_continuing_approvals_window,
            u.initial_approval_rate,
            o.oews_median_wage,
            o.oews_p10, o.oews_p25, o.oews_p75,
            -- Within-level wage gap proxy: pct_level_1 weighted toward p10, etc.
            (l.median_wage_filed - o.oews_median_wage) AS wage_gap_gross
        FROM lca_agg l
        LEFT JOIN uscis_agg u
          ON u.employer_norm = l.employer_norm
         AND u.window_label  = l.window_label
        LEFT JOIN oews o
          ON o.cbsa_code = l.cbsa_code
         AND o.soc_code  = l.soc_code
        """
    )

    out = out_path or (MARTS / "mart_fact.parquet")
    out.parent.mkdir(parents=True, exist_ok=True)
    df = con.execute("SELECT * FROM mart_fact").pl()

    df.write_parquet(out)
    _log.info("mart_fact: %s rows -> %s", df.height, out)
    return out
