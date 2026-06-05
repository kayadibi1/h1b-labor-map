"""Probe candidate URLs without Range headers — some servers refuse partial GET."""

from __future__ import annotations

import requests

UA = "h1b-labor-map/0.1 (research; sidarvig@gmail.com)"

URLS = [
    # DOL OFLC LCA (confirmed pattern from landing page)
    "https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY2025_Q4.xlsx",
    "https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY2024_Q4.xlsx",
    "https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY2023_Q4.xlsx",
    "https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY2022_Q4.xlsx",
    # PERM
    "https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/PERM_Disclosure_Data_FY2025_Q4.xlsx",
    "https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/PERM_Disclosure_Data_FY2024_Q4.xlsx",
    # USCIS Hub
    "https://www.uscis.gov/sites/default/files/document/data/h1b_datahubexport-2024.csv",
    "https://www.uscis.gov/sites/default/files/document/data/h1b_datahubexport-2023.csv",
    "https://www.uscis.gov/sites/default/files/document/data/h1b_datahubexport-2022.csv",
    # OEWS
    "https://www.bls.gov/oes/special.requests/oesm24ma.zip",
    "https://www.bls.gov/oes/special.requests/oesm23ma.zip",
    # SEC
    "https://www.sec.gov/files/company_tickers.json",
]


def probe(url: str) -> tuple[str, str]:
    try:
        # HEAD-equivalent: GET with stream=True, then close without reading body
        r = requests.get(
            url,
            headers={"User-Agent": UA, "Accept": "*/*"},
            timeout=30,
            allow_redirects=True,
            stream=True,
        )
        size = r.headers.get("Content-Length", "?")
        try:
            mb = f"{int(size) / 1024 / 1024:.1f} MB"
        except (ValueError, TypeError):
            mb = size
        r.close()
        return (str(r.status_code), mb)
    except Exception as e:  # noqa: BLE001
        return ("ERR", str(e)[:50])


for u in URLS:
    status, size = probe(u)
    flag = "OK  " if status == "200" else "FAIL"
    print(f"{flag} {status:>4}  {size:>10}  {u}")
