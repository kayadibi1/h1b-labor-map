"""Generate a self-contained HTML visual report from the mart views.

Single file (no external CSS/JS) so it opens in any browser. Inline SVG bar/donut
charts. Color-coded tables. Plain-English methodology callouts.

Output: /data/marts/report.html
"""

from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from .common import MARTS, load_config, load_user_profile

_log = logging.getLogger("h1b.report")

# ---------------------------------------------------------------------------
# Style + palette
# ---------------------------------------------------------------------------

CSS = """
* { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  color: #0f172a;
  background: #f8fafc;
  line-height: 1.55;
}
body { max-width: 1180px; margin: 0 auto; padding: 32px 28px 80px; }

h1 { font-size: 32px; margin: 0 0 4px; color: #0f172a; letter-spacing: -0.02em; }
h2 { font-size: 22px; margin: 56px 0 12px; padding-bottom: 8px;
     border-bottom: 2px solid #e2e8f0; color: #0f172a; letter-spacing: -0.01em; }
h3 { font-size: 16px; margin: 28px 0 8px; color: #1e293b; }
p, li { font-size: 14.5px; color: #334155; }
small { color: #64748b; }
code { background: #eef2ff; color: #3730a3; padding: 1px 5px; border-radius: 3px;
       font-family: 'SF Mono', Menlo, Consolas, monospace; font-size: 13px; }
a { color: #1d4ed8; }

.subhead { color: #64748b; font-size: 14.5px; margin: 0 0 24px; }

.callout {
  border-radius: 8px;
  padding: 18px 22px;
  margin: 16px 0;
  font-size: 14.5px;
}
.callout.warn   { background: #fef3c7; border-left: 4px solid #d97706; }
.callout.bad    { background: #fee2e2; border-left: 4px solid #dc2626; }
.callout.good   { background: #d1fae5; border-left: 4px solid #059669; }
.callout.info   { background: #dbeafe; border-left: 4px solid #2563eb; }
.callout.note   { background: #f1f5f9; border-left: 4px solid #64748b; }

.kpi-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 20px 0 28px; }
.kpi { background: white; border: 1px solid #e2e8f0; border-radius: 8px;
       padding: 14px 16px; }
.kpi .label { font-size: 12px; color: #64748b; text-transform: uppercase;
              letter-spacing: 0.04em; }
.kpi .value { font-size: 24px; font-weight: 600; color: #0f172a; margin-top: 4px; }
.kpi .sub { font-size: 12px; color: #94a3b8; margin-top: 2px; }

.card { background: white; border: 1px solid #e2e8f0; border-radius: 8px;
        padding: 18px 20px; margin: 12px 0; }
.card h3 { margin-top: 0; }

table { width: 100%; border-collapse: collapse; margin: 12px 0 18px;
        font-size: 13.5px; }
th { text-align: left; padding: 10px 8px; background: #f1f5f9;
     border-bottom: 1px solid #e2e8f0; font-weight: 600; color: #1e293b;
     font-size: 12.5px; text-transform: uppercase; letter-spacing: 0.03em; }
td { padding: 10px 8px; border-bottom: 1px solid #f1f5f9; vertical-align: top; }
tr:nth-child(even) td { background: #fafbfc; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }

.tier-HIGH   { color: #047857; font-weight: 600; }
.tier-MEDIUM { color: #b45309; font-weight: 600; }
.tier-LOW    { color: #b91c1c; }

.branch-CAP_EXEMPT  { color: #047857; }
.branch-CAP_SUBJECT { color: #b45309; }

.realism-bar { display: inline-block; height: 14px; vertical-align: middle;
               background: #34d399; border-radius: 3px; min-width: 4px; }
.realism-bar.low { background: #fde68a; }
.realism-bar.med { background: #fbbf24; }

.bar-chart { width: 100%; height: auto; }

footer { margin-top: 80px; padding-top: 24px; border-top: 1px solid #e2e8f0;
         font-size: 12px; color: #94a3b8; text-align: center; }
"""


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


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


def fmt_int(v) -> str:
    try:
        return f"{int(float(v)):,}"
    except (TypeError, ValueError):
        return "—"


def fmt_float(v, digits=2) -> str:
    try:
        return f"{float(v):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def e(s) -> str:
    return html.escape("" if s is None else str(s))


