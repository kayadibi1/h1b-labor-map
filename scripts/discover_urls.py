"""Scrape DOL OFLC + USCIS Hub landing pages and pull the actual download URLs."""

from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

UA = "h1b-labor-map/0.1 (research; sidarvig@gmail.com)"

LANDING_PAGES = {
    "DOL OFLC": "https://www.dol.gov/agencies/eta/foreign-labor/performance",
    "USCIS Hub Files": "https://www.uscis.gov/tools/reports-and-studies/h-1b-employer-data-hub",
    "USCIS Hub Files Archive": "https://www.uscis.gov/archive/h-1b-employer-data-hub-files",
    "IPEDS DAPIP": "https://ope.ed.gov/dapip/",
    "DOL OFLC FLAG LCA": "https://flag.dol.gov/programs/LCA",
}

PATTERNS = {
    "DOL OFLC": re.compile(r"LCA_Disclosure_Data[^\"' ]*\.(?:xlsx|csv)", re.IGNORECASE),
    "DOL OFLC PERM": re.compile(r"PERM_Disclosure_Data[^\"' ]*\.(?:xlsx|csv)", re.IGNORECASE),
    "USCIS Hub": re.compile(r"h1b_datahubexport[^\"' ]*\.(?:csv|xlsx)", re.IGNORECASE),
}


def fetch(url: str) -> str | None:
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"}, timeout=30)
        if r.status_code == 200:
            return r.text
        print(f"  [non-200: {r.status_code}] {url}")
        return None
    except Exception as e:  # noqa: BLE001
        print(f"  [ERR] {e}: {url}")
        return None


def main() -> None:
    for name, url in LANDING_PAGES.items():
        print(f"\n=== {name}: {url} ===")
        html = fetch(url)
        if html is None:
            continue
        soup = BeautifulSoup(html, "lxml")
        # All anchor hrefs
        hrefs = {a.get("href", "") for a in soup.find_all("a", href=True)}
        # Apply each pattern
        for pname, pat in PATTERNS.items():
            for h in hrefs:
                if pat.search(h):
                    full = h if h.startswith("http") else (
                        f"https://www.dol.gov{h}" if "dol.gov" in url or h.startswith("/sites/") else
                        f"https://www.uscis.gov{h}" if "uscis.gov" in url else
                        h
                    )
                    print(f"  [{pname}] {full}")
        # Also any .xlsx / .csv / .zip
        if name in ("DOL OFLC", "DOL OFLC FLAG LCA"):
            for h in sorted(hrefs):
                if h.lower().endswith((".xlsx", ".csv", ".zip")) and (
                    "lca" in h.lower() or "perm" in h.lower() or "disclosure" in h.lower()
                ):
                    full = h if h.startswith("http") else f"https://www.dol.gov{h}" if h.startswith("/") else h
                    print(f"  [any-data] {full}")
        if name in ("USCIS Hub Files", "USCIS Hub Files Archive"):
            for h in sorted(hrefs):
                if h.lower().endswith((".xlsx", ".csv")) and "datahub" in h.lower():
                    full = h if h.startswith("http") else f"https://www.uscis.gov{h}" if h.startswith("/") else h
                    print(f"  [any-data] {full}")
        if name == "IPEDS DAPIP":
            for h in sorted(hrefs):
                if h.lower().endswith((".csv", ".xlsx", ".zip")) or "csv" in h.lower():
                    print(f"  [any-data] {h}")


if __name__ == "__main__":
    main()
