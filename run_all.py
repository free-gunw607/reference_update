import asyncio
import argparse
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from shared.config import load_config
from shared.vault import Vault
from shared.gsheets import get_sheet
from shared.search_engine import update_status_panel, get_sheet_stats


async def _run_and_disconnect(name: str):
    import importlib
    mod = importlib.import_module(f"bots.{name}")
    await mod.run()
    from shared.telegram_client import disconnect_all
    await disconnect_all()


def run_bot(name: str):
    if name == "smic":
        from bots.smic import run
        run()
    else:
        asyncio.run(_run_and_disconnect(name))


def export_excel(vault, cfg):
    import pandas as pd
    from pathlib import Path

    exports_dir = Path(__file__).parent / "exports"
    exports_dir.mkdir(exist_ok=True)
    ts = datetime.now(ZoneInfo(cfg.timezone)).strftime("%Y%m%d")
    out_path = exports_dir / f"reference_update_{ts}.xlsx"

    tables = {
        "소중한추억": "docpool_items",
        "Papers": "papers_items",
        "증권사리포트": "company_report_items",
        "Quick Report": "quick_report_items",
    }

    with pd.ExcelWriter(str(out_path), engine="openpyxl") as writer:
        for sheet_name, table in tables.items():
            try:
                rows = vault.conn.execute(f"SELECT * FROM {table}").fetchall()
                if rows:
                    cols = [d[0] for d in vault.conn.execute(f"SELECT * FROM {table} LIMIT 0").description]
                    df = pd.DataFrame([dict(r) for r in rows], columns=cols)
                else:
                    df = pd.DataFrame()
            except Exception:
                df = pd.DataFrame()
            df.to_excel(writer, sheet_name=sheet_name, index=False)

        # SMIC
        try:
            rows = vault.conn.execute("SELECT * FROM smic_items").fetchall()
            if rows:
                cols = [d[0] for d in vault.conn.execute("SELECT * FROM smic_items LIMIT 0").description]
                df = pd.DataFrame([dict(r) for r in rows], columns=cols)
            else:
                df = pd.DataFrame()
        except Exception:
            df = pd.DataFrame()
        df.to_excel(writer, sheet_name="SMIC", index=False)

    print(f"📊 Excel exported: {out_path}")
    return out_path


def update_search_engine(cfg):
    try:
        ws = get_sheet(cfg.sheet_id, cfg.search_engine_tab)
        labels = {
            "docpool": "<데이터>소중한추억",
            "papers": "<데이터>Papers",
            "company_report": "<데이터>[주식] 증권사 리포트",
            "quick_report": "<데이터>Quick Report",
            "smic": "SMIC 리포트",
        }
        sources = {}
        for name, tab in labels.items():
            try:
                info = get_sheet_stats(cfg.sheet_id, tab)
                sources[name] = {
                    "tab": tab,
                    "last_date": info.get("last_date", ""),
                    "count": info.get("count", 0),
                    "ok": True,
                }
            except Exception as e:
                sources[name] = {
                    "tab": tab, "last_date": "", "count": 0, "ok": False,
                }
        update_status_panel(ws, sources, cfg.timezone)
        print("✅ Search Engine status panel updated")
    except Exception as e:
        print(f"⚠️ Search Engine update failed: {e}")


def write_source_panels(cfg):
    """Write monitoring panels to all source sheets."""
    from shared.gsheets import write_source_panel
    sources = [
        ("<데이터>소중한추억", "https://t.me/DOC_POOL"),
        ("<데이터>Papers", "https://t.me/DTpapers"),
        ("<데이터>[주식] 증권사 리포트", "https://t.me/companyreport"),
        ("<데이터>Quick Report", "https://t.me/quick_report"),
        ("SMIC 리포트", "http://snusmic.com/research/"),
    ]
    for tab, url in sources:
        try:
            info = get_sheet_stats(cfg.sheet_id, tab)
            ws = get_sheet(cfg.sheet_id, tab)
            write_source_panel(ws, url, tab, info["last_date"], info["count"])
            print(f"  ✅ {tab}: panel updated")
        except Exception as e:
            print(f"  ⚠️ {tab}: {e}")


def build_search_engine(cfg):
    """Refresh Search Engine data from all source sheets."""
    from refresh_search_engine import run as refresh_run
    refresh_run()


def main():
    parser = argparse.ArgumentParser(description="Reference Update Bot Runner")
    parser.add_argument("--bots", type=str, default="all",
                        help="Comma-separated bot names: docpool,papers,company_report,quick_report,smic")
    parser.add_argument("--excel", action="store_true", help="Export Excel after bot run")
    parser.add_argument("--search-update", action="store_true", help="Update Search Engine status panel")
    parser.add_argument("--build-search", action="store_true", help="Rebuild Search Engine data from source sheets")
    parser.add_argument("--source-panel", action="store_true", help="Write monitoring panels to source sheets")
    parser.add_argument("--search", type=str, help="Search keyword in Search Engine")
    parser.add_argument("--source", type=str, help="Filter search by source tab")
    parser.add_argument("--from", dest="date_from", type=str, help="Search start date YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", type=str, help="Search end date YYYY-MM-DD")
    parser.add_argument("--trigger", type=str, default="cron", help="Trigger type: cron|manual|backfill")
    args = parser.parse_args()

    cfg = load_config()

    if args.search:
        from shared.search_engine import search_keyword, print_search_stats
        ws = get_sheet(cfg.sheet_id, cfg.search_engine_tab)
        results = search_keyword(ws, args.search, args.source or "", args.date_from or "", args.date_to or "")
        print(f"🔍 Search '{args.search}': {len(results)} results")
        for r in results[:30]:
            print(f"  [{r['date']}] [{r['source'][:15]}] {r['name'][:50]}")
        print_search_stats(results)
        return

    if args.bots == "all":
        bot_names = ["docpool", "papers", "company_report", "quick_report", "smic"]
    else:
        bot_names = [b.strip() for b in args.bots.split(",") if b.strip()]

    for name in bot_names:
        try:
            run_bot(name)
        except Exception as e:
            print(f"❌ Bot '{name}' failed: {e}")

    if args.excel:
        vault = Vault(cfg.timezone)
        export_excel(vault, cfg)

    if args.source_panel:
        write_source_panels(cfg)

    if args.build_search:
        build_search_engine(cfg)

    if args.search_update or args.excel:
        update_search_engine(cfg)


if __name__ == "__main__":
    main()