def realism_bar(value: float) -> str:
    v = max(0.0, min(1.0, float(value or 0)))
    width = int(v * 100)
    cls = "" if v >= 0.5 else ("med" if v >= 0.25 else "low")
    return (
        f'<span class="realism-bar {cls}" style="width:{width}px"></span>'
        f' <small>{v:.2f}</small>'
    )


# ---------------------------------------------------------------------------
# Inline SVG bar chart
# ---------------------------------------------------------------------------


def hbar_chart(data: list[tuple[str, float]], *, height_per_bar: int = 24,
               width: int = 760, value_fmt=fmt_int,
               bar_color: str = "#0f766e", label_chars: int = 56) -> str:
    """Horizontal bar chart in inline SVG. data: [(label, value), ...]"""
    if not data:
        return '<p><em>No data.</em></p>'
    max_v = max(v for _, v in data) or 1
    left_pad = 290
    right_pad = 80
    bar_area = max(120, width - left_pad - right_pad)
    h = height_per_bar * len(data) + 8
    rows = []
    for i, (lbl, v) in enumerate(data):
        y = i * height_per_bar + 4
        bar_len = int((v / max_v) * bar_area)
        truncated = (lbl[:label_chars] + "…") if len(lbl) > label_chars else lbl
        rows.append(
            f'<text x="{left_pad - 8}" y="{y + height_per_bar / 2 + 4}" '
            f'text-anchor="end" font-size="12" fill="#334155">{e(truncated)}</text>'
            f'<rect x="{left_pad}" y="{y + 4}" width="{bar_len}" '
            f'height="{height_per_bar - 12}" fill="{bar_color}" rx="2"/>'
            f'<text x="{left_pad + bar_len + 6}" y="{y + height_per_bar / 2 + 4}" '
            f'font-size="12" fill="#1e293b">{e(value_fmt(v))}</text>'
        )
    return (
        f'<svg class="bar-chart" viewBox="0 0 {width} {h}" '
        f'xmlns="http://www.w3.org/2000/svg" role="img">'
        + "".join(rows)
        + "</svg>"
    )


def donut_chart(data: list[tuple[str, float]], *, colors=None, size: int = 220) -> str:
    """Donut chart (single inline SVG). data sums to ~total."""
    if not data:
        return ""
    if colors is None:
        colors = ["#0f766e", "#0891b2", "#7c3aed", "#d97706", "#dc2626", "#64748b"]
    total = sum(v for _, v in data) or 1
    cx = cy = size / 2
    r = size / 2 - 6
    inner = r * 0.58
    paths = []
    angle = -90.0
    import math

    for i, (lbl, v) in enumerate(data):
        frac = v / total
        sweep = frac * 360
        a1 = math.radians(angle)
        a2 = math.radians(angle + sweep)
        x1 = cx + r * math.cos(a1)
        y1 = cy + r * math.sin(a1)
        x2 = cx + r * math.cos(a2)
        y2 = cy + r * math.sin(a2)
        xi1 = cx + inner * math.cos(a1)
        yi1 = cy + inner * math.sin(a1)
        xi2 = cx + inner * math.cos(a2)
        yi2 = cy + inner * math.sin(a2)
        large = 1 if sweep > 180 else 0
        d = (
            f"M {x1:.2f} {y1:.2f} "
            f"A {r:.2f} {r:.2f} 0 {large} 1 {x2:.2f} {y2:.2f} "
            f"L {xi2:.2f} {yi2:.2f} "
            f"A {inner:.2f} {inner:.2f} 0 {large} 0 {xi1:.2f} {yi1:.2f} Z"
        )
        paths.append(f'<path d="{d}" fill="{colors[i % len(colors)]}"/>')
        angle += sweep
    legend = []
    for i, (lbl, v) in enumerate(data):
        pct = v / total * 100
        legend.append(
            f'<div style="display:flex;align-items:center;gap:8px;font-size:13px;'
            f'margin-bottom:4px;"><span style="width:10px;height:10px;'
            f'background:{colors[i % len(colors)]};display:inline-block;'
            f'border-radius:2px;"></span>'
            f'<span style="flex:1;color:#334155;">{e(lbl)}</span>'
            f'<span style="color:#94a3b8;">{fmt_int(v)} ({pct:.1f}%)</span></div>'
        )
    return (
        f'<div style="display:flex;align-items:center;gap:24px;">'
        f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}" '
        f'xmlns="http://www.w3.org/2000/svg">'
        + "".join(paths)
        + f'<text x="{cx}" y="{cy - 6}" text-anchor="middle" font-size="13" '
        f'fill="#64748b">Total</text>'
        f'<text x="{cx}" y="{cy + 14}" text-anchor="middle" font-size="18" '
        f'font-weight="600" fill="#0f172a">{fmt_int(int(total))}</text>'
        + "</svg>"
        f'<div style="flex:1;">{"".join(legend)}</div></div>'
    )


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _read(name: str) -> pl.DataFrame:
    path = MARTS / f"{name}.parquet"
    if not path.exists():
        return pl.DataFrame()
    return pl.read_parquet(path)


