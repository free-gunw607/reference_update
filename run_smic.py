#!/usr/bin/env python3
"""SMIC bot - no Drive upload, just PDF URLs"""
import re, sys, os, time
from datetime import datetime
from zoneinfo import ZoneInfo

os.chdir("/home/liam2/agent-coding/agent-projects/A4-worker-repos/reference_update")
sys.path.insert(0, ".")
from shared.config import load_config
from shared.vault import Vault
from shared.gsheets import get_sheet
from shared.notify import send_telegram_chunked
from bots.smic import scrape_smic_latest


def run():
    cfg = load_config()
    bc = cfg.bots.get("smic")
    vault = Vault(cfg.timezone)
    run_id = vault.start_run("smic")
    print("🚀 [SMIC] Starting...")

    ws = get_sheet(cfg.sheet_id, bc.sheet_tab)

    # Get existing URLs from sheet
    vals = ws.get_all_values()
    existing_urls = set()
    last_row = 0
    for idx, row in enumerate(vals, 1):
        if any((c or "").strip() for c in row[:5]):
            last_row = idx
        e = row[4] if len(row) > 4 else ""
        if e and "http" in str(e):
            m = re.search(r"https?://\S+", str(e))
            if m:
                existing_urls.add(m.group(0).rstrip("|"))
    print(f"  Existing URLs: {len(existing_urls)}, Last row: {last_row}")

    # Scrape
    print("  Scraping...")
    t0 = time.time()
    all_items = scrape_smic_latest(bc.iter_limit)
    print(f"  Total items: {len(all_items)} ({time.time()-t0:.0f}s)")

    new_items = [x for x in all_items if x.article_url and x.article_url not in existing_urls]
    new_items.sort(key=lambda x: (x.publish_date, x.report_title))
    print(f"  New items: {len(new_items)}")

    if not new_items:
        print("  No new data")
        vault.finish_run(run_id, "ok", 0)
        return

    # Build rows (no Drive upload)
    main_rows = []
    for x in new_items:
        links = x.pdf_url or x.article_url
        note = f"{x.report_title} | {x.article_url}"
        main_rows.append([x.publish_date, "Equity Research", x.company_name, links, note])

    # Upload in batches
    BATCH = 100
    for i in range(0, len(main_rows), BATCH):
        batch = main_rows[i:i + BATCH]
        ws.insert_rows(batch, row=2, value_input_option="RAW")
        print(f"  Uploaded batch {i//BATCH + 1}: {len(batch)} rows")

    # Save to vault
    for x in new_items:
        vault.conn.execute(
            "INSERT OR IGNORE INTO smic_items (article_url, publish_date, company_name, pdf_url, first_seen_at) VALUES (?, ?, ?, ?, ?)",
            (x.article_url, x.publish_date, x.company_name, x.pdf_url, vault.now_iso()),
        )
    vault.conn.commit()
    vault.set_state("smic", len(new_items), new_items[-1].publish_date)
    vault.finish_run(run_id, "ok", len(main_rows))

    now = datetime.now(ZoneInfo(cfg.timezone))
    msg = f"📈 [{now.strftime('%m/%d %H:%M')}] SMIC Update\nNew: {len(main_rows)} items"
    send_telegram_chunked(msg, cfg)
    print(f"✅ Done: {len(main_rows)} items")


if __name__ == "__main__":
    run()
