"""Probe primary source URLs to confirm they actually resolve under real headers."""
from __future__ import annotations

import requests

UA = "h1b-labor-map/0.1 (research; sidarvig@gmail.com)"

URLS = [
    # DOL OFLC LCA
    "https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY2025.xlsx",
    "https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY2024.xlsx",
    "https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY2023.xlsx",
    "https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY2022.xlsx",
    # USCIS Employer Data Hub
    "https://www.uscis.gov/sites/default/files/document/data/h1b_datahubexport-2024.csv",
    "https://www.uscis.gov/sites/default/files/document/data/h1b_datahubexport-2025.csv",
    "https://www.uscis.gov/sites/default/files/document/data/h1b_datahubexport-2026.csv",
    # BLS OEWS
    "https://www.bls.gov/oes/special.requests/oesm24ma.zip",
    "https://www.bls.gov/oes/special.requests/oesm23ma.zip",
    # IPEDS / DAPIP
    "https://ope.ed.gov/dapip/api/institution/csv?activeOnly=true&format=csv",
    "https://ope.ed.gov/dapip/#/home",
    # SEC EDGAR
    "https://www.sec.gov/files/company_tickers.json",
    # Census (confirmed working)
    "https://www2.census.gov/programs-surveys/metro-micro/geographies/reference-files/2023/delineation-files/list1_2023.xlsx",
]


def probe(url: str) -> tuple[str, str, str]:
    try:
        r = requests.get(
            url,
            headers={"User-Agent": UA, "Range": "bytes=0-1023", "Accept": "*/*"},
            timeout=30,
            allow_redirects=True,
            stream=True,
        )
        size = r.headers.get("Content-Length") or r.headers.get("Content-Range", "?")
        ctype = r.headers.get("Content-Type", "?")[:30]
        return (str(r.status_code), ctype, str(size))
    except Exception as e:  # noqa: BLE001
        return ("ERR", str(e)[:60], "")


for u in URLS:
    status, ctype, size = probe(u)
    print(f"{status:>4}  {ctype:30}  {size:30}  {u}")