def section_executive_summary(cfg: dict, profile: dict, fact: pl.DataFrame,
                              scored: pl.DataFrame, top: pl.DataFrame) -> str:
    cip = profile["identity"]["cip_code"]
    stem_set = {"45.0603", "30.4901", "30.7001", "30.7101", "30.7102", "30.7104"}
    is_stem = cip in stem_set
    branch = "STEM-OPT eligible (36-month runway)" if is_stem else "NON-STEM (12-month runway)"
    cap_only = profile["gates"].get("cap_exempt_only")
    if cap_only is None:
        cap_only = not is_stem

    fy2026 = cfg["rules"]["lottery_selection_rate_fy2026"]["value"]
    weighted_l1 = cfg["rules"]["wage_level_adjusted_selection_rate_fy2027"]["1"]
    weighted_l4 = cfg["rules"]["wage_level_adjusted_selection_rate_fy2027"]["4"]

    return f"""
    <section>
      <h2>Executive summary</h2>
      <div class="kpi-grid">
        <div class="kpi"><div class="label">CIP code</div>
          <div class="value">{e(cip)}</div>
          <div class="sub">{e(profile['identity'].get('program_name', ''))}</div></div>
        <div class="kpi"><div class="label">STEM-OPT</div>
          <div class="value" style="color:{'#047857' if is_stem else '#b91c1c'};">
            {'YES' if is_stem else 'NO'}</div>
          <div class="sub">{e(branch)}</div></div>
        <div class="kpi"><div class="label">Pipeline branch</div>
          <div class="value">{'cap-exempt first' if cap_only else 'both lanes'}</div>
          <div class="sub">gates.cap_exempt_only = {str(cap_only)}</div></div>
        <div class="kpi"><div class="label">Mart rows</div>
          <div class="value">{fmt_int(scored.height)}</div>
          <div class="sub">{fmt_int(scored.select(pl.col('employer_norm').n_unique())['employer_norm'][0]) if scored.height else 0} unique employers</div></div>
      </div>

      <div class="callout {'good' if cap_only else 'info'}">
        <strong>Strategic verdict.</strong> Because your CIP code (<code>{e(cip)}</code>)
        is not on the live SEVP STEM list, you have a 12-month OPT runway and at most
        one cap-subject lottery shot. Under the FY2027+ wage-weighted rule, an entry-level
        (Level I) cap-subject offer faces an effective selection rate of about
        <strong>{fmt_pct(weighted_l1)}</strong>
        (down from a flat {fmt_pct(fy2026)} in FY2026). A Level IV offer would be
        {fmt_pct(weighted_l4)}, but a first-job offer for a SAIS grad is almost
        always Level I or II.
        <br><br>
        The math says cap-exempt employers — universities, affiliated nonprofits,
        nonprofit research orgs — are not just preferable, they are the dominant
        realistic path. They bypass the lottery entirely. This report is structured
        around that reality.
      </div>

      {section_top_targets(top)}
    </section>
    """


