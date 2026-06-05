"""SEC EDGAR ingest — public-company parent CIK lookup for entity resolution.

We download the public `company_tickers.json` file (no auth) which gives us
CIK -> ticker + company name. We then use these for parent-name canonicalization
when the legal-entity is publicly traded.
"""

from __future__ import annotations

import logging
from pathlib import Path

import polars as pl
import requests

from .common import RAW, STAGING, http_get, normalize_employer_name

_log = logging.getLogger("h1b.ingest_edgar")

EDGAR_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


def download_edgar(*, force: bool = False, dry_run: bool = False) -> Path | None:
    if dry_run:
        _log.info("[dry-run] would download EDGAR company tickers")
        return None
    target = RAW / "edgar" / "company_tickers.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = http_get(EDGAR_TICKERS_URL)
        if r.status_code != 200:
            _log.error("EDGAR download failed with %d", r.status_code)
            return None
        target.write_bytes(r.content)
        return target
    except Exception as exc:  # noqa: BLE001
        _log.error("EDGAR download error: %s", exc)
        return None


def parse_edgar(path: Path) -> pl.DataFrame:
    import json

    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    rows = []
    for _k, v in raw.items():
        rows.append(
            {
                "cik": int(v["cik_str"]),
                "ticker": v.get("ticker"),
                "title": v.get("title"),
                "employer_norm": normalize_employer_name(v.get("title", "")),
            }
        )
    df = pl.DataFrame(rows)
    out_dir = STAGING / "edgar"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "company_tickers.parquet"
    df.write_parquet(out)
    _log.info("staged %s EDGAR companies -> %s", df.height, out)
    return df
