"""USCIS H-1B Employer Data Hub ingest.

The Hub publishes one CSV per fiscal year with per-employer counts:
  Initial Approvals, Initial Denials, Continuing Approvals, Continuing Denials,
  plus employer name, NAICS, city, state, ZIP, tax-id (recent years only).

Initial Approvals is the headline "new sponsorship" signal. Continuing is
renewal context — kept but never used in ranking.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import polars as pl

from .common import (
    RAW,
    STAGING,
    SourceEntry,
    download_to,
    load_sources_manifest,
    normalize_employer_name,
    save_sources_manifest,
)

_log = logging.getLogger("h1b.ingest_uscis")


# USCIS reports four counts per employer × FY. Header text drifts slightly
# year to year — we resolve via case-insensitive substring match.
_HEADER_RESOLUTIONS = {
    "fiscal_year": [r"fiscal\s*year"],
    "employer": [r"employer(?!\s*petition)"],
    "initial_approval": [r"initial\s*approval"],
    "initial_denial": [r"initial\s*denial"],
    "continuing_approval": [r"continuing\s*approval"],
    "continuing_denial": [r"continuing\s*denial"],
    "city": [r"^city$", r"petitioner\s*city"],
    "state": [r"^state$", r"petitioner\s*state"],
    "zip": [r"\bzip\b"],
    "naics_code": [r"naics"],
    "tax_id": [r"tax\s*id"],
}


def _resolve_header(headers: list[str], patterns: list[str]) -> str | None:
    for p in patterns:
        rx = re.compile(p, flags=re.IGNORECASE)
        for h in headers:
            if rx.search(h):
                return h
    return None


def parse_uscis_hub_csv(path: Path, fiscal_year: int | None = None) -> pl.DataFrame:
    """Parse a USCIS Employer Data Hub CSV/xlsx file into normalized columns.

    Returns one row per (employer × FY) with the four count columns + meta.
    """
    if path.suffix.lower() in {".xlsx", ".xls"}:
        import pandas as pd

        pdf = pd.read_excel(path, dtype=str).fillna("")
        df = pl.from_pandas(pdf)
    else:
        df = pl.read_csv(path, infer_schema_length=10_000, ignore_errors=True)

    # Header resolution
    resolved: dict[str, str] = {}
    for logical, patterns in _HEADER_RESOLUTIONS.items():
        h = _resolve_header(list(df.columns), patterns)
        if h is not None:
            resolved[logical] = h

    missing = {"employer", "initial_approval", "initial_denial"} - set(resolved)
    if missing:
        raise ValueError(
            f"USCIS Hub file missing required columns {missing}; "
            f"headers seen: {list(df.columns)}"
        )

    # Project + rename
    out = df.select([pl.col(resolved[k]).alias(k) for k in resolved])
    # Coerce count columns to integers (strings like "1,234" appear)
    for cnt_col in ("initial_approval", "initial_denial", "continuing_approval", "continuing_denial"):
        if cnt_col in out.columns:
            out = out.with_columns(
                pl.col(cnt_col)
                .cast(pl.String)
                .str.replace_all(",", "")
                .str.strip_chars()
                .cast(pl.Int64, strict=False)
                .alias(cnt_col)
            )
        else:
            out = out.with_columns(pl.lit(0, dtype=pl.Int64).alias(cnt_col))

    # Derive fiscal_year if column absent and caller provided one
    if "fiscal_year" not in out.columns and fiscal_year is not None:
        out = out.with_columns(pl.lit(fiscal_year, dtype=pl.Int32).alias("fiscal_year"))
    elif "fiscal_year" in out.columns:
        out = out.with_columns(
            pl.col("fiscal_year").cast(pl.String).str.extract(r"(\d{4})", 1).cast(pl.Int32)
        )

    # Compute initial_approval_rate (denominator-safe)
    out = out.with_columns(
        (
            pl.when((pl.col("initial_approval") + pl.col("initial_denial")) > 0)
            .then(pl.col("initial_approval") / (pl.col("initial_approval") + pl.col("initial_denial")))
            .otherwise(None)
        ).alias("initial_approval_rate")
    )

    # Normalized employer name for downstream matching
    out = out.with_columns(
        pl.col("employer")
        .map_elements(normalize_employer_name, return_dtype=pl.String)
        .alias("employer_norm")
    )

    return out


def stage_uscis_file(path: Path, fiscal_year: int | None = None) -> Path:
    df = parse_uscis_hub_csv(path, fiscal_year=fiscal_year)
    fy = fiscal_year or (df["fiscal_year"].max() if "fiscal_year" in df.columns else "unknown")
    out_dir = STAGING / "uscis"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"hub_fy{fy}.parquet"
    df.write_parquet(out)
    _log.info("staged %s USCIS Hub rows -> %s", df.height, out)
    return out


# ---------------------------------------------------------------------------
# Download discovery
# ---------------------------------------------------------------------------


def candidate_hub_urls(fiscal_years: list[int]) -> dict[int, list[str]]:
    """USCIS Hub file URLs by FY. URLs are mostly published under:

        https://www.uscis.gov/sites/default/files/document/data/h1b_datahubexport-{fy}.csv

    Some years use .xlsx. We try both.
    """
    out: dict[int, list[str]] = {}
    for fy in fiscal_years:
        out[fy] = [
            f"https://www.uscis.gov/sites/default/files/document/data/h1b_datahubexport-{fy}.csv",
            f"https://www.uscis.gov/sites/default/files/document/data/h1b_datahubexport-{fy}.xlsx",
        ]
    return out


def discover_and_download(
    fiscal_years: list[int],
    *,
    force: bool = False,
    dry_run: bool = False,
) -> dict[int, Path | None]:
    manifest = load_sources_manifest()
    target_dir = RAW / "uscis" / "employer_hub"
    target_dir.mkdir(parents=True, exist_ok=True)
    cand = candidate_hub_urls(fiscal_years)
    result: dict[int, Path | None] = {}
    for fy, urls in cand.items():
        if dry_run:
            _log.info("[dry-run] would try USCIS Hub URLs for FY%d", fy)
            result[fy] = None
            continue
        chosen: SourceEntry | None = None
        for url in urls:
            ext = url.rsplit(".", 1)[-1]
            dest = target_dir / f"hub_fy{fy}.{ext}"
            try:
                chosen = download_to(
                    url,
                    dest,
                    name=f"uscis_hub_fy{fy}",
                    manifest=manifest,
                    force=force,
                )
                result[fy] = dest
                break
            except Exception as exc:  # noqa: BLE001 — try the next URL
                _log.warning("FY%d USCIS candidate %s failed: %s", fy, url, exc)
        if chosen is None:
            _log.error("FY%d USCIS: no candidate URL worked", fy)
            result[fy] = None
    save_sources_manifest(manifest)
    return result
