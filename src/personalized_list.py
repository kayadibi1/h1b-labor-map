"""Personalized employer list keyed to Sidar's 14 archetypes.

For each archetype we:
  1. Map to a SOC set.
  2. Query the H-1B mart for cap-exempt and cap-subject sponsors at his
     actual filter levels ($50K floor, US-wide, exclude staffing).
  3. Aggregate per legal-entity employer (not per SOC×CBSA row) so the list
     is a real shortlist, not a denormalized join.

Adds two sections the H-1B mart cannot see:
  - G-visa international orgs (UN system + IMF/WB/IFC etc.) — they don't file
    H-1B because their employees use G-4 visas.
  - UK HPI lane — London employers Sidar can join without sponsorship for
    2 years under the Johns Hopkins → HPI pathway.

Output: /data/marts/personalized_employer_list.html
"""

from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from .common import MARTS

_log = logging.getLogger("h1b.personalized")


# ---------------------------------------------------------------------------
# Archetype → SOC mapping (matched to Sidar's _profile.md)
# ---------------------------------------------------------------------------

ARCHETYPES: list[dict] = [
    {
        "name": "Management Consultant (Public Sector / Strategy)",
        "tier": "PRIMARY",
        "socs": ["13-1111", "13-1199"],
        "blurb": (
            "Tier-1 strategy firms + Big 4 GPS practices + federal-contractor strategy. "
            "MBB, Booz Allen, ICF, Guidehouse, Accenture Federal, Deloitte Consulting, "
            "EY-Parthenon Public Sector, KPMG GPS, PwC Strategy&."
        ),
    },
    {
        "name": "Policy / Research Analyst",
        "tier": "PRIMARY",
        "socs": ["13-1111", "19-3011", "19-3094", "19-3022", "19-3099"],
        "blurb": (
            "Think tanks + university policy centers + research nonprofits. "
            "Heavy cap-exempt lane — universities and qualifying research orgs file "
            "anytime, no lottery."
        ),
    },
    {
        "name": "International Development Consultant",
        "tier": "PRIMARY",
        "socs": ["13-1111", "11-9151", "13-1199"],
        "blurb": (
            "USAID-implementer ecosystem (Chemonics, DAI, RTI, Palladium, Abt, "
            "Tetra Tech) + Mathematica Policy Research + MSCI development arms. "
            "Sponsorship-friendly given international staff norms."
        ),
    },
    {
        "name": "Government & Public Sector Strategy Analyst",
        "tier": "SECONDARY",
        "socs": ["13-1111", "13-1199"],
        "blurb": (
            "Federal-facing consulting + agency contractors. Booz Allen, MITRE, "
            "Mantech, SAIC, CACI, Leidos. Cap-exempt for MITRE (FFRDC). "
            "Most others cap-subject."
        ),
    },
    {
        "name": "Geopolitical / Political Risk Analyst",
        "tier": "SECONDARY",
        "socs": ["19-3094", "13-1111", "19-3099"],
        "blurb": (
            "Eurasia Group, Control Risks, RANE/Stratfor, Beacon Global Strategies, "
            "Teneo, Albright Stonebridge, Kissinger Associates, Hakluyt, McLarty. "
            "Mostly cap-subject; some are UK-based (HPI lane)."
        ),
    },
    {
        "name": "Corporate Strategy Analyst",
        "tier": "ADJACENT",
        "socs": ["13-1111", "13-2051", "13-1199"],
        "blurb": (
            "Strategy & operations teams at Fortune-500 (financial services, "
            "industrial, consumer). Often cap-subject but high realism for L2+ wages."
        ),
    },
    {
        "name": "IO / NGO Program Analyst",
        "tier": "ADJACENT",
        "socs": ["11-9151", "13-1111"],
        "blurb": (
            "Domestic NGOs file H-1B (Brookings, RAND, etc.). "
            "True UN-system / Bretton Woods / regional development banks use "
            "**G-4 visas**, not H-1B — see the G-Visa section below for those."
        ),
    },
    # Specialized
    {
        "name": "Frontier AI Policy / Safety",
        "tier": "SPECIALIZED",
        "socs": ["13-1111", "13-1041", "11-9199", "13-1199"],
        "blurb": (
            "Anthropic, OpenAI, Google DeepMind, Microsoft AI policy, Meta AI policy, "
            "ARC Evals/METR. All cap-subject — high wages help in the wage-weighted "
            "lottery. Anthropic has known policy fellow programs."
        ),
    },
    {
        "name": "Big Tech Public Policy / Trust & Safety",
        "tier": "SPECIALIZED",
        "socs": ["13-1111", "13-1041", "13-1199"],
        "blurb": (
            "Meta, Google, ByteDance/TikTok, Microsoft, Amazon public policy + "
            "Trust & Safety teams. High-volume H-1B sponsors."
        ),
    },
    {
        "name": "Corporate Public Affairs (Financial Services)",
        "tier": "SPECIALIZED",
        "socs": ["13-1111", "13-2051", "13-1041"],
        "blurb": (
            "JPMorgan, Goldman Sachs, BlackRock, Morgan Stanley, Citi, Wells Fargo "
            "public-affairs / government-relations / regulatory-affairs teams."
        ),
    },
    {
        "name": "Corporate Public Affairs / Sustainability (Industrial/Consumer)",
        "tier": "SPECIALIZED",
        "socs": ["13-1111", "13-1041", "13-1199"],
        "blurb": (
            "Sustainability / ESG / trade-compliance teams at industrial and "
            "consumer MNCs. P&G, Unilever, Boeing, GE, Ford, Microsoft (sustainability)."
        ),
    },
    {
        "name": "Crypto / web3 Policy",
        "tier": "SPECIALIZED",
        "socs": ["13-1111", "13-1041", "13-2099"],
        "blurb": (
            "Coinbase, Circle, Stripe, Chainalysis, TRM Labs, Kharon, Elliptic. "
            "Smaller volume but sponsorship-friendly given international talent norms."
        ),
    },
    {
        "name": "Foundation Program Analyst / Associate",
        "tier": "SPECIALIZED",
        "socs": ["13-1111", "11-9151"],
        "blurb": (
            "Gates Foundation, Ford, MacArthur, Open Society, Hewlett, Rockefeller, "
            "Mott, Carnegie Corp of NY. Most are 501(c)(3) but sponsorship varies — "
            "Gates is cap-subject for program staff; check per-org."
        ),
    },
    {
        "name": "Economic / Regulatory Consulting Boutique",
        "tier": "SPECIALIZED",
        "socs": ["13-1111", "19-3011", "13-2051"],
        "blurb": (
            "CRA Charles River, Brattle Group, Cornerstone Research, BRG, "
            "Analysis Group, Compass Lexecon, NERA, Bates White, ERS, Edgeworth, "
            "FTI Consulting. Mid-tier consultancies known to sponsor analysts."
        ),
    },
]