def section_top_targets(top: pl.DataFrame) -> str:
    if top.is_empty():
        return ('<div class="callout warn">No employers passed all of your '
                'personal gates (target SOCs + ≥$75K + ≥MEDIUM evidence + '
                'cap-exempt-only). Try loosening <code>min_wage_floor_usd_annual</code> '
                'or expanding <code>target_socs</code>.</div>')
    rows = []
    for r in top.iter_rows(named=True):
        rows.append(f"""
          <tr>
            <td><strong>{e(r.get('employer_name'))}</strong>
                <br><small>{e(r.get('employer_group') or '')}</small></td>
            <td>{e(r.get('soc_code'))} · {e(r.get('soc_title') or '')}</td>
            <td>{e(r.get('cbsa_code') or 'off-map')}</td>
            <td><span class="branch-{e(r.get('branch'))}">{e(r.get('branch'))}</span>
                <br><small>{e(r.get('cap_exempt_subcategory'))}</small></td>
            <td class="num">{fmt_int(r.get('uscis_initial_approvals_window'))}</td>
            <td class="num">{fmt_pct(r.get('initial_approval_rate'))}</td>
            <td class="num">{fmt_money(r.get('median_wage_filed'))}</td>
            <td class="num">{realism_bar(r.get('sponsorship_realism'))}</td>
            <td class="num">{fmt_float(r.get('personal_score'), 3)}</td>
            <td><span class="tier-{e(r.get('evidence_tier'))}">
                {e(r.get('evidence_tier'))}</span></td>
          </tr>
        """)
    return f"""
      <h3>Your top targets (personal score, post all gates)</h3>
      <p class="subhead">Filtered to your target SOCs, target metros (or off-map), cap-exempt only,
      excluding staffing firms, wage ≥ ${'{:,}'.format(75000)}, evidence tier ≥ MEDIUM.</p>
      <table>
        <thead><tr>
          <th>Employer</th><th>Role</th><th>CBSA</th><th>Branch</th>
          <th>Initial approvals</th><th>Approval rate</th>
          <th>Median wage filed</th><th>Realism</th>
          <th>Personal score</th><th>Evidence</th>
        </tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    """


def section_regime_change(cfg: dict) -> str:
    levels = cfg["rules"]["wage_level_adjusted_selection_rate_fy2027"]
    fy26 = cfg["rules"]["lottery_selection_rate_fy2026"]["value"]
    data = [
        ("Level I — 1 ticket", float(levels.get("1", 0))),
        ("Level II — 2 tickets", float(levels.get("2", 0))),
        ("Level III — 3 tickets", float(levels.get("3", 0))),
        ("Level IV — 4 tickets", float(levels.get("4", 0))),
    ]
    chart = hbar_chart(
        data,
        value_fmt=lambda v: f"{v * 100:.1f}%",
        bar_color="#d97706",
        height_per_bar=28,
        label_chars=24,
    )
    return f"""
    <h2>The two regime changes that shape your odds</h2>

    <h3>1. Beneficiary-centric selection (effective FY2025)</h3>
    <p>USCIS now treats each unique beneficiary, not each registration, as a
    single lottery entry per employer. This eliminated the gaming where one
    candidate could be registered by 5+ shell employers. FY2026 was the second
    cycle under this rule; the published selection rate was
    <strong>{fmt_pct(fy26)}</strong>
    (118,660 selections out of 336,153 eligible beneficiaries).</p>

    <h3>2. Wage-weighted lottery (effective Feb 27, 2026 — applies to FY2027+ registrations)</h3>
    <p>The new rule grants more lottery entries to higher-wage offers:
    Level IV = 4 entries, Level III = 3, Level II = 2, Level I = 1. Combined
    with beneficiary-centric selection, the effective per-level selection rate
    for the FY2027 lottery (which ran in March 2026) looks like this:</p>

    {chart}

    <div class="callout warn">
      <strong>What this means for a SAIS grad.</strong> Your first offer is
      almost certainly Level I or II by DOL prevailing-wage criteria
      (no prior US work experience, no advanced specialization). That puts
      your cap-subject realistic conversion in the range of
      <strong>{fmt_pct(float(levels.get('1', 0)))}–{fmt_pct(float(levels.get('2', 0)))}</strong>
      <em>before</em> approval-rate, sample-size, and staffing-firm penalties.
      The cap-exempt path bypasses this entirely.
    </div>
    """


