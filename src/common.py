"""Shared utilities: config loading, paths, source manifest, HTTP download.

Everything here is dependency-light and side-effect-free where possible so it
can be reused by every ingest/transform module.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yaml
from dotenv import load_dotenv
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA = PROJECT_ROOT / "data"
RAW = DATA / "raw"
STAGING = DATA / "staging"
MARTS = DATA / "marts"
MANIFEST = DATA / "manifest"
SNAPSHOTS = MANIFEST / "snapshots"
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
USER_PROFILE_PATH = PROJECT_ROOT / "user_profile.yaml"
SOURCES_MANIFEST = MANIFEST / "sources.json"


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Initialise a single root logger with a readable line format."""
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(level=level, format=fmt, stream=sys.stdout, force=True)
    return logging.getLogger("h1b")


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_user_profile(path: Path = USER_PROFILE_PATH) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_env() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=False)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path, buf: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(buf)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Source manifest — incremental-run support per blueprint
# ---------------------------------------------------------------------------


@dataclass
class SourceEntry:
    name: str
    url: str
    etag: str | None = None
    last_modified: str | None = None
    sha256: str | None = None
    bytes: int | None = None
    downloaded_at: str | None = None
    saved_to: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "sha256": self.sha256,
            "bytes": self.bytes,
            "downloaded_at": self.downloaded_at,
            "saved_to": self.saved_to,
            "extra": self.extra,
        }


def load_sources_manifest() -> dict[str, SourceEntry]:
    if not SOURCES_MANIFEST.exists():
        return {}
    with SOURCES_MANIFEST.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    return {k: SourceEntry(**v) for k, v in raw.items()}


def save_sources_manifest(entries: dict[str, SourceEntry]) -> None:
    MANIFEST.mkdir(parents=True, exist_ok=True)
    payload = {k: v.to_dict() for k, v in entries.items()}
    with SOURCES_MANIFEST.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)


# ---------------------------------------------------------------------------
# HTTP download with retry, conditional fetch, and sha256 capture
# ---------------------------------------------------------------------------

_log = logging.getLogger("h1b.common")

# Akamai (on dol.gov, bls.gov) is touchy:
#   - Rejects Firefox/Chrome-shaped UAs ("likely bots faking a browser").
#   - Rejects bare/sparse UAs without a contact email in the parenthetical
#     (e.g. "h1b-labor-map/0.1 (research)" gets 403).
#   - Accepts identifiable UAs *with* an email, e.g.
#     "h1b-labor-map/0.1 (research; sidarvig@gmail.com)".
# SEC EDGAR is a separate beast: requires "name email" format.
# Verified 2026-05-27 by side-by-side requests.
def _build_default_headers() -> dict[str, str]:
    contact = os.getenv("PROPUBLICA_CONTACT_EMAIL")
    paren = f"research; {contact}" if contact else "research"
    return {
        "User-Agent": f"h1b-labor-map/0.1 ({paren})",
        "Accept": "*/*",
    }


class HTTPError(Exception):
    pass


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=20),
    retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout, HTTPError)),
)
def http_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 60,
    allow_redirects: bool = True,
) -> requests.Response:
    """GET with retry + a sane User-Agent. Raises on 5xx; returns Response otherwise.

    SEC EDGAR requires a contact email in the User-Agent. We honor
    PROPUBLICA_CONTACT_EMAIL as a generic contact-email var.
    """
    contact = os.getenv("PROPUBLICA_CONTACT_EMAIL")
    hdrs = _build_default_headers()
    if "sec.gov" in url and contact:
        # SEC's documented requirement: "name email" format. They reject Firefox-like UAs.
        hdrs["User-Agent"] = f"h1b-labor-map-research {contact}"
        hdrs["Host"] = "www.sec.gov"
    elif contact:
        hdrs["From"] = contact
    if headers:
        hdrs.update(headers)
    resp = requests.get(url, headers=hdrs, timeout=timeout, allow_redirects=allow_redirects)
    if resp.status_code >= 500:
        raise HTTPError(f"server error {resp.status_code} for {url}")
    return resp


