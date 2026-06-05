"""Pipeline orchestrator.

Stages: verify -> ingest -> clean -> entity-resolve -> join -> score -> views.

Usage:
    python run.py                       # full run (downloads everything)
    python run.py --dry-run             # show plan, do nothing
    python run.py --incremental         # skip unchanged sources
    python run.py --force-refresh       # re-download everything
    python run.py --stage join          # run only join (assumes stage data exists)
    python run.py --stage score         # run scoring + views
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from src.common import (
    ensure_dirs,
    load_config,
    load_env,
    load_user_profile,
    setup_logging,
)
from src.cap_exempt import classify_dataframe
from src.entity_resolve import attach_canonical_to_df
from src.geo_normalize import attach_cbsa
from src.ingest_bls import download_oews, parse_oews_metro_zip, stage_oews
from src.ingest_census import download_cbsa, parse_cbsa, stage_cbsa
from src.ingest_dol import discover_and_download as dol_download, stage_dol_file
from src.ingest_edgar import download_edgar, parse_edgar
from src.ingest_ipeds import download_ipeds, parse_ipeds, stage_ipeds
from src.ingest_uscis import discover_and_download as uscis_download, stage_uscis_file
from src.ingest_warn import ingest_warn
from src.join import build_mart
from src.report import build_report
from src.scoring import score_mart
from src.views import build_views

console = Console()

VALID_STAGES = ["verify", "ingest", "clean", "resolve", "join", "score", "views", "report", "all"]


def _print_phase0_branch(profile: dict) -> None:
    cip = profile["identity"]["cip_code"]
    stem_codes = {"45.0603", "30.4901", "30.7001", "30.7101", "30.7102", "30.7104"}
    is_stem = cip in stem_codes
    branch = "STEM-OPT eligible (36-month runway)" if is_stem else "NON-STEM (12-month runway)"
    cap_exempt_only = profile["gates"].get("cap_exempt_only")
    if cap_exempt_only is None:
        cap_exempt_only = not is_stem

    t = Table(title="Phase 0.0 — STEM Branch")
    t.add_column("Field")
    t.add_column("Value")
    t.add_row("CIP code", cip)
    t.add_row("STEM-OPT", "YES" if is_stem else "NO")
    t.add_row("Branch", branch)
    t.add_row("cap_exempt_only", str(cap_exempt_only))
    console.print(t)


def stage_verify(args) -> None:
    cfg = load_config()
    profile = load_user_profile()
    _print_phase0_branch(profile)
    console.print(
        "\n[bold cyan]Phase 0 findings:[/bold cyan] "
        "see data/manifest/phase0_findings.md"
    )
    console.print(
        "[bold cyan]Defaults reference:[/bold cyan] "
        "see DEFAULTS REFERENCE in labor_market_h1b_map_blueprint.md"
    )


def stage_ingest(args) -> None:
    cfg = load_config()
    window_years = cfg["windows"]["window_years_lca"]
    # Most recent complete FY = current year - 1 (FY runs Oct-Sep)
    import datetime as _dt

    today = _dt.date.today()
    latest_fy_dol = today.year if today.month >= 10 else today.year - 1
    fiscal_years_dol = list(range(latest_fy_dol - window_years + 1, latest_fy_dol + 1))

    # USCIS Hub typically lags DOL by ~1-2 FY. Verified 2026-05-27: latest
    # published FY is 2023. Window slides back accordingly.
    latest_fy_uscis = 2023
    fiscal_years_uscis = list(range(latest_fy_uscis - window_years + 1, latest_fy_uscis + 1))

    console.print(f"\n[bold]DOL fiscal years:[/bold] {fiscal_years_dol}")
    console.print(f"[bold]USCIS Hub fiscal years:[/bold] {fiscal_years_uscis}  "
                  f"[dim](Hub lags DOL by ~2 yrs)[/dim]")

    # DOL LCA
    console.print("[cyan]DOL OFLC LCA...[/cyan]")
    dol_paths = dol_download(fiscal_years_dol, force=args.force_refresh, dry_run=args.dry_run)
    if not args.dry_run:
        for fy, p in dol_paths.items():
            if p and p.exists():
                try:
                    stage_dol_file(p, fy)
                except Exception as exc:  # noqa: BLE001
                    console.print(f"[red]DOL FY{fy} parse failed: {exc}[/red]")

    # USCIS Employer Hub
    console.print("[cyan]USCIS Employer Hub...[/cyan]")
    uscis_paths = uscis_download(fiscal_years_uscis, force=args.force_refresh, dry_run=args.dry_run)
    if not args.dry_run:
        for fy, p in uscis_paths.items():
            if p and p.exists():
                try:
                    stage_uscis_file(p, fy)
                except Exception as exc:  # noqa: BLE001
                    console.print(f"[red]USCIS FY{fy} parse failed: {exc}[/red]")
    latest_fy = latest_fy_dol  # used by OEWS download below

    # OEWS — latest real release is May 2024 (May 2025 returns a 25KB
    # placeholder as of 2026-05-27). Hardcode 2024 until 2025 is published.
    console.print("[cyan]BLS OEWS...[/cyan]")
    oews_year = 2024
    oews_path = download_oews(oews_year, force=args.force_refresh, dry_run=args.dry_run)
    if oews_path and not args.dry_run:
        try:
            stage_oews(oews_path, oews_year)
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]OEWS parse failed: {exc}[/red]")

    # IPEDS Title-IV institutions
    console.print("[cyan]IPEDS / DAPIP...[/cyan]")
    ip = download_ipeds(force=args.force_refresh, dry_run=args.dry_run)
    if ip and not args.dry_run:
        try:
            stage_ipeds(ip)
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]IPEDS parse failed: {exc}[/red]")

    # Census CBSA
    console.print("[cyan]Census CBSA delineation...[/cyan]")
    cb = download_cbsa(force=args.force_refresh, dry_run=args.dry_run)
    if cb and not args.dry_run:
        try:
            stage_cbsa(cb)
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]CBSA parse failed: {exc}[/red]")

    # EDGAR (entity resolution support)
    console.print("[cyan]SEC EDGAR tickers...[/cyan]")
    if not args.dry_run:
        e = download_edgar()
        if e:
            try:
                parse_edgar(e)
            except Exception as exc:  # noqa: BLE001
                console.print(f"[red]EDGAR parse failed: {exc}[/red]")

    # WARN
    console.print("[cyan]State WARN Act portals...[/cyan]")
    if not args.dry_run:
        try:
            ingest_warn()
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]WARN ingest failed: {exc}[/red]")


def stage_clean_resolve(args) -> None:
    """Apply entity-resolve and geo-normalize to staged DOL data."""
    import polars as pl

    from src.common import STAGING

    dol_files = sorted((STAGING / "dol" / "lca").glob("*.parquet"))
    if not dol_files:
        console.print("[red]No DOL staging files — skipping resolve[/red]")
        return
    for p in dol_files:
        df = pl.read_parquet(p)
        df = attach_canonical_to_df(df, employer_col="employer_name", norm_col="employer_norm")
        df = attach_cbsa(df, city_col="worksite_city", state_col="worksite_state")
        df = classify_dataframe(df)
        df.write_parquet(p)
        console.print(f"[green]resolved + normalized {p.name}[/green]")


def stage_join(args) -> None:
    build_mart()


def stage_score(args) -> None:
    score_mart()


def stage_views(args) -> None:
    build_views()


def stage_report(args) -> None:
    path = build_report()
    console.print(f"\n[bold green]Report written:[/bold green] {path}")
    console.print("Open it in a browser to view the personalized H-1B targeting analysis.")


STAGE_FNS = {
    "verify": stage_verify,
    "ingest": stage_ingest,
    "clean": stage_clean_resolve,
    "resolve": stage_clean_resolve,
    "join": stage_join,
    "score": stage_score,
    "views": stage_views,
    "report": stage_report,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="H-1B Labor Map pipeline")
    parser.add_argument(
        "--stage",
        choices=VALID_STAGES,
        default="all",
        help="Run a single stage (default: all)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--incremental", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    log = setup_logging(verbose=args.verbose)
    load_env()
    ensure_dirs()

    plan = (
        [args.stage]
        if args.stage != "all"
        else ["verify", "ingest", "clean", "join", "score", "views", "report"]
    )
    log.info("plan: %s (dry_run=%s force=%s)", plan, args.dry_run, args.force_refresh)
    start = time.time()
    for s in plan:
        log.info("=== stage: %s ===", s)
        STAGE_FNS[s](args)
    log.info("done in %.1fs", time.time() - start)
    return 0


if __name__ == "__main__":
    sys.exit(main())