def section_cap_exempt_landscape(scored: pl.DataFrame) -> str:
    if scored.is_empty():
        return ""
    capex = scored.filter(pl.col("branch") == "CAP_EXEMPT")
    if capex.is_empty():
        return ""

    # Subcategory breakdown
    subcat = (
        capex.group_by("cap_exempt_subcategory")
        .agg(pl.col("uscis_initial_approvals_window").sum().alias("approvals"))
        .sort("approvals", descending=True)
    )
    subcat_data = [(r["cap_exempt_subcategory"] or "NONE",
                    float(r["approvals"] or 0)) for r in subcat.iter_rows(named=True)]
    donut = donut_chart(subcat_data)

    # Top employers by approvals (aggregated across SOC/CBSA)
    top_emp = (
        capex.group_by("employer_name")
        .agg(
            [
                pl.col("uscis_initial_approvals_window").sum().alias("approvals"),
                pl.col("lca_filings_window").sum().alias("lca"),
                pl.col("median_wage_filed").mean().alias("avg_wage"),
            ]
        )
        .filter(pl.col("approvals") > 0)
        .sort("approvals", descending=True)
        .head(25)
    )
    emp_data = [(r["employer_name"] or "?", float(r["approvals"] or 0))
                for r in top_emp.iter_rows(named=True)]
    emp_chart = hbar_chart(emp_data, bar_color="#0f766e", height_per_bar=22)

    # Top SOCs by cap-exempt approvals
    top_soc = (
        capex.group_by(["soc_code", "soc_title"])
        .agg(pl.col("uscis_initial_approvals_window").sum().alias("approvals"))
        .sort("approvals", descending=True)
        .head(20)
    )
    soc_data = [(f"{r['soc_code']} · {r['soc_title']}", float(r["approvals"] or 0))
                for r in top_soc.iter_rows(named=True)]
    soc_chart = hbar_chart(soc_data, bar_color="#0891b2", height_per_bar=22)

    return f"""
    <h2>The cap-exempt universe</h2>
    <p class="subhead">These employers bypass the lottery. They can sponsor anytime
    in the year. For a non-STEM applicant this is the main game.</p>

    <h3>Cap-exempt subcategories (initial approvals over the 4-yr window)</h3>
    {donut}

    <h3>Top 25 cap-exempt sponsors by initial approvals</h3>
    {emp_chart}

    <div class="callout note">
      <strong>Read this honestly.</strong> The top names are big medical schools
      and major research universities. For a SAIS / policy / IR grad, the actual
      hireable roles are typically <em>research analyst</em>, <em>policy associate</em>,
      <em>program manager</em>, or <em>statistician</em> positions inside those
      institutions, plus think tanks and policy nonprofits (which you should
      have populated in <code>user_profile.yaml &gt; manual_cap_exempt_orgs</code>).
    </div>

    <h3>Where the cap-exempt approvals concentrate (top 20 SOCs)</h3>
    {soc_chart}
    <p><small>Most cap-exempt approvals go to faculty, postdoc, and research-scientist
    roles — not SAIS-fit analyst roles. That's why your <em>personal_top_targets</em>
    list is short: the intersection is genuinely thin. Use this view to gauge whether
    you should broaden your SOC list (e.g., add bioinformatics-adjacent roles if your
    quant skills allow).</small></p>
    """


