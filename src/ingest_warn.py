"""WARN Act notices ingest (replaces Layoffs.fyi as primary layoff signal).

Each state has its own portal. Many are scrape-only. We provide per-state
adapters for the top 10 H-1B states + DC. Each adapter returns a polars
DataFrame with: state, employer_raw, employer_norm, notice_date,
effective_date, positions_affected, location.

State portals change layouts; adapters are best-effort and intentionally
graceful — failures log and skip rather than crash the pipeline.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from typing import Callable

import polars as pl
import requests
from bs4 import BeautifulSoup

from .common import (
    RAW,
    STAGING,
    download_to,
    load_sources_manifest,
    normalize_employer_name,
    save_sources_manifest,
)

_log = logging.getLogger("h1b.ingest_warn")


_DATE_PATTERNS = [
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%B %d, %Y",
    "%b %d, %Y",
]


def _parse_date(s: str) -> date | None:
    if not s:
        return None
    s = s.strip()
    from datetime import datetime as dt

    for fmt in _DATE_PATTERNS:
        try:
            return dt.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_int(s: str) -> int | None:
    if not s:
        return None
    m = re.search(r"\d+", s.replace(",", ""))
    return int(m.group()) if m else None


# ---------------------------------------------------------------------------
# Per-state HTML scraping adapters (best-effort; layouts drift)
# ---------------------------------------------------------------------------


def _fetch_html(url: str) -> str | None:
    try:
        from .common import http_get

        r = http_get(url, timeout=60)
        if r.status_code == 200:
            return r.text
    except Exception as exc:  # noqa: BLE001
        _log.warning("WARN fetch failed: %s — %s", url, exc)
    return None


def scrape_warn_generic_table(
    html: str,
    state_code: str,
    *,
    column_map: dict[str, str],
) -> list[dict]:
    """Generic HTML table scraper. `column_map` maps logical -> header substring.

    Logical keys: employer, notice_date, effective_date, positions, location.
    """
    soup = BeautifulSoup(html, "lxml")
    out: list[dict] = []
    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        if not headers:
            continue
        idx: dict[str, int] = {}
        for logical, needle in column_map.items():
            for i, h in enumerate(headers):
                if needle.lower() in h:
                    idx[logical] = i
                    break
        if "employer" not in idx:
            continue
        for tr in table.find_all("tr")[1:]:
            tds = [td.get_text(strip=True) for td in tr.find_all("td")]
            if not tds:
                continue
            row = {
                "state": state_code,
                "employer_raw": tds[idx["employer"]] if idx.get("employer") is not None and idx["employer"] < len(tds) else None,
                "notice_date": _parse_date(tds[idx["notice_date"]]) if idx.get("notice_date") is not None and idx["notice_date"] < len(tds) else None,
                "effective_date": _parse_date(tds[idx["effective_date"]]) if idx.get("effective_date") is not None and idx["effective_date"] < len(tds) else None,
                "positions_affected": _parse_int(tds[idx["positions"]]) if idx.get("positions") is not None and idx["positions"] < len(tds) else None,
                "location": tds[idx["location"]] if idx.get("location") is not None and idx["location"] < len(tds) else None,
            }
            row["employer_norm"] = normalize_employer_name(row["employer_raw"])
            out.append(row)
    return out


STATE_ADAPTERS: dict[str, tuple[str, Callable[[str], list[dict]]]] = {
    "NY": (
        "https://dol.ny.gov/warn-notices",
        lambda html: scrape_warn_generic_table(
            html,
            "NY",
            column_map={
                "employer": "company",
                "notice_date": "notice date",
                "effective_date": "effective",
                "positions": "affected",
                "location": "county",
            },
        ),
    ),
    "MA": (
        "https://www.mass.gov/lists/warn-notices",
        lambda html: scrape_warn_generic_table(
            html,
            "MA",
            column_map={
                "employer": "employer",
                "notice_date": "notice date",
                "effective_date": "effective",
                "positions": "affected",
                "location": "location",
            },
        ),
    ),
    "VA": (
        "https://www.vec.virginia.gov/warn-notices",
        lambda html: scrape_warn_generic_table(
            html,
            "VA",
            column_map={
                "employer": "employer",
                "notice_date": "notice",
                "effective_date": "effective",
                "positions": "employees",
                "location": "city",
            },
        ),
    ),
    "DC": (
        "https://does.dc.gov/page/warn-notifications",
        lambda html: scrape_warn_generic_table(
            html,
            "DC",
            column_map={
                "employer": "employer",
                "notice_date": "notice date",
                "effective_date": "effective",
                "positions": "affected",
                "location": "location",
            },
        ),
    ),
    # CA, TX, WA, NJ, IL, FL, GA have JS-rendered portals or PDF dumps.
    # Placeholders that try the landing page but most-likely yield nothing
    # without per-state custom logic — review CSV captures the gap.
}


def ingest_warn(states: list[str] | None = None, *, dry_run: bool = False) -> pl.DataFrame | None:
    """Run all configured state adapters and return a unified DataFrame."""
    if dry_run:
        _log.info("[dry-run] would scrape WARN portals: %s", states or list(STATE_ADAPTERS))
        return None
    states = states or list(STATE_ADAPTERS)
    rows: list[dict] = []
    for st in states:
        adapter = STATE_ADAPTERS.get(st)
        if not adapter:
            _log.info("no WARN adapter for state %s — skipping", st)
            continue
        url, parser = adapter
        html = _fetch_html(url)
        if not html:
            continue
        try:
            new_rows = parser(html)
        except Exception as exc:  # noqa: BLE001
            _log.warning("WARN parser for %s failed: %s", st, exc)
            new_rows = []
        _log.info("WARN %s: %d rows", st, len(new_rows))
        rows.extend(new_rows)

    if not rows:
        return pl.DataFrame()
    df = pl.DataFrame(rows)
    out_dir = STAGING / "warn"
    out_dir.mkdir(parents=True, exist_ok=True)
    df.write_parquet(out_dir / "warn_recent.parquet")
    return df
