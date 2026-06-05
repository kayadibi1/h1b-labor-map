"""Tiered employer entity resolution.

Pipeline (in order, per blueprint):
  1. Exact match on normalized name.
  2. Token-sort ratio (rapidfuzz) >= 95  -> auto-accept.
  3. 85-94                                -> review queue.
  4. < 85                                 -> reject (distinct employer).
  5. Curated corporate-group overrides (corporate_groups.yaml) applied LAST.

State persists in /data/manifest/employer_matches.csv so quarterly re-runs
only review NEW unmatched names.
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Iterable
from pathlib import Path

import polars as pl
import yaml
from rapidfuzz import fuzz, process

from .common import (
    MANIFEST,
    PROJECT_ROOT,
    normalize_employer_name,
)

_log = logging.getLogger("h1b.entity_resolve")

CORPORATE_GROUPS_PATH = MANIFEST / "corporate_groups.yaml"
EMPLOYER_MATCHES_CSV = MANIFEST / "employer_matches.csv"
EMPLOYER_REVIEW_CSV = MANIFEST / "employer_matches_review.csv"


def load_corporate_groups() -> dict[str, str]:
    """Returns alias_normalized -> canonical_group_name."""
    if not CORPORATE_GROUPS_PATH.exists():
        return {}
    with CORPORATE_GROUPS_PATH.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    out: dict[str, str] = {}
    for g in data.get("groups", []):
        canonical = g.get("canonical")
        if not canonical:
            continue
        out[normalize_employer_name(canonical)] = canonical
        for alias in g.get("aliases", []):
            out[normalize_employer_name(alias)] = canonical
    return out


def _load_persisted_matches() -> dict[str, str]:
    """Returns norm_name -> canonical_group from prior runs' decisions."""
    out: dict[str, str] = {}
    if not EMPLOYER_MATCHES_CSV.exists():
        return out
    with EMPLOYER_MATCHES_CSV.open("r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            n = row.get("employer_norm") or ""
            c = row.get("canonical_group") or ""
            if n and c:
                out[n] = c
    return out


def _persist_match(norm: str, canonical: str, *, tier: str, score: int | None = None) -> None:
    EMPLOYER_MATCHES_CSV.parent.mkdir(parents=True, exist_ok=True)
    exists = EMPLOYER_MATCHES_CSV.exists()
    with EMPLOYER_MATCHES_CSV.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(["employer_norm", "canonical_group", "tier", "score", "from"])
        w.writerow([norm, canonical, tier, score or "", "auto"])


def _write_review_rows(rows: Iterable[dict]) -> None:
    rows = list(rows)
    if not rows:
        return
    EMPLOYER_REVIEW_CSV.parent.mkdir(parents=True, exist_ok=True)
    exists = EMPLOYER_REVIEW_CSV.exists()
    with EMPLOYER_REVIEW_CSV.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["employer_norm", "candidate_group", "score", "decision"])
        if not exists:
            w.writeheader()
        for r in rows:
            r.setdefault("decision", "")
            w.writerow(r)


def resolve_employers(
    employer_names: list[str],
    *,
    auto_threshold: int = 95,
    review_threshold: int = 85,
) -> dict[str, str | None]:
    """Resolve a list of raw employer names to canonical group names.

    Returns dict raw_name -> canonical_group_or_None_if_distinct.

    The matcher's order:
        prior decisions -> exact corporate-group alias -> rapidfuzz >= auto_threshold
        -> review queue (review_threshold..auto_threshold) -> None.
    """
    corp_groups = load_corporate_groups()
    persisted = _load_persisted_matches()
    canonical_keys = list(corp_groups)  # normalized alias keys

    out: dict[str, str | None] = {}
    review_rows: list[dict] = []

    for raw in employer_names:
        norm = normalize_employer_name(raw)
        if not norm:
            out[raw] = None
            continue

        # 1. Prior decision
        if norm in persisted:
            out[raw] = persisted[norm]
            continue

        # 2. Exact alias in corporate-groups
        if norm in corp_groups:
            canonical = corp_groups[norm]
            _persist_match(norm, canonical, tier="exact_alias")
            out[raw] = canonical
            continue

        # 3. rapidfuzz token-sort against the alias set
        if canonical_keys:
            match, score, _ = process.extractOne(
                norm,
                canonical_keys,
                scorer=fuzz.token_sort_ratio,
            ) or (None, 0, None)
        else:
            match, score = None, 0

        if match and score >= auto_threshold:
            canonical = corp_groups[match]
            _persist_match(norm, canonical, tier="token_sort_auto", score=int(score))
            out[raw] = canonical
            continue

        if match and score >= review_threshold:
            review_rows.append(
                {
                    "employer_norm": norm,
                    "candidate_group": corp_groups[match],
                    "score": int(score),
                }
            )
            out[raw] = None  # treat as distinct until reviewer decides
            continue

        # 4. < review_threshold -> distinct legal entity, no group
        out[raw] = None

    _write_review_rows(review_rows)
    return out


def attach_canonical_to_df(
    df: pl.DataFrame,
    *,
    employer_col: str = "employer",
    norm_col: str = "employer_norm",
    out_col: str = "employer_group",
) -> pl.DataFrame:
    """Resolve every unique normalized employer in `df` and join the canonical."""
    if norm_col not in df.columns:
        df = df.with_columns(
            pl.col(employer_col)
            .map_elements(normalize_employer_name, return_dtype=pl.String)
            .alias(norm_col)
        )
    uniques = df.select(pl.col(employer_col)).unique().to_series().to_list()
    resolved = resolve_employers(uniques)
    mapping_df = pl.DataFrame(
        {employer_col: list(resolved.keys()), out_col: list(resolved.values())}
    )
    # Use the legal name as fallback so the column is never null at the row level
    df = df.join(mapping_df, on=employer_col, how="left")
    df = df.with_columns(
        pl.when(pl.col(out_col).is_null())
        .then(pl.col(norm_col))
        .otherwise(pl.col(out_col))
        .alias(out_col)
    )
    return df