def section_cap_subject_reality(scored: pl.DataFrame, cfg: dict) -> str:
    cs = scored.filter(pl.col("branch") == "CAP_SUBJECT")
    if cs.is_empty():
        return ""

    target_socs = {s["code"] for s in cfg.get("target_socs", [])}
    cs_targets = cs.filter(pl.col("soc_code").is_in(list(target_socs)))

    # Wage level distribution across full cap-subject (proxy for what Level I share looks like)
    pct_l1_avg = float(cs.select(pl.col("pct_level_1").fill_null(0).mean())[0, 0] or 0)
    pct_l2_avg = float(cs.select(pl.col("pct_level_2").fill_null(0).mean())[0, 0] or 0)
    pct_l3_avg = float(cs.select(pl.col("pct_level_3").fill_null(0).mean())[0, 0] or 0)
    pct_l4_avg = float(cs.select(pl.col("pct_level_4").fill_null(0).mean())[0, 0] or 0)

    # Top cap-subject in target SOCs by realism
    top = cs_targets.sort("sponsorship_realism", descending=True).head(20)
    rows = []
    for r in top.iter_rows(named=True):
        staff = r.get("staffing_firm_flag")
        rows.append(f"""
          <tr>
            <td><strong>{e(r.get('employer_name'))}</strong>
                {' <small style="color:#dc2626;">[staffing]</small>' if staff else ''}
            </td>
            <td>{e(r.get('soc_code'))}</td>
            <td>{e(r.get('cbsa_code') or 'off-map')}</td>
            <td class="num">{fmt_int(r.get('lca_filings_window'))}</td>
            <td class="num">{fmt_int(r.get('uscis_initial_approvals_window'))}</td>
            <td class="num">{fmt_pct(r.get('initial_approval_rate'))}</td>
            <td class="num">{fmt_pct(r.get('pct_level_1'))}</td>
            <td class="num">{fmt_money(r.get('median_wage_filed'))}</td>
            <td class="num">{realism_bar(r.get('sponsorship_realism'))}</td>
            <td><span class="tier-{e(r.get('evidence_tier'))}">
                {e(r.get('evidence_tier'))}</span></td>
          </tr>
        """)

    levels = cfg["rules"]["wage_level_adjusted_selection_rate_fy2027"]
    return f"""
    <h2>Cap-subject reality check</h2>
    <p class="subhead">If you do choose to enter the lottery, these are the
    cap-subject employers most likely to convert for a SAIS-fit role. Realism
    already accounts for the wage-weighted lottery.</p>

    <div class="card">
      <strong>Cross-mart wage-level mix.</strong> Across all {fmt_int(cs.height)} cap-subject
      rows, employers' wage-level filings average:
      Level I = <strong>{fmt_pct(pct_l1_avg)}</strong> ({fmt_pct(float(levels.get('1', 0)))} effective lottery),
      Level II = <strong>{fmt_pct(pct_l2_avg)}</strong> ({fmt_pct(float(levels.get('2', 0)))}),
      Level III = <strong>{fmt_pct(pct_l3_avg)}</strong> ({fmt_pct(float(levels.get('3', 0)))}),
      Level IV = <strong>{fmt_pct(pct_l4_avg)}</strong> ({fmt_pct(float(levels.get('4', 0)))}).
      An employer who files mostly Level I is both a worse cultural signal
      and a worse lottery bet for you.
    </div>

    <h3>Top {len(rows)} cap-subject sponsors in your target SOCs</h3>
    <table>
      <thead><tr>
        <th>Employer</th><th>SOC</th><th>CBSA</th>
        <th>LCAs (4yr)</th><th>Initial approvals</th>
        <th>Approval rate</th><th>% Level I</th>
        <th>Median wage</th><th>Realism (w/ lottery)</th><th>Evidence</th>
      </tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    """


def section_red_flags(scored: pl.DataFrame) -> str:
    rf = scored.filter(
        (pl.col("lca_filings_window") >= 100)
        & (
            (pl.col("initial_approval_rate") < 0.6)
            | (pl.col("staffing_firm_flag") == True)  # noqa: E712
            | (pl.col("pct_level_1").fill_null(0.0) >= 0.5)
        )
    )
    # Aggregate to employer level
    agg = (
        rf.group_by("employer_name")
        .agg(
            [
                pl.col("lca_filings_window").sum().alias("lca"),
                pl.col("uscis_initial_approvals_window").sum().alias("approvals"),
                pl.col("initial_approval_rate").mean().alias("ar"),
                pl.col("pct_level_1").mean().alias("p1"),
                pl.col("staffing_firm_flag").any().alias("staff"),
            ]
        )
        .sort("lca", descending=True)
        .head(20)
    )
    rows = []
    for r in agg.iter_rows(named=True):
        why = []
        if r.get("staff"):
            why.append("Staffing/IT-consultancy pattern")
        if (r.get("ar") or 1) < 0.6:
            why.append("Low initial approval rate")
        if (r.get("p1") or 0) >= 0.5:
            why.append("Mostly Level I filings (entry-wage)")
        rows.append(f"""
          <tr>
            <td><strong>{e(r.get('employer_name'))}</strong></td>
            <td class="num">{fmt_int(r.get('lca'))}</td>
            <td class="num">{fmt_int(r.get('approvals'))}</td>
            <td class="num">{fmt_pct(r.get('ar'))}</td>
            <td class="num">{fmt_pct(r.get('p1'))}</td>
            <td><small>{e(' · '.join(why))}</small></td>
          </tr>
        """)
    return f"""
    <h2>Red flags — avoid or de-prioritize</h2>
    <p class="subhead">High volume + low approval rate, mostly Level I, or known
    staff-augmentation pattern. These employers will dominate naive rankings;
    your pipeline filters them out by default.</p>
    <table>
      <thead><tr><th>Employer</th><th>LCAs (4yr)</th><th>Initial approvals</th>
      <th>Approval rate</th><th>% Level I</th><th>Why flagged</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    """


