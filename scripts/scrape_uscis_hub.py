"""Pull every file-looking URL off the live USCIS Hub page."""

from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

UA = "h1b-labor-map/0.1 (research; sidarvig@gmail.com)"


def scan(url: str) -> None:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    print(f"\n=== {url}  -> {r.status_code} {len(r.text)} bytes ===")
    soup = BeautifulSoup(r.text, "lxml")
    hits: set[str] = set()
    for a in soup.find_all("a", href=True):
        h = a["href"]
        if any(k in h.lower() for k in ("datahub", "h-1b", "h1b")):
            if h.lower().endswith((".csv", ".xlsx", ".zip")):
                full = h if h.startswith("http") else f"https://www.uscis.gov{h}" if h.startswith("/") else h
                hits.add(full)
    for h in sorted(hits):
        print(f"  {h}")
    # Also pull any data file URLs from text/scripts
    pat = re.compile(r"https?://[^\"' >]+(?:datahub|h1b)[^\"' >]*?\.(?:csv|xlsx)", re.IGNORECASE)
    for m in pat.findall(r.text):
        if m not in hits:
            print(f"  [script] {m}")


for u in (
    "https://www.uscis.gov/tools/reports-and-studies/h-1b-employer-data-hub",
    "https://www.uscis.gov/tools/reports-and-studies/h-1b-employer-data-hub/h-1b-employer-data-hub-files",
    "https://www.uscis.gov/archive/h-1b-employer-data-hub-files",
):
    scan(u)
