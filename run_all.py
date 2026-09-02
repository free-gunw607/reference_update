import asyncio
import argparse
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from shared.config import load_config
from shared.vault import Vault
from shared.gsheets import get_sheet
from shared.search_engine import update_status_panel


def run_bot(name: str):
    if name == "smic":
        from bots.smic import run
        run()
    else:
        import importlib
        mod = importlib.import_module(f"bots.{name}")
        import asyncio
        asyncio.run(mod.run())
        # Disconnect any lingering Telegram clients
        from shared.telegram_client import disconnect_all
        asyncio.run(disconnect_all())


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
        vault = Vault(cfg.timezone)
        stats = vault.get_all_source_stats()
        labels = {
            "docpool": "<데이터>소중한추억",
            "papers": "<데이터>Papers",
            "company_report": "증권사 리포트",
            "quick_report": "Quick Report",
            "smic": "SMIC 리포트",
        }
        sources = {}
        for name, info in stats.items():
            sources[name] = {
                "tab": labels.get(name, name),
                "last_date": info.get("last_date", "N/A"),
                "count": info.get("count", 0),
                "ok": info.get("ok", False),
            }
        update_status_panel(ws, sources, cfg.timezone)
        print("✅ Search Engine status panel updated")
    except Exception as e:
        print(f"⚠️ Search Engine update failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="Reference Update Bot Runner")
    parser.add_argument("--bots", type=str, default="all",
                        help="Comma-separated bot names: docpool,papers,company_report,quick_report,smic")
    parser.add_argument("--excel", action="store_true", help="Export Excel after bot run")
    parser.add_argument("--search-update", action="store_true", help="Update Search Engine status panel")
    parser.add_argument("--search", type=str, help="Search keyword in Search Engine")
    parser.add_argument("--trigger", type=str, default="cron", help="Trigger type: cron|manual|backfill")
    args = parser.parse_args()

    cfg = load_config()

    if args.search:
        from shared.search_engine import search_keyword
        ws = get_sheet(cfg.sheet_id, cfg.search_engine_tab)
        results = search_keyword(ws, args.search)
        print(f"🔍 Search '{args.search}': {len(results)} results")
        for r in results[:20]:
            print(f"  [{r['date']}] {r['name'][:50]} | {r['source']}")
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

    if args.search_update or args.excel:
        update_search_engine(cfg)


if __name__ == "__main__":
    main()
