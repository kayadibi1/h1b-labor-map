"""DOL OFLC LCA + PERM disclosure ingest.

Schema drifts year-to-year — we discover columns from real headers at ingest
time and persist a per-FY column mapper to /data/manifest/dol_column_mappers/.
Fails loudly when an expected logical column has no resolvable physical name.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from .common import (
    MANIFEST,
    RAW,
    STAGING,
    SourceEntry,
    load_sources_manifest,
    normalize_wage_to_annual,
    save_sources_manifest,
)

_log = logging.getLogger("h1b.ingest_dol")
MAPPERS_DIR = MANIFEST / "dol_column_mappers"


# Logical columns we require and the candidate physical-header regex patterns
# observed across DOL releases (FY2018–FY2025). Add more aliases as encountered.
LOGICAL_COLUMNS: dict[str, list[str]] = {
    "case_number": [r"^CASE_NUMBER$", r"^CASE_NO$"],
    "case_status": [r"^CASE_STATUS$", r"^STATUS$"],
    "decision_date": [r"^DECISION_DATE$", r"^DECISION_DT$"],
    "employer_name": [r"^EMPLOYER_NAME$", r"^EMPLOYER$"],
    "employer_city": [r"^EMPLOYER_CITY$"],
    "employer_state": [r"^EMPLOYER_STATE$", r"^EMPLOYER_STATE_PROVINCE$"],
    "naics_code": [r"^NAICS_CODE$", r"^NAIC_CODE$"],
    "job_title": [r"^JOB_TITLE$"],
    "soc_code": [r"^SOC_CODE$"],
    "soc_title": [r"^SOC_NAME$", r"^SOC_TITLE$"],
    "wage_rate_from": [r"^WAGE_RATE_OF_PAY_FROM$", r"^WAGE_RATE_FROM$"],
    "wage_rate_to": [r"^WAGE_RATE_OF_PAY_TO$", r"^WAGE_RATE_TO$"],
    "wage_unit_of_pay": [r"^WAGE_UNIT_OF_PAY$"],
    "pw_wage": [r"^PW_WAGE$", r"^PREVAILING_WAGE$"],
    "pw_unit_of_pay": [r"^PW_UNIT_OF_PAY$", r"^PW_WAGE_UNIT$"],
    "pw_wage_level": [r"^PW_WAGE_LEVEL$", r"^PW_LEVEL$", r"^WAGE_LEVEL$"],
    "worksite_city": [r"^WORKSITE_CITY$", r"^WORK_CITY$"],
    "worksite_state": [r"^WORKSITE_STATE$", r"^WORK_STATE$"],
    "full_time_position": [r"^FULL_TIME_POSITION$", r"^FULL_TIME$"],
}


REQUIRED_LOGICAL = {
    "case_number",
    "case_status",
    "decision_date",
    "employer_name",
    "employer_state",
    "soc_code",
    "wage_rate_from",
    "wage_unit_of_pay",
    "worksite_city",
    "worksite_state",
}

# pw_wage_level is "load-bearing but allowed missing for FY < ~2018"
PREFERRED_LOGICAL = {"pw_wage_level", "pw_wage", "naics_code", "soc_title", "job_title"}


@dataclass
class ColumnMapping:
    fiscal_year: int
    logical_to_physical: dict[str, str]
    missing_required: list[str]
    missing_preferred: list[str]


def build_mapping(headers: list[str], fiscal_year: int) -> ColumnMapping:
    """Map logical columns to actual physical headers via regex on uppercase."""
    upper = {h: h.upper().strip() for h in headers}
    inverse = {v: k for k, v in upper.items()}
    mapping: dict[str, str] = {}
    for logical, patterns in LOGICAL_COLUMNS.items():
        for pat in patterns:
            rx = re.compile(pat)
            match = next((h for h in inverse if rx.match(h)), None)
            if match is not None:
                mapping[logical] = inverse[match]
                break
    missing_required = sorted(REQUIRED_LOGICAL - set(mapping))
    missing_preferred = sorted(PREFERRED_LOGICAL - set(mapping))
    return ColumnMapping(
        fiscal_year=fiscal_year,
        logical_to_physical=mapping,
        missing_required=missing_required,
        missing_preferred=missing_preferred,
    )


def save_mapping(mapping: ColumnMapping) -> Path:
    MAPPERS_DIR.mkdir(parents=True, exist_ok=True)
    out = MAPPERS_DIR / f"fy{mapping.fiscal_year}.json"
    with out.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "fiscal_year": mapping.fiscal_year,
                "logical_to_physical": mapping.logical_to_physical,
                "missing_required": mapping.missing_required,
                "missing_preferred": mapping.missing_preferred,
            },
            f,
            indent=2,
            sort_keys=True,
        )
    return out


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _read_dol_excel(path: Path) -> pl.DataFrame:
    """Read a DOL xlsx file. xlsx engine: prefer openpyxl via pandas, then polars."""
    import pandas as pd

    pdf = pd.read_excel(path, dtype=str)
    pdf = pdf.fillna("")
    return pl.from_pandas(pdf)


def parse_lca_file(path: Path, fiscal_year: int) -> tuple[pl.DataFrame, ColumnMapping]:
    """Parse one DOL LCA xlsx file into a staging DataFrame keyed by logical names.

    Raises ValueError if required logical columns are missing — surfaces the
    unmatched header set to the caller for a decision.
    """
    df = _read_dol_excel(path)
    mapping = build_mapping(df.columns, fiscal_year)
    if mapping.missing_required:
        raise ValueError(
            f"DOL FY{fiscal_year} missing required columns: "
            f"{mapping.missing_required}. Headers seen: {sorted(df.columns)}"
        )
    save_mapping(mapping)

    # Project to logical column names + filter to CERTIFIED
    rename = {phys: log for log, phys in mapping.logical_to_physical.items()}
    df = df.rename(rename).select(list(mapping.logical_to_physical.keys()))

    # CERTIFIED filter
    df = df.filter(pl.col("case_status").str.to_uppercase() == "CERTIFIED")

    # Wage normalization to annual
    def _to_annual(val: str, unit: str) -> float | None:
        try:
            return normalize_wage_to_annual(float(val), unit) if val else None
        except (TypeError, ValueError):
            return None

    df = df.with_columns(
        [
            pl.struct(["wage_rate_from", "wage_unit_of_pay"])
            .map_elements(
                lambda s: _to_annual(s["wage_rate_from"], s["wage_unit_of_pay"]),
                return_dtype=pl.Float64,
            )
            .alias("wage_rate_annual"),
            pl.lit(fiscal_year, dtype=pl.Int32).alias("fiscal_year"),
            pl.col("decision_date").str.to_datetime(strict=False, format=None).alias(
                "decision_date_parsed"
            ),
        ]
    )

    if "pw_wage" in df.columns:
        df = df.with_columns(
            pl.struct(["pw_wage", "pw_unit_of_pay"])
            .map_elements(
                lambda s: _to_annual(s["pw_wage"], s.get("pw_unit_of_pay")),
                return_dtype=pl.Float64,
            )
            .alias("pw_wage_annual")
        )
    else:
        df = df.with_columns(pl.lit(None, dtype=pl.Float64).alias("pw_wage_annual"))

    # Clean wage level to digit 1-4 (DOL writes 'Level I' or 'I' or '1')
    if "pw_wage_level" in df.columns:
        df = df.with_columns(
            pl.col("pw_wage_level")
            .str.extract(r"([1-4IV]+)", 1)
            .str.replace_all("IV", "4")
            .str.replace_all("III", "3")
            .str.replace_all("II", "2")
            .str.replace_all("I", "1")
            .alias("pw_wage_level_digit")
        )
    else:
        df = df.with_columns(pl.lit(None, dtype=pl.String).alias("pw_wage_level_digit"))

    return df, mapping


def stage_dol_file(path: Path, fiscal_year: int, program: str = "LCA") -> Path:
    """Parse a DOL file and write it to /data/staging as parquet."""
    df, _mapping = parse_lca_file(path, fiscal_year)
    out_dir = STAGING / "dol" / program.lower()
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"fy{fiscal_year}.parquet"
    df.write_parquet(out)
    _log.info("staged %s rows -> %s", df.height, out)
    return out


# ---------------------------------------------------------------------------
# Discover live download URLs
# ---------------------------------------------------------------------------


def candidate_lca_urls(fiscal_years: list[int]) -> dict[int, list[str]]:
    """Resolved DOL LCA xlsx URLs by FY (verified 2026-05-27 by scraping the
    landing page at https://www.dol.gov/agencies/eta/foreign-labor/performance).

    Pattern is `LCA_Disclosure_Data_FY{YYYY}_Q4.xlsx` for full-FY files,
    `_Q2.xlsx` for mid-year. Current-FY (in progress) uses /media/ instead of
    /sites/dolgov/... and has a typo (`Dislclosure`).
    """
    out: dict[int, list[str]] = {}
    for fy in fiscal_years:
        if fy >= 2026:
            # Current/in-progress FY — try the /media/ path with the known typo
            out[fy] = [
                f"https://www.dol.gov/media/LCA_Dislclosure_Data_FY{fy}_Q2.xlsx",
                f"https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY{fy}_Q2.xlsx",
                f"https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY{fy}_Q4.xlsx",
            ]
        else:
            out[fy] = [
                f"https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY{fy}_Q4.xlsx",
                f"https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY{fy}.xlsx",
            ]
    return out


def candidate_perm_urls(fiscal_years: list[int]) -> dict[int, list[str]]:
    """Resolved DOL PERM xlsx URLs by FY (verified 2026-05-27)."""
    out: dict[int, list[str]] = {}
    for fy in fiscal_years:
        out[fy] = [
            f"https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/PERM_Disclosure_Data_FY{fy}_Q4.xlsx",
            f"https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/PERM_Disclosure_Data_FY{fy}.xlsx",
        ]
    return out


def discover_and_download(
    fiscal_years: list[int],
    *,
    force: bool = False,
    dry_run: bool = False,
) -> dict[int, Path | None]:
    """Try candidate URLs in order; cache to /data/raw/dol/lca/."""
    from .common import download_to

    manifest = load_sources_manifest()
    target_dir = RAW / "dol" / "lca"
    target_dir.mkdir(parents=True, exist_ok=True)
    candidates = candidate_lca_urls(fiscal_years)
    result: dict[int, Path | None] = {}

    for fy, urls in candidates.items():
        dest = target_dir / f"lca_fy{fy}.xlsx"
        if dry_run:
            _log.info("[dry-run] would try %d URLs for FY%d -> %s", len(urls), fy, dest)
            result[fy] = None
            continue
        chosen: SourceEntry | None = None
        for url in urls:
            try:
                chosen = download_to(
                    url,
                    dest,
                    name=f"dol_lca_fy{fy}",
                    manifest=manifest,
                    force=force,
                )
                break
            except Exception as exc:  # noqa: BLE001 — try the next URL
                _log.warning("FY%d candidate %s failed: %s", fy, url, exc)
        if chosen is None:
            _log.error("FY%d: no candidate URL worked — set manually in config.yaml", fy)
        result[fy] = dest if chosen else None

    save_sources_manifest(manifest)
    return result
