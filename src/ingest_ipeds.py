"""IPEDS / Title IV institutions ingest — HIGH-confidence HIGHER_ED cap-exempt flag.

Pulls the federal Postsecondary Education Participants System (DAPIP) list
of currently active Title-IV institutions. Used to mark employers as
cap-exempt HIGHER_ED with HIGH confidence in `cap_exempt.py`.
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
    normalize_employer_name,
    save_sources_manifest,
)

_log = logging.getLogger("h1b.ingest_ipeds")

# DAPIP CSV API is JS-gated and 404s on direct hits. Use NCES IPEDS HD
# (Institutional Characteristics) bulk file as the authoritative Title-IV
# list instead. Discovered URL stable as of 2026-05-27.
DAPIP_INSTITUTION_LIST_URL = "https://nces.ed.gov/ipeds/datacenter/data/HD2023.zip"


def download_ipeds(*, force: bool = False, dry_run: bool = False) -> Path | None:
    if dry_run:
        _log.info("[dry-run] would download IPEDS HD institutional list")
        return None
    manifest = load_sources_manifest()
    target = RAW / "ipeds" / "HD2023.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        download_to(
            DAPIP_INSTITUTION_LIST_URL,
            target,
            name="ipeds_hd_2023",
            manifest=manifest,
            force=force,
        )
        save_sources_manifest(manifest)
        return target
    except Exception as exc:  # noqa: BLE001
        _log.error("IPEDS download failed: %s", exc)
        return None


def parse_ipeds(path: Path) -> pl.DataFrame:
    """Parse IPEDS HD zip. HD = Institutional Characteristics; one row per UNITID
    with INSTNM (institution name), ICLEVEL (1=4yr, 2=2yr, 3=<2yr), SECTOR, etc.
    """
    import io
    import zipfile

    with zipfile.ZipFile(path) as zf:
        csvs = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not csvs:
            raise FileNotFoundError(f"no csv in {path}")
        with zf.open(csvs[0]) as fh:
            data = fh.read()
    df = pl.read_csv(io.BytesIO(data), infer_schema_length=10_000, ignore_errors=True,
                     encoding="latin-1")
    # Pick the institution-name column heuristically
    upper = {c: c.upper() for c in df.columns}
    name_col = next((c for c, u in upper.items() if u == "INSTNM"), None)
    if name_col is None:
        name_col = next((c for c in df.columns if "name" in c.lower()), df.columns[0])
    df = df.with_columns(
        pl.col(name_col)
        .map_elements(normalize_employer_name, return_dtype=pl.String)
        .alias("employer_norm")
    )
    df = df.rename({name_col: "institution_name"})
    keep = ["institution_name", "employer_norm"] + [
        c for c in df.columns if c not in ("institution_name", "employer_norm")
    ]
    return df.select(keep)


def stage_ipeds(path: Path) -> Path:
    df = parse_ipeds(path)
    out_dir = STAGING / "ipeds"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "title_iv_institutions.parquet"
    df.write_parquet(out)
    _log.info("staged %s IPEDS institutions -> %s", df.height, out)
    return out
