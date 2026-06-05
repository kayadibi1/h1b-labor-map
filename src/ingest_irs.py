"""IRS / ProPublica Nonprofit Explorer ingest — cap-exempt subcategory data.

Strategy:
1. For employers we want to check, hit ProPublica's Nonprofit Explorer API
   (no key required, but rate-limited; respect ~0.5 req/s).
2. Capture 501(c) status, NTEE code, and free-form `name` for confidence
   scoring in entity_resolve / cap_exempt.

For high-volume runs, prefer IRS Form 990 bulk data dumps. This module starts
with ProPublica because it requires no setup; bulk-data loader can be added
as the project scales.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import polars as pl

from .common import RAW, STAGING, http_get, normalize_employer_name

_log = logging.getLogger("h1b.ingest_irs")

PP_BASE = "https://projects.propublica.org/nonprofits/api/v2"


def search_propublica(query: str, *, sleep_s: float = 0.6) -> list[dict]:
    """Search the ProPublica Nonprofit Explorer for an org name.

    Returns a list of candidate matches with at minimum:
        ein, name, ntee_code, subsection_code, state, city.
    """
    time.sleep(sleep_s)
    url = f"{PP_BASE}/search.json?q={requests_quote(query)}"
    r = http_get(url)
    if r.status_code != 200:
        return []
    j = r.json()
    return j.get("organizations", [])


def get_organization(ein: int, *, sleep_s: float = 0.6) -> dict | None:
    time.sleep(sleep_s)
    url = f"{PP_BASE}/organizations/{ein}.json"
    r = http_get(url)
    if r.status_code != 200:
        return None
    return r.json().get("organization")


def requests_quote(s: str) -> str:
    from urllib.parse import quote

    return quote(s)


def lookup_employers(names: list[str], *, sleep_s: float = 0.6) -> pl.DataFrame:
    """Look up a list of normalized employer names; return enrichment frame.

    Output columns:
        employer_norm, propublica_ein, propublica_name, ntee_code,
        subsection_code, state, city, propublica_confidence.
    """
    out: list[dict] = []
    for n in names:
        if not n:
            continue
        try:
            candidates = search_propublica(n, sleep_s=sleep_s)
        except Exception as exc:  # noqa: BLE001
            _log.warning("ProPublica search failed for %s: %s", n, exc)
            continue
        if not candidates:
            out.append({"employer_norm": n, "propublica_ein": None})
            continue
        top = candidates[0]
        top_norm = normalize_employer_name(top.get("name", ""))
        confidence = "HIGH" if top_norm == n else ("MEDIUM" if top_norm.startswith(n[:10]) else "LOW")
        out.append(
            {
                "employer_norm": n,
                "propublica_ein": top.get("ein"),
                "propublica_name": top.get("name"),
                "ntee_code": top.get("ntee_code"),
                "subsection_code": top.get("subsection_code"),  # 3 = 501(c)(3)
                "state": top.get("state"),
                "city": top.get("city"),
                "propublica_confidence": confidence,
            }
        )
    df = pl.DataFrame(out) if out else pl.DataFrame()
    if df.height:
        out_dir = STAGING / "irs"
        out_dir.mkdir(parents=True, exist_ok=True)
        df.write_parquet(out_dir / "propublica_lookups.parquet")
    return df