# ---------------------------------------------------------------------------
# G-visa orgs (NOT in H-1B mart — different visa class)
# ---------------------------------------------------------------------------

GVISA_ORGS = [
    # UN system (G-4 visas)
    ("UN Secretariat (UN HQ NY)", "UN", "G-4 visa; YPP / P-1/P-2"),
    ("UNDP", "UN", "G-4; New York HQ + Istanbul Regional Hub"),
    ("UNICEF", "UN", "G-4; NY HQ + 190+ country offices"),
    ("UNFPA", "UN", "G-4; NY HQ + 8-country EECA Regional Office (Istanbul) — Sidar's home"),
    ("UN Women", "UN", "G-4; NY HQ"),
    ("UNESCO", "UN", "G-4; Paris HQ"),
    ("UNHCR", "UN", "G-4; Geneva HQ + DC liaison"),
    ("UNRWA", "UN", "G-4; Amman HQ + NY/Brussels liaison"),
    ("OHCHR (UN Human Rights)", "UN", "G-4; Geneva HQ + NY liaison"),
    ("UNOPS", "UN", "G-4; Copenhagen HQ + multiple regional hubs"),
    ("ILO", "UN", "G-4; Geneva HQ + DC liaison"),
    ("IOM (Migration)", "UN", "G-4; Geneva HQ"),
    ("FAO", "UN", "G-4; Rome HQ"),
    ("WFP", "UN", "G-4; Rome HQ"),
    ("WHO", "UN", "G-4; Geneva HQ + DC PAHO"),
    # Bretton Woods (G-4)
    ("IMF", "Bretton Woods", "G-4; DC HQ — strong SAIS pipeline"),
    ("World Bank", "Bretton Woods", "G-4; DC HQ — flagship Young Professionals Program"),
    ("IFC (World Bank Group)", "Bretton Woods", "G-4; DC HQ"),
    ("MIGA (World Bank Group)", "Bretton Woods", "G-4; DC HQ"),
    # Regional development banks (G-4 or equivalent)
    ("IDB (Inter-American Dev Bank)", "Regional MDB", "G-4; DC HQ"),
    ("AfDB (African Dev Bank)", "Regional MDB", "Abidjan HQ + DC liaison"),
    ("ADB (Asian Dev Bank)", "Regional MDB", "Manila HQ + DC liaison"),
    ("EBRD (European Bank for Reconstruction)", "Regional MDB", "London HQ — HPI compatible"),
    ("EIB (European Investment Bank)", "Regional MDB", "Luxembourg HQ"),
    # Other IOs (varies)
    ("OECD", "IO", "Paris HQ + DC mission; G-visa for DC"),
    ("WTO", "IO", "Geneva HQ"),
    ("OSCE", "IO", "Vienna HQ"),
    ("NATO HQ Brussels", "IO", "Brussels HQ"),
    ("WIPO", "IO", "Geneva HQ"),
    ("Bank for International Settlements (BIS)", "IO", "Basel HQ"),
]


