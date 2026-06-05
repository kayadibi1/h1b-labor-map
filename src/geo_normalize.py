"""Geographic normalization: messy worksite strings -> CBSA code.

LCA worksite columns are messy ("Wash. DC", "Washington, District of Columbia",
"Arlington, VA"). We use the Census/OMB delineation crosswalk + a curated
city->CBSA shortcut table for the most common metros.

For unmatched localities we log to /data/manifest/geo_review.csv so the user
can curate.
"""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path

import polars as pl

from .common import MANIFEST, STAGING

_log = logging.getLogger("h1b.geo_normalize")

GEO_REVIEW_CSV = MANIFEST / "geo_review.csv"

# Curated city/state -> CBSA shortcuts for the top SAIS-target metros.
# Expand via `geo_review.csv` decisions in subsequent runs.
CITY_STATE_CBSA: dict[tuple[str, str], str] = {
    # DC metro (47900)
    ("WASHINGTON", "DC"): "47900",
    ("WASHINGTON", "DISTRICT OF COLUMBIA"): "47900",
    ("ARLINGTON", "VA"): "47900",
    ("ALEXANDRIA", "VA"): "47900",
    ("BETHESDA", "MD"): "47900",
    ("ROCKVILLE", "MD"): "47900",
    ("RESTON", "VA"): "47900",
    ("MCLEAN", "VA"): "47900",
    ("TYSONS", "VA"): "47900",
    ("TYSONS CORNER", "VA"): "47900",
    ("FAIRFAX", "VA"): "47900",
    ("HERNDON", "VA"): "47900",
    ("CHANTILLY", "VA"): "47900",
    ("SILVER SPRING", "MD"): "47900",
    ("COLLEGE PARK", "MD"): "47900",
    ("BALTIMORE", "MD"): "12580",  # Baltimore-Columbia-Towson MSA — separate from DC
    # NY (35620)
    ("NEW YORK", "NY"): "35620",
    ("MANHATTAN", "NY"): "35620",
    ("BROOKLYN", "NY"): "35620",
    ("QUEENS", "NY"): "35620",
    ("BRONX", "NY"): "35620",
    ("STATEN ISLAND", "NY"): "35620",
    ("JERSEY CITY", "NJ"): "35620",
    ("NEWARK", "NJ"): "35620",
    ("HOBOKEN", "NJ"): "35620",
    ("WHITE PLAINS", "NY"): "35620",
    ("STAMFORD", "CT"): "35620",
    # Boston (14460)
    ("BOSTON", "MA"): "14460",
    ("CAMBRIDGE", "MA"): "14460",
    ("WALTHAM", "MA"): "14460",
    ("BURLINGTON", "MA"): "14460",
    ("SOMERVILLE", "MA"): "14460",
    ("QUINCY", "MA"): "14460",
    # SF (41860)
    ("SAN FRANCISCO", "CA"): "41860",
    ("OAKLAND", "CA"): "41860",
    ("BERKELEY", "CA"): "41860",
    ("DALY CITY", "CA"): "41860",
    ("SOUTH SAN FRANCISCO", "CA"): "41860",
    ("REDWOOD CITY", "CA"): "41860",
    ("FOSTER CITY", "CA"): "41860",
    ("PALO ALTO", "CA"): "41860",  # Note: Palo Alto can also map to San Jose; DOL usage varies
    # San Jose (41940)
    ("SAN JOSE", "CA"): "41940",
    ("SANTA CLARA", "CA"): "41940",
    ("SUNNYVALE", "CA"): "41940",
    ("MOUNTAIN VIEW", "CA"): "41940",
    ("CUPERTINO", "CA"): "41940",
    ("MILPITAS", "CA"): "41940",
    ("MENLO PARK", "CA"): "41940",
    # Seattle (42660)
    ("SEATTLE", "WA"): "42660",
    ("BELLEVUE", "WA"): "42660",
    ("REDMOND", "WA"): "42660",
    ("KIRKLAND", "WA"): "42660",
    ("TACOMA", "WA"): "42660",
}


_STATE_NORMS = {
    "DISTRICT OF COLUMBIA": "DC",
    "D.C.": "DC",
    "WASH": "WA",
    "MASS.": "MA",
    "MD.": "MD",
}


def _norm(s: str | None) -> str:
    if s is None:
        return ""
    s = str(s).upper().strip()
    s = re.sub(r"[^A-Z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _norm_state(s: str | None) -> str:
    if s is None:
        return ""
    s = _norm(s)
    return _STATE_NORMS.get(s, s)


def city_state_to_cbsa(city: str | None, state: str | None) -> str | None:
    key = (_norm(city), _norm_state(state))
    return CITY_STATE_CBSA.get(key)


def attach_cbsa(
    df: pl.DataFrame,
    *,
    city_col: str = "worksite_city",
    state_col: str = "worksite_state",
    out_col: str = "cbsa_code",
) -> pl.DataFrame:
    """Add `cbsa_code` to the DataFrame; log unmatched rows to review CSV."""
    keys = (
        df.select([city_col, state_col])
        .unique()
        .with_columns(
            [
                pl.col(city_col).map_elements(_norm, return_dtype=pl.String).alias("_city_norm"),
                pl.col(state_col).map_elements(_norm_state, return_dtype=pl.String).alias("_state_norm"),
            ]
        )
    )
    cbsa_map = {(r["_city_norm"], r["_state_norm"]): CITY_STATE_CBSA.get((r["_city_norm"], r["_state_norm"])) for r in keys.iter_rows(named=True)}
    unmatched: list[dict] = []
    for (c, s), cbsa in cbsa_map.items():
        if cbsa is None and c:
            unmatched.append({"city": c, "state": s, "count": int(keys.filter((pl.col("_city_norm") == c) & (pl.col("_state_norm") == s)).height)})
    if unmatched:
        _log_geo_review(unmatched)

    # Apply mapping to df
    df = df.with_columns(
        [
            pl.col(city_col).map_elements(_norm, return_dtype=pl.String).alias("_city_norm"),
            pl.col(state_col).map_elements(_norm_state, return_dtype=pl.String).alias("_state_norm"),
        ]
    )
    df = df.with_columns(
        pl.struct(["_city_norm", "_state_norm"])
        .map_elements(
            lambda r: CITY_STATE_CBSA.get((r["_city_norm"], r["_state_norm"])),
            return_dtype=pl.String,
        )
        .alias(out_col)
    ).drop(["_city_norm", "_state_norm"])
    return df


def _log_geo_review(rows: list[dict]) -> None:
    GEO_REVIEW_CSV.parent.mkdir(parents=True, exist_ok=True)
    exists = GEO_REVIEW_CSV.exists()
    seen = set()
    if exists:
        with GEO_REVIEW_CSV.open("r", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                seen.add((r.get("city", ""), r.get("state", "")))
    new_rows = [r for r in rows if (r["city"], r["state"]) not in seen]
    if not new_rows:
        return
    with GEO_REVIEW_CSV.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["city", "state", "count", "cbsa_decision"])
        if not exists:
            w.writeheader()
        for r in new_rows:
            r.setdefault("cbsa_decision", "")
            w.writerow(r)