def section_timing() -> str:
    return """
    <h2>When to apply</h2>

    <div class="kpi-grid" style="grid-template-columns: repeat(2, 1fr);">
      <div class="card" style="background:#ecfdf5; border-color:#a7f3d0;">
        <h3 style="margin-top:0; color:#065f46;">Cap-exempt employers — anytime</h3>
        <p>Universities, affiliated nonprofits, nonprofit research orgs,
        government research orgs can file at any point in the year. No cap, no
        lottery, no March deadline. You can convert from OPT to H-1B as soon
        as a petition is approved.</p>
        <p><strong>Action:</strong> outreach now → throughout 2026.</p>
      </div>
      <div class="card" style="background:#fef3c7; border-color:#fcd34d;">
        <h3 style="margin-top:0; color:#92400e;">Cap-subject employers — March cycle</h3>
        <p>Next registration window: <strong>March 2027</strong> (FY2028 lottery).
        Employers register candidates in mid-March; USCIS conducts the weighted
        random selection; petitions filed April–June; H-1B status starts
        October 1, 2027.</p>
        <p><strong>Action:</strong> outreach by <strong>December 2026</strong> so
        the employer has time to do internal sponsorship sign-off,
        prevailing-wage determination, and registration before the March window.</p>
      </div>
    </div>

    <p><small>The full <code>timing_calendar</code> view in <code>/data/marts/timing_calendar.csv</code>
    has a per-employer line you can join into your outreach tracker.</small></p>
    """


def section_methodology(cfg: dict) -> str:
    n_capex = cfg["dampeners"]["n_threshold_capexempt"]
    n_capsub = cfg["dampeners"]["n_threshold_capsubject"]
    return f"""
    <h2>Methodology — how realism is computed</h2>

    <h3>Sources (verified live 2026-05-27)</h3>
    <ul>
      <li><strong>DOL OFLC LCA disclosure</strong> — FY2022–FY2025 Q4 xlsx, 437,834
        certified rows. Headline employer-attestation signal (intent).</li>
      <li><strong>USCIS H-1B Employer Data Hub</strong> — FY2020–FY2023 CSVs,
        ~209K rows. Initial Approvals = "new sponsorship" headline; Continuing is
        renewal context only.</li>
      <li><strong>BLS OEWS May 2024 metro</strong> — wage benchmarks by SOC × CBSA.</li>
      <li><strong>IPEDS HD 2023</strong> — Title-IV institutions, the
        HIGH-confidence HIGHER_ED cap-exempt seed.</li>
      <li><strong>SEC EDGAR</strong> — public-company CIK / ticker for
        parent-subsidiary entity resolution.</li>
      <li><strong>Census/OMB CBSA</strong> — county-to-metro crosswalk.</li>
      <li><strong>WARN Act</strong> — NY/MA/VA/DC scraping; layoff signal.</li>
    </ul>

    <h3>Sponsorship realism formula</h3>
    <div class="card">
      <strong>Cap-exempt</strong> (no lottery):<br>
      <code>realism = approval_rate × min(1, approvals/{n_capex}) × (1 − staffing) × (1 − layoff)</code>
      <br><br>
      <strong>Cap-subject</strong> (FY2027+ wage-weighted lottery applies):<br>
      <code>realism = approval_rate × Σ(pct_levelL × lottery_rateL) × min(1, approvals/{n_capsub}) × (1 − staffing) × (1 − layoff)</code>
    </div>

    <h3>Why LCA-only rankings are misleading</h3>
    <ul>
      <li>An LCA is a <em>wage attestation</em>, not a petition. Employers file
        speculative or bulk LCAs that never become petitions.</li>
      <li>USCIS Hub measures actual petition decisions, but mixes Initial
        (new) and Continuing (renewal) — only Initial matters for an OPT-to-H-1B job seeker.</li>
      <li>Cap-subject petitions also need to win the lottery to matter.
        Pre-2025 selection rates inflate badly under naive averaging.</li>
    </ul>

    <h3>Known gaps</h3>
    <ul>
      <li>Geographic coverage is curated (DC/NYC/Boston/SF/San Jose/Seattle).
        Off-map rows have <code>cbsa_code = null</code>. Expand via
        <code>geo_review.csv</code>.</li>
      <li>USCIS Hub publishes ~2 FYs behind DOL (latest is FY2023). The most
        recent DOL filings (FY2024–FY2025) will have <code>uscis_initial_approvals_window
        = null</code> because USCIS hasn't published yet.</li>
      <li>WARN scrapers exist for NY/MA/VA/DC; CA/TX/WA/NJ/IL/FL/GA are
        JS-gated and need per-state Playwright work.</li>
      <li>PERM (green-card) data is ingested but not yet wired into the
        join — <code>green_card_friendly_employers</code> view is empty.</li>
    </ul>
    """


