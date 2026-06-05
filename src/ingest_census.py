"""Census Bureau gazetteer + OMB CBSA delineation ingest.

Output:
  /data/staging/geo/place_to_cbsa.parquet  (city,state -> CBSA code)
  /data/staging/geo/cbsa_names.parquet     (CBSA code -> canonical name)

The CBSA delineation file is the authoritative county -> CBSA mapping. The
gazetteer contains places (cities + CDPs) with FIPS county. We join them to
produce a city/state -> CBSA crosswalk used by `geo_normalize.py`.
"""

from __future__ import annotations

import logging
from pathlib import Path

import polars as pl

from .common import (
    RAW,
    STAGING,
    download_to,
    load_sources_manifest,
    save_sources_manifest,
)

_log = logging.getLogger("h1b.ingest_census")

# OMB Bulletin 23-01 delineation (Census-hosted Excel). Stable URL as of 2026-05-27:
CBSA_DELINEATION_URL = (
    "https://www2.census.gov/programs-surveys/metro-micro/geographies/reference-files/2023/"
    "delineation-files/list1_2023.xlsx"
)

# Census gazetteer (places) — 2023 release
GAZETTEER_PLACES_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/2023_Gaz_place_national.zip"
)


def download_cbsa(*, force: bool = False, dry_run: bool = False) -> Path | None:
    if dry_run:
        _log.info("[dry-run] would download OMB CBSA delineation file")
        return None
    manifest = load_sources_manifest()
    target = RAW / "census" / "cbsa_delineation_2023.xlsx"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        download_to(
            CBSA_DELINEATION_URL,
            target,
            name="census_cbsa_delineation_2023",
            manifest=manifest,
            force=force,
        )
        save_sources_manifest(manifest)
        return target
    except Exception as exc:  # noqa: BLE001
        _log.error("CBSA delineation download failed: %s", exc)
        return None


def parse_cbsa(path: Path) -> pl.DataFrame:
    """Parse the OMB list1 delineation file -> CBSA county/code mapping.

    The file has a banner ("Table with row headers...") followed by the real
    header on row 3 (0-indexed: skiprows=2). Verified 2026-05-27.
    """
    import pandas as pd

    pdf = pd.read_excel(path, dtype=str, skiprows=2).fillna("")
    if not any("CBSA" in str(c).upper() for c in pdf.columns):
        # Header didn't land where we expected — try other offsets defensively
        for skip in (1, 3, 4):
            try:
                attempt = pd.read_excel(path, dtype=str, skiprows=skip).fillna("")
                if any("CBSA" in str(c).upper() for c in attempt.columns):
                    pdf = attempt
                    break
            except Exception:  # noqa: BLE001
                continue
    df = pl.from_pandas(pdf)
    upper = {c: str(c).upper().strip() for c in df.columns}
    rename: dict[str, str] = {}
    for c, u in upper.items():
        if u.startswith("CBSA CODE"):
            rename[c] = "cbsa_code"
        elif u.startswith("CBSA TITLE"):
            rename[c] = "cbsa_name"
        elif u.startswith("FIPS STATE"):
            rename[c] = "state_fips"
        elif u.startswith("FIPS COUNTY"):
            rename[c] = "county_fips"
        elif u.startswith("COUNTY/COUNTY EQUIVALENT"):
            rename[c] = "county_name"
        elif u.startswith("STATE NAME"):
            rename[c] = "state_name"
        elif u.startswith("METROPOLITAN/MICROPOLITAN"):
            rename[c] = "cbsa_type"
    df = df.rename(rename)
    keep = [
        c for c in ("cbsa_code", "cbsa_name", "cbsa_type", "state_fips", "county_fips", "county_name", "state_name")
        if c in df.columns
    ]
    df = df.select(keep)
    if "cbsa_code" in df.columns:
        df = df.filter(pl.col("cbsa_code").str.len_chars() > 0)
    return df


def stage_cbsa(path: Path) -> Path:
    df = parse_cbsa(path)
    out_dir = STAGING / "geo"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "cbsa_county_2023.parquet"
    df.write_parquet(out)
    _log.info("staged %s CBSA-county rows -> %s", df.height, out)
    return out