# ---------------------------------------------------------------------------
# UK HPI lane (Sidar's second track — no sponsorship needed for 2 years)
# ---------------------------------------------------------------------------

UK_HPI_ORGS = [
    ("McKinsey & Company London", "Consulting (T1)", "Public sector + EMEA Strategy"),
    ("BCG London", "Consulting (T1)", "Public sector + Financial institutions"),
    ("Bain & Company London", "Consulting (T1)", "Public sector practice"),
    ("Oliver Wyman London", "Consulting (T2)", "Public sector + finance"),
    ("Deloitte Consulting UK", "Consulting (T2)", "Government & public services"),
    ("EY-Parthenon London", "Consulting (T2)", "Public sector + strategy"),
    ("PwC UK Strategy&", "Consulting (T2)", "Public sector + government"),
    ("KPMG UK", "Consulting (T2)", "Government practice"),
    ("Eurasia Group London", "Political Risk", "Europe coverage"),
    ("Control Risks London", "Political Risk", "Global HQ in London"),
    ("Hakluyt London", "Political Risk", "Hopkins-adjacent; small but elite"),
    ("Brunswick Group London", "Strategic Comms", "Public affairs + crisis"),
    ("Teneo London", "Strategic Comms", "Global HQ-adjacent"),
    ("Edelman Global Advisory London", "Strategic Comms", "Geopolitics + corporate"),
    ("Chatham House", "Think Tank", "Iconic UK IR think tank — research roles"),
    ("RUSI (Royal United Services Institute)", "Think Tank", "Defence + security"),
    ("IISS (International Institute for Strategic Studies)", "Think Tank", "Strategic studies"),
    ("ODI (Overseas Development Institute)", "Think Tank", "Development + IO sponsorship-friendly"),
    ("IFS (Institute for Fiscal Studies)", "Think Tank", "Quant fiscal policy"),
    ("NIESR (Nat'l Inst Econ & Soc Research)", "Think Tank", "Econ policy"),
    ("EBRD London HQ", "IO", "European Bank for Reconstruction — Turkey relevant"),
    ("HM Treasury Civil Service Fast Stream", "Government", "Open to HPI holders"),
    ("FCDO (Foreign Commonwealth Dev Office)", "Government", "Limited but HPI-compatible roles"),
    ("Open Society Foundations London", "Foundation", "Policy + advocacy"),
]