def section_defaults(cfg: dict, profile: dict) -> str:
    weights = profile["weights"]
    gates = profile["gates"]
    rows = [
        ("n_threshold_capexempt", cfg["dampeners"]["n_threshold_capexempt"],
         "Initial approvals required before cap-exempt realism reaches full credit"),
        ("n_threshold_capsubject", cfg["dampeners"]["n_threshold_capsubject"],
         "Initial approvals required before cap-subject realism reaches full credit"),
        ("window_years_lca / uscis", f"{cfg['windows']['window_years_lca']} / {cfg['windows']['window_years_uscis']}",
         "Sponsorship window spans the FY2025 regime change"),
        ("lottery_selection_rate_fy2026", cfg["rules"]["lottery_selection_rate_fy2026"]["value"],
         "Flat (pre-wage-weighted) selection rate from 118,660 / 336,153"),
        ("wage_level lottery entries", "L1:1 / L2:2 / L3:3 / L4:4",
         "From 90 FR 2025-23853, effective 2026-02-27"),
        ("w_realism", weights["w_realism"], "Personal-score weight on sponsorship realism (dominant)"),
        ("w_fit", weights["w_fit"], "Weight on SOC fit"),
        ("w_wage", weights["w_wage"], "Weight on wage adequacy (above $75K floor)"),
        ("w_metro", weights["w_metro"], "Weight on metro preference"),
        ("w_demand", weights["w_demand"], "Weight on demand signal (currently placeholder)"),
        ("w_layoff (penalty)", weights["w_layoff"], "Subtractive penalty for recent WARN"),
        ("min_wage_floor_usd_annual", gates["min_wage_floor_usd_annual"],
         "Hard filter for personal_top_targets view"),
        ("exclude_staffing_firms", gates["exclude_staffing_firms"],
         "Filter out IT staffing / body shops"),
        ("min_evidence_tier", gates["min_evidence_tier"],
         "Suppress LOW-evidence rows from headline view"),
    ]
    body = "".join(
        f"<tr><td><code>{e(k)}</code></td><td class='num'>{e(v)}</td>"
        f"<td><small>{e(why)}</small></td></tr>"
        for k, v, why in rows
    )
    return f"""
    <h2>Configuration reference (locked defaults)</h2>
    <p class="subhead">Edit these in <code>config.yaml</code> /
    <code>user_profile.yaml</code> and re-run <code>python run.py</code>.</p>
    <table>
      <thead><tr><th>Knob</th><th>Value</th><th>Rationale</th></tr></thead>
      <tbody>{body}</tbody>
    </table>
    """


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def build_report(out_path: Path | None = None) -> Path:
    cfg = load_config()
    profile = load_user_profile()
    fact = _read("mart_fact")
    scored = _read("mart_scored")
    top = _read("personal_top_targets")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    title = "US Labor Market × H-1B Sponsorship — Personal Targeting Report"

    body = "".join(
        [
            f'<header><h1>{e(title)}</h1>'
            f'<p class="subhead">Generated {e(now)} from real DOL OFLC + USCIS '
            f'Employer Hub + BLS OEWS + IPEDS data. Window: FY2022–FY2025 (DOL), '
            f'FY2020–FY2023 (USCIS).</p></header>',
            section_executive_summary(cfg, profile, fact, scored, top),
            section_regime_change(cfg),
            section_cap_exempt_landscape(scored),
            section_cap_subject_reality(scored, cfg),
            section_red_flags(scored),
            section_timing(),
            section_methodology(cfg),
            section_defaults(cfg, profile),
            '<footer>Generated by h1b-labor-map pipeline · '
            'data/marts/report.html · re-run via <code>python run.py --stage report</code></footer>',
        ]
    )

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{e(title)}</title>
<style>{CSS}</style>
</head>
<body>
{body}
</body>
</html>
"""

    out = out_path or (MARTS / "report.html")
    out.write_text(html_doc, encoding="utf-8")
    _log.info("wrote report -> %s", out)
    return out
