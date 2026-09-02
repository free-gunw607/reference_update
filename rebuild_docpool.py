#!/usr/bin/env python3
"""Rebuild DOC_POOL sheet from backup + vault"""
import re, sys, os
from datetime import datetime

os.chdir("/home/liam2/agent-coding/agent-projects/A4-worker-repos/reference_update")
sys.path.insert(0, ".")
from shared.gsheets import get_sheet
from shared.vault import Vault

BACKUP_SHEET_ID = "1c-iCE2FTA6Kn9xBhwBHTXLfLQVPT4wCN2i6eJtDvCaU"
MAIN_SHEET_ID = "19Q3KNbFu0ftr2hAqEdNwhf_UQvYXiXa2Vvk8lv9S6JY"
TAB = "<데이터>소중한추억"
HEADER = ["날짜", "", "파일명", "텔레그램 링크", "요약"]

def parse_date(s):
    s = (s or "").strip()
    for fmt in ("%Y. %m. %d", "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None

def run():
    # 1. Read backup sheet
    print("📥 Reading backup sheet...")
    bws = get_sheet(BACKUP_SHEET_ID, TAB)
    bvals = bws.get_all_values()
    backup_rows = []
    for row in bvals[1:]:
        if not any((c or "").strip() for c in row[:4]):
            continue
        date = parse_date(row[0])
        link = row[3] if len(row) > 3 else ""
        mid = 0
        m = re.search(r"t\.me/DOC_POOL/(\d+)", link)
        if m:
            mid = int(m.group(1))
        clean = [row[0] if len(row) > 0 else "",
                 "",  # B empty
                 row[2] if len(row) > 2 else "",
                 row[3] if len(row) > 3 else "",
                 row[4] if len(row) > 4 else ""]
        backup_rows.append((date, mid, clean, link))
    print(f"  Backup: {len(backup_rows)} rows")

    # 2. Read vault
    print("📥 Reading vault...")
    vault = Vault("Asia/Seoul")
    c = vault.conn.cursor()
    c.execute("SELECT msg_id, date, pdf_name, tg_link, summary FROM docpool_items ORDER BY msg_id")
    vault_rows = []
    for msg_id, date_str, pdf_name, tg_link, summary in c.fetchall():
        date = parse_date(date_str)
        clean = [date_str, "", pdf_name, tg_link, summary[:200] if summary else ""]
        vault_rows.append((date, msg_id, clean, tg_link))
    print(f"  Vault: {len(vault_rows)} rows")

    # 3. Merge (backup + vault), dedup by link
    all_rows = backup_rows + vault_rows
    print(f"  Total before dedup: {len(all_rows)}")

    seen = set()
    deduped = []
    for date, mid, row, link in all_rows:
        if link and link in seen:
            continue
        if link:
            seen.add(link)
        deduped.append((date, mid, row))

    # 4. Sort by date, then by ID
    deduped.sort(key=lambda x: (x[0] or datetime.min.date(), x[1]))
    print(f"  After dedup + sort: {len(deduped)} rows")

    # 5. Build sheet data
    sheet_data = [HEADER] + [r[2] for r in deduped]
    print(f"  Writing {len(sheet_data)} rows...")

    # 6. Write to main sheet in batches
    BATCH = 20000
    for i in range(0, len(sheet_data), BATCH):
        batch = sheet_data[i:i + BATCH]
        start_row = i + 1
        end_row = start_row + len(batch) - 1
        ws = get_sheet(MAIN_SHEET_ID, TAB)
        ws.update(range_name=f"A{start_row}:E{end_row}", values=batch, value_input_option="RAW")
        print(f"    Written rows {start_row}-{end_row}")

    print(f"\n✅ DOC_POOL rebuilt: {len(deduped)} rows")


if __name__ == "__main__":
    run()