# ---------------------------------------------------------------------------
# Curated employer roster from Sidar's career-ops/jds folder + yml targets
# (cross-reference his existing tracking)
# ---------------------------------------------------------------------------

ALREADY_TRACKED = {
    "ANTHROPIC", "OPENAI", "GOOGLE", "ALPHABET", "BLACKROCK", "BLOOMBERG",
    "JPMORGAN", "JP MORGAN", "COINBASE", "CIRCLE", "STRIPE", "RAND",
    "CARNEGIE", "BAIN", "BAIN AND COMPANY", "EURASIA GROUP", "ATLANTIC COUNCIL",
    "PIIE", "PETERSON INSTITUTE", "KHARON", "ANALYSIS GROUP", "BRATTLE",
    "ASPEN INSTITUTE", "ASIA SOCIETY", "ALPHASIGHTS", "AMERICAN HOSPITAL ASSOCIATION",
    "AHIP", "AML RIGHT SOURCE", "ACCENTURE",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def e(s) -> str:
    return html.escape("" if s is None else str(s))


def fmt_int(v) -> str:
    try:
        return f"{int(float(v)):,}"
    except (TypeError, ValueError):
        return "—"


def fmt_money(v) -> str:
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return "—"


def fmt_pct(v) -> str:
    try:
        return f"{float(v) * 100:.0f}%"
    except (TypeError, ValueError):
        return "—"


def fmt_realism(v) -> str:
    try:
        f = float(v)
        cls = "good" if f >= 0.5 else ("med" if f >= 0.25 else "low")
        return f'<span class="r r-{cls}">{f:.2f}</span>'
    except (TypeError, ValueError):
        return "—"


def aggregate_by_employer(scored: pl.DataFrame, socs: list[str], *,
                          min_wage: float = 50000.0,
                          cap_exempt_only: bool = False,
                          exclude_staffing: bool = True) -> pl.DataFrame:
    """Per-employer aggregate for a given archetype SOC set."""
    df = scored.filter(pl.col("soc_code").is_in(socs))
    if cap_exempt_only:
        df = df.filter(pl.col("branch") == "CAP_EXEMPT")
    if exclude_staffing:
        df = df.filter(pl.col("staffing_firm_flag") == False)  # noqa: E712
    df = df.filter(pl.col("median_wage_filed").fill_null(0.0) >= float(min_wage))
    if df.is_empty():
        return df

    agg = (
        df.group_by("employer_name")
        .agg(
            [
                pl.col("uscis_initial_approvals_window").sum().alias("approvals"),
                pl.col("lca_filings_window").sum().alias("lcas"),
                pl.col("initial_approval_rate").mean().alias("approval_rate"),
                pl.col("median_wage_filed").mean().alias("avg_wage"),
                pl.col("sponsorship_realism").max().alias("realism"),
                pl.col("evidence_tier").mode().first().alias("evidence_tier"),
                pl.col("cap_exempt_subcategory").mode().first().alias("cap_exempt"),
                pl.col("branch").mode().first().alias("branch"),
                pl.col("staffing_firm_flag").any().alias("staffing"),
                pl.col("soc_code").unique().alias("socs"),
                pl.col("cbsa_code").unique().alias("cbsas"),
            ]
        )
        .filter(pl.col("approvals") > 0)
        .sort(["realism", "approvals"], descending=[True, True])
    )
    return agg


def archetype_table(name: str, agg: pl.DataFrame, *, top_n: int = 25) -> str:
    """Render top employers for an archetype as a table."""
    if agg.is_empty():
        return '<p><em>No matching sponsors in the mart at the $50K floor.</em></p>'
    rows = []
    for r in agg.head(top_n).iter_rows(named=True):
        emp_name = r.get("employer_name") or "?"
        emp_upper = emp_name.upper()
        tracked = any(t in emp_upper for t in ALREADY_TRACKED)
        flag = ' <small style="color:#7c3aed;">[on your radar]</small>' if tracked else ''
        socs = r.get("socs") or []
        soc_str = ", ".join(socs[:4])
        cbsas = [c for c in (r.get("cbsas") or []) if c]
        cbsa_str = ", ".join(cbsas[:3]) if cbsas else "off-map"
        cap_label = r.get("cap_exempt") or "NONE"
        cap_html = (f'<span style="color:#047857;font-weight:600;">{cap_label}</span>'
                    if cap_label != "NONE"
                    else '<span style="color:#64748b;">cap-subject</span>')
        rows.append(f"""
          <tr>
            <td><strong>{e(emp_name)}</strong>{flag}<br>
                <small>SOCs: {e(soc_str)} · {e(cbsa_str)}</small></td>
            <td>{cap_html}</td>
            <td class="num">{fmt_int(r.get('approvals'))}</td>
            <td class="num">{fmt_int(r.get('lcas'))}</td>
            <td class="num">{fmt_pct(r.get('approval_rate'))}</td>
            <td class="num">{fmt_money(r.get('avg_wage'))}</td>
            <td class="num">{fmt_realism(r.get('realism'))}</td>
            <td><span class="tier-{e(r.get('evidence_tier'))}">{e(r.get('evidence_tier'))}</span></td>
          </tr>
        """)
    return f"""
    <table>
      <thead><tr>
        <th>Employer</th><th>Branch</th><th>Initial approvals (4yr)</th>
        <th>LCAs (4yr)</th><th>Approval rate</th><th>Avg filed wage</th>
        <th>Realism</th><th>Evidence</th>
      </tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    """


def gvisa_section() -> str:
    rows = "".join(
        f"<tr><td><strong>{e(name)}</strong></td><td>{e(cat)}</td><td><small>{e(note)}</small></td></tr>"
        for name, cat, note in GVISA_ORGS
    )
    return f"""
    <h2>G-Visa international organizations (separate visa class)</h2>
    <div class="callout info">
      <strong>These employers don't sponsor H-1B.</strong> They use
      <code>G-4 visas</code> — issued by the State Department for staff and
      eligible family of international organizations. The H-1B cap is
      irrelevant; the lottery is irrelevant. The pathway is the org's own
      hiring process (often the YPP / Junior Professional Officer / consultant
      tracks).
      <br><br>
      <strong>For you specifically:</strong> Your UNFPA EECA Regional Office
      experience is direct insider currency at every UN-system org below.
      The IMF / World Bank YPP pipelines are explicit SAIS targets.
    </div>
    <table>
      <thead><tr><th>Organization</th><th>Category</th><th>Notes</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    """


def uk_hpi_section() -> str:
    rows = "".join(
        f"<tr><td><strong>{e(name)}</strong></td><td>{e(cat)}</td><td><small>{e(note)}</small></td></tr>"
        for name, cat, note in UK_HPI_ORGS
    )
    return f"""
    <h2>UK HPI lane — no sponsorship needed for 2 years</h2>
    <div class="callout good">
      <strong>Johns Hopkins → UK HPI visa.</strong> 2 years of unrestricted UK
      work authorization without any employer sponsorship. Any London role that
      filters on "right to work" or "no sponsorship" is still accessible to
      you. Treat this as your second track if the US path doesn't land by
      Dec 2026.
      <br><br>
      <strong>Note:</strong> HPI is a 2-year bridge, not permanent. The next
      step requires a Skilled Worker / Global Talent visa or a different
      pathway. Pick UK employers with track records of converting HPI → SW.
    </div>
    <table>
      <thead><tr><th>Employer</th><th>Category</th><th>Notes</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    """


# ---------------------------------------------------------------------------
# Build the report
# ---------------------------------------------------------------------------

CSS = """
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; color: #0f172a; background: #f8fafc; line-height: 1.55; }
body { max-width: 1240px; margin: 0 auto; padding: 32px 28px 80px; }
h1 { font-size: 30px; margin: 0 0 4px; color: #0f172a; letter-spacing: -0.02em; }
h2 { font-size: 22px; margin: 56px 0 12px; padding-bottom: 8px; border-bottom: 2px solid #e2e8f0; color: #0f172a; }
h3 { font-size: 17px; margin: 28px 0 8px; color: #1e293b; }
p, li { font-size: 14.5px; color: #334155; }
small { color: #64748b; }
code { background: #eef2ff; color: #3730a3; padding: 1px 5px; border-radius: 3px; font-family: 'SF Mono', Menlo, Consolas, monospace; font-size: 13px; }
.subhead { color: #64748b; font-size: 14.5px; margin: 0 0 24px; }
.callout { border-radius: 8px; padding: 16px 20px; margin: 14px 0; font-size: 14.5px; }
.callout.warn { background: #fef3c7; border-left: 4px solid #d97706; }
.callout.good { background: #d1fae5; border-left: 4px solid #059669; }
.callout.info { background: #dbeafe; border-left: 4px solid #2563eb; }
.callout.note { background: #f1f5f9; border-left: 4px solid #64748b; }
.archetype-card { background: white; border: 1px solid #e2e8f0; border-radius: 10px; padding: 22px 24px; margin: 18px 0; }
.archetype-card .tier { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; letter-spacing: 0.05em; }
.tier-PRIMARY     { background: #dcfce7; color: #166534; }
.tier-SECONDARY   { background: #dbeafe; color: #1e40af; }
.tier-ADJACENT    { background: #f1f5f9; color: #475569; }
.tier-SPECIALIZED { background: #fef3c7; color: #92400e; }
table { width: 100%; border-collapse: collapse; margin: 12px 0 18px; font-size: 13.5px; }
th { text-align: left; padding: 10px 8px; background: #f1f5f9; border-bottom: 1px solid #e2e8f0; font-weight: 600; color: #1e293b; font-size: 12.5px; text-transform: uppercase; letter-spacing: 0.03em; }
td { padding: 10px 8px; border-bottom: 1px solid #f1f5f9; vertical-align: top; }
tr:nth-child(even) td { background: #fafbfc; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.r { display: inline-block; padding: 2px 6px; border-radius: 3px; font-weight: 600; }
.r-good { background: #d1fae5; color: #065f46; }
.r-med  { background: #fef3c7; color: #92400e; }
.r-low  { background: #fee2e2; color: #991b1b; }
.tier-HIGH   { color: #047857; font-weight: 600; }
.tier-MEDIUM { color: #b45309; font-weight: 600; }
.tier-LOW    { color: #b91c1c; }
footer { margin-top: 80px; padding-top: 24px; border-top: 1px solid #e2e8f0; font-size: 12px; color: #94a3b8; text-align: center; }
"""


def build_personalized_list(out_path: Path | None = None) -> Path:
    scored = pl.read_parquet(MARTS / "mart_scored.parquet")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    sections: list[str] = []

    # Header + framing
    sections.append(f"""
    <header>
      <h1>Personalized employer shortlist — Sidar Aslanoglu</h1>
      <p class="subhead">Generated {e(now)} from your 14 archetypes
      × 437K real DOL OFLC LCAs + 209K USCIS Hub records. Filters: $50K floor
      (your <code>profile.yml</code> minimum), staffing firms excluded,
      US-wide geography.</p>
    </header>
    <div class="callout good">
      <strong>Three lanes, ranked by current reality.</strong>
      <ol style="margin: 6px 0 0 20px;">
        <li><strong>Cap-exempt H-1B (no lottery)</strong> — universities,
        affiliated nonprofits, nonprofit research orgs, gov't research. Your
        dominant US path under non-STEM OPT.</li>
        <li><strong>G-Visa international orgs</strong> — UN system, IMF, WB,
        IFC, EBRD. Different visa class entirely; not in the H-1B mart.
        Your UNFPA insider currency is highest here.</li>
        <li><strong>UK HPI lane</strong> — 2 years unrestricted UK work, no
        sponsor required. Treat as your second track if US doesn't land by
        Dec 2026.</li>
      </ol>
    </div>
    """)

    # Each archetype gets its own card with 2 tables (cap-exempt + cap-subject)
    for arch in ARCHETYPES:
        cap_ex = aggregate_by_employer(scored, arch["socs"], cap_exempt_only=True)
        cap_sub = aggregate_by_employer(scored, arch["socs"], cap_exempt_only=False)
        # Filter cap_sub to only CAP_SUBJECT (since the all-call returns mixed)
        if not cap_sub.is_empty():
            cap_sub = cap_sub.filter(pl.col("branch") == "CAP_SUBJECT")

        sections.append(f"""
        <div class="archetype-card">
          <div style="display:flex; align-items:baseline; gap:12px;">
            <h3 style="margin:0;">{e(arch['name'])}</h3>
            <span class="tier tier-{e(arch['tier'])}">{e(arch['tier'])}</span>
          </div>
          <p style="margin-top:8px; color:#475569;">{e(arch['blurb'])}</p>

          <h3 style="margin-top:18px;">Cap-exempt sponsors (no lottery — start here)</h3>
          {archetype_table(arch['name'], cap_ex, top_n=20)}

          <h3 style="margin-top:18px;">Cap-subject sponsors (lottery factored into realism)</h3>
          {archetype_table(arch['name'], cap_sub, top_n=15)}
        </div>
        """)

    sections.append(gvisa_section())
    sections.append(uk_hpi_section())

    # Strategy summary
    sections.append("""
    <h2>Sequencing — what to do this quarter</h2>
    <div class="callout warn">
      <strong>OPT timing trap.</strong> Your OPT starts July 2026 and ends
      ~July 2027. If you go cap-subject, the FY2028 lottery runs March 2027
      and H-1B status starts October 1, 2027 — a 3-month gap. You need
      cap-gap eligibility, which requires the petition <strong>filed before
      your OPT expires</strong>. Practically, the employer must be locked in
      by December 2026.
    </div>

    <h3>Recommended weekly cadence (June 2026 → December 2026)</h3>
    <ol>
      <li><strong>Apply broadly to G-visa orgs in parallel</strong> — IMF YPP
      / WB YPP / UNDP / UNICEF / UNFPA continuing-role conversions. These
      bypass H-1B entirely.</li>
      <li><strong>Outreach to top 15 cap-exempt H-1B targets</strong> from the
      tables above. Lead with your UNFPA proof point + Bilkent SNA modeling.
      RAND, MITRE, Mathematica, Brookings, university policy centers.</li>
      <li><strong>Open UK HPI as a parallel track</strong> — McKinsey London,
      BCG London, Chatham House, Hakluyt, RUSI. No sponsorship needed for the
      first 2 years.</li>
      <li><strong>Cap-subject as backup</strong> — target firms that file
      Level II+ for analyst roles. Big 4 GPS practices, MBB DC offices,
      Booz Allen, ICF, Guidehouse. Avoid the staffing-firm pattern in your
      red flags view.</li>
      <li><strong>Hard lock by Dec 2026</strong> — for cap-subject, the
      employer must commit by then to be ready for March 2027 registration.</li>
    </ol>

    <h3>Plan B if H-1B doesn't land by July 2027</h3>
    <ul>
      <li><strong>O-1A</strong> if you accumulate notable publications/awards in policy research.</li>
      <li><strong>EB-2 NIW</strong> for policy work of national significance (Sanctions / EU regulation can qualify).</li>
      <li><strong>UK HPI activation</strong> — pivot to a 2-year London track. EBRD London or Chatham House is Turkey-relevant.</li>
      <li><strong>Turkey re-entry with US-conducive role</strong> — UNFPA Istanbul, EBRD Ankara, IPC, TUSIAD — credentialing for a future US/UK move.</li>
    </ul>
    """)

    sections.append('<footer>Generated by h1b-labor-map · '
                    'src/personalized_list.py · re-run via '
                    '<code>python -c "from src.personalized_list import build_personalized_list; build_personalized_list()"</code></footer>')

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Personalized Employer List — Sidar Aslanoglu</title>
<style>{CSS}</style>
</head>
<body>
{''.join(sections)}
</body>
</html>
"""
    out = out_path or (MARTS / "personalized_employer_list.html")
    out.write_text(html_doc, encoding="utf-8")
    _log.info("wrote personalized list -> %s", out)
    return out


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    p = build_personalized_list()
    print(f"Wrote: {p}")