def download_to(
    url: str,
    dest: Path,
    *,
    name: str,
    manifest: dict[str, SourceEntry],
    force: bool = False,
    extra: dict[str, Any] | None = None,
) -> SourceEntry:
    """Download `url` to `dest` with conditional ETag/Last-Modified.

    Skips download if the manifest entry's ETag/Last-Modified is unchanged and
    the file still exists on disk.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    prior = manifest.get(name)
    headers: dict[str, str] = {}
    if prior and not force and dest.exists():
        if prior.etag:
            headers["If-None-Match"] = prior.etag
        if prior.last_modified:
            headers["If-Modified-Since"] = prior.last_modified

    _log.info("downloading %s -> %s (force=%s)", url, dest, force)
    resp = http_get(url, headers=headers)
    if resp.status_code == 304 and prior is not None and dest.exists():
        _log.info("304 not modified — using cached %s", dest)
        return prior
    if resp.status_code != 200:
        raise HTTPError(f"unexpected status {resp.status_code} for {url}")
    dest.write_bytes(resp.content)
    entry = SourceEntry(
        name=name,
        url=url,
        etag=resp.headers.get("ETag"),
        last_modified=resp.headers.get("Last-Modified"),
        sha256=sha256_file(dest),
        bytes=dest.stat().st_size,
        downloaded_at=utcnow_iso(),
        saved_to=str(dest.relative_to(PROJECT_ROOT)),
        extra=extra or {},
    )
    manifest[name] = entry
    return entry


# ---------------------------------------------------------------------------
# Name normalization — used by entity_resolve and elsewhere
# ---------------------------------------------------------------------------

import re

_LEGAL_SUFFIXES = (
    r"\bINCORPORATED\b",
    r"\bINC\.?\b",
    r"\bLLC\.?\b",
    r"\bL\.L\.C\.?\b",
    r"\bCORP(?:ORATION)?\.?\b",
    r"\bCO(?:MPANY)?\.?\b",
    r"\bLTD\.?\b",
    r"\bLLP\.?\b",
    r"\bL\.L\.P\.?\b",
    r"\bLP\.?\b",
    r"\bPLLC\b",
    r"\bPC\b",
    r"\bP\.C\.?\b",
    r"\bGROUP\b",
    r"\bHOLDINGS\b",
    r"\bUSA\b",
    r"\bU\.?S\.?A?\.?\b",
    r"\bNORTH AMERICA\b",
    r"\bNA\b",
    r"\bDBA\b",
    r"\bDOING BUSINESS AS\b",
)

_SUFFIX_RE = re.compile("|".join(_LEGAL_SUFFIXES), flags=re.IGNORECASE)
_NONALNUM_RE = re.compile(r"[^A-Z0-9\s&]")
_WS_RE = re.compile(r"\s+")


def normalize_employer_name(name: str | None) -> str:
    """Uppercase, strip punctuation + legal-form suffixes, collapse whitespace."""
    if not name:
        return ""
    s = name.upper().replace("&", " AND ")
    s = _SUFFIX_RE.sub(" ", s)
    s = _NONALNUM_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


# ---------------------------------------------------------------------------
# Wage normalization to annual
# ---------------------------------------------------------------------------

_HOURS_PER_YEAR = 2080.0  # 40 * 52


def normalize_wage_to_annual(wage: float | None, unit: str | None) -> float | None:
    """Normalize a wage to annual based on unit-of-pay code/label.

    Accepts common DOL codes ('Year', 'Hour', 'Week', 'Bi-Weekly', 'Month') and
    short codes ('YR', 'HR', 'WK', 'BI', 'MO'). Returns None on unknowns.
    """
    if wage is None:
        return None
    if unit is None:
        return wage  # caller's risk; better than dropping
    u = str(unit).upper().strip()
    if u in {"YEAR", "YR", "ANNUAL", "ANN", "Y"}:
        return float(wage)
    if u in {"HOUR", "HR", "HOURLY", "H"}:
        return float(wage) * _HOURS_PER_YEAR
    if u in {"WEEK", "WK", "WEEKLY", "W"}:
        return float(wage) * 52.0
    if u in {"BI-WEEKLY", "BI", "BIWEEKLY", "BW"}:
        return float(wage) * 26.0
    if u in {"MONTH", "MO", "MONTHLY", "M"}:
        return float(wage) * 12.0
    return None


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


def ensure_dirs() -> None:
    for p in (RAW, STAGING, MARTS, MANIFEST, SNAPSHOTS):
        p.mkdir(parents=True, exist_ok=True)


def write_review_csv(path: Path, rows: list[dict[str, Any]], headers: list[str]) -> None:
    """Append rows to a manifest review CSV (header preserved if file exists)."""
    import csv

    exists = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        if not exists:
            w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in headers})
