"""BLS ingest — JOLTS (demand), CES (employment), OEWS (wages by SOC×metro),
Employment Projections (10-yr SOC growth).

OEWS + Projections are downloads (xlsx); JOLTS/CES go through the API v2.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import polars as pl
import requests

from .common import (
    RAW,
    STAGING,
    download_to,
    load_sources_manifest,
    save_sources_manifest,
)

_log = logging.getLogger("h1b.ingest_bls")

BLS_API_BASE = "https://api.bls.gov/publicAPI/v2/timeseries/data/"


def _api_key() -> str | None:
    return os.getenv("BLS_API_KEY") or None


def bls_timeseries(
    series_ids: list[str],
    start_year: int,
    end_year: int,
    *,
    annual_average: bool = False,
) -> dict:
    """POST to BLS API v2. Returns parsed JSON."""
    headers = {"Content-Type": "application/json"}
    payload: dict[str, object] = {
        "seriesid": series_ids,
        "startyear": str(start_year),
        "endyear": str(end_year),
        "annualaverage": annual_average,
    }
    key = _api_key()
    if key:
        payload["registrationkey"] = key
    resp = requests.post(BLS_API_BASE, data=json.dumps(payload), headers=headers, timeout=60)
    resp.raise_for_status()
    j = resp.json()
    if j.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS API error: {j.get('message')}")
    return j


def fetch_jolts_by_supersector(
    supersectors: list[str], start_year: int, end_year: int
) -> pl.DataFrame:
    """Pull JOLTS openings/hires/quits/levels by supersector.

    JOLTS series codes: JTU<supersector><state>00<data_type>L.
    For national totals use state='00'. Data type codes: 'JO'=openings,
    'HI'=hires, 'TS'=total separations, 'QU'=quits, 'LD'=layoffs/discharges.
    """
    series = []
    for ss in supersectors:
        for dt in ("JO", "HI", "QU", "LD"):
            series.append(f"JTU{ss}000000000{dt}L")
    j = bls_timeseries(series, start_year, end_year)
    rows: list[dict] = []
    for s in j["Results"]["series"]:
        for d in s["data"]:
            rows.append(
                {
                    "series_id": s["seriesID"],
                    "year": int(d["year"]),
                    "period": d["period"],
                    "value": float(d["value"]) if d.get("value") not in (None, "") else None,
                }
            )
    return pl.DataFrame(rows)


# ---------------------------------------------------------------------------
# OEWS download (annual xlsx, by SOC × metro)
# ---------------------------------------------------------------------------


def candidate_oews_urls(year: int) -> list[str]:
    """OEWS metro file URLs follow the May{YYYY} convention.

    Example (May 2024 release): https://www.bls.gov/oes/special.requests/oesm24ma.zip
    """
    yy = str(year)[-2:]
    return [
        f"https://www.bls.gov/oes/special.requests/oesm{yy}ma.zip",
        f"https://www.bls.gov/oes/{year}/may/oesm{yy}ma.zip",
    ]


def download_oews(year: int, *, force: bool = False, dry_run: bool = False) -> Path | None:
    manifest = load_sources_manifest()
    target_dir = RAW / "bls" / "oews"
    target_dir.mkdir(parents=True, exist_ok=True)
    if dry_run:
        _log.info("[dry-run] would download OEWS May%s metro file", year)
        return None
    for url in candidate_oews_urls(year):
        dest = target_dir / f"oewsm{year}ma.zip"
        try:
            download_to(url, dest, name=f"bls_oews_may{year}", manifest=manifest, force=force)
            save_sources_manifest(manifest)
            return dest
        except Exception as exc:  # noqa: BLE001
            _log.warning("OEWS candidate %s failed: %s", url, exc)
    _log.error("OEWS download failed for May %s — set URL manually in config.yaml", year)
    return None


def parse_oews_metro_zip(path: Path) -> pl.DataFrame:
    """Read the metro xlsx out of the OEWS zip and return SOC × metro wages."""
    import io
    import zipfile

    import pandas as pd

    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".xlsx")]
        if not names:
            raise FileNotFoundError(f"no xlsx in OEWS zip {path}")
        # pick MSA-level file ('MSA' or 'metro' in name)
        candidates = [n for n in names if "msa" in n.lower() or "metro" in n.lower()]
        chosen = candidates[0] if candidates else names[0]
        with zf.open(chosen) as fh:
            data = fh.read()
    pdf = pd.read_excel(io.BytesIO(data), dtype=str).fillna("")
    df = pl.from_pandas(pdf)
    # OEWS metro headers (case-insensitive): AREA, AREA_TITLE, OCC_CODE, OCC_TITLE,
    # TOT_EMP, A_MEAN, A_MEDIAN, A_PCT10, A_PCT25, A_PCT75, A_PCT90
    rename = {}
    upper = {h: h.upper() for h in df.columns}
    for h, u in upper.items():
        if u in {"AREA"}:
            rename[h] = "cbsa_code"
        elif u in {"AREA_TITLE"}:
            rename[h] = "cbsa_name"
        elif u in {"OCC_CODE"}:
            rename[h] = "soc_code"
        elif u in {"OCC_TITLE"}:
            rename[h] = "soc_title"
        elif u in {"A_MEAN"}:
            rename[h] = "oews_mean_wage"
        elif u in {"A_MEDIAN"}:
            rename[h] = "oews_median_wage"
        elif u in {"A_PCT10"}:
            rename[h] = "oews_p10"
        elif u in {"A_PCT25"}:
            rename[h] = "oews_p25"
        elif u in {"A_PCT75"}:
            rename[h] = "oews_p75"
        elif u in {"A_PCT90"}:
            rename[h] = "oews_p90"
        elif u in {"TOT_EMP"}:
            rename[h] = "tot_emp"
    df = df.rename(rename)

    keep = [
        c
        for c in (
            "cbsa_code",
            "cbsa_name",
            "soc_code",
            "soc_title",
            "tot_emp",
            "oews_mean_wage",
            "oews_median_wage",
            "oews_p10",
            "oews_p25",
            "oews_p75",
            "oews_p90",
        )
        if c in df.columns
    ]
    df = df.select(keep)

    for c in ("oews_mean_wage", "oews_median_wage", "oews_p10", "oews_p25", "oews_p75", "oews_p90"):
        if c in df.columns:
            df = df.with_columns(
                pl.col(c)
                .cast(pl.String)
                .str.replace_all(",", "")
                .str.replace_all(r"\*+", "")
                .str.strip_chars()
                .cast(pl.Float64, strict=False)
                .alias(c)
            )

    return df


def stage_oews(path: Path, year: int) -> Path:
    df = parse_oews_metro_zip(path)
    out_dir = STAGING / "bls" / "oews"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"oews_may{year}_msa.parquet"
    df.write_parquet(out)
    _log.info("staged %s OEWS rows -> %s", df.height, out)
    return out
