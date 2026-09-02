#!/usr/bin/env python3
"""Re-sort DOC_POOL sheet: restore header + sort by date + dedup"""
import re, sys, os
from datetime import datetime

os.chdir("/home/liam2/agent-coding/agent-projects/A4-worker-repos/reference_update")
sys.path.insert(0, ".")
from shared.gsheets import get_sheet

SHEET_ID = "19Q3KNbFu0ftr2hAqEdNwhf_UQvYXiXa2Vvk8lv9S6JY"
TAB = "<데이터>소중한추억"
HEADER = ["날짜", "", "파일명", "텔레그램 링크", "요약", "레퍼런스 소스 정보"]

def parse_date(s):
    s = (s or "").strip()
    for fmt in ("%Y. %m. %d", "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None

def run():
    ws = get_sheet(SHEET_ID, TAB)
    print("📥 Reading all data...")
    vals = ws.get_all_values()
    print(f"  Total rows: {len(vals)}")

    # All rows are data (header was overwritten)
    data_rows = vals

    # Parse and sort by date, then by ID
    parsed = []
    for row in data_rows:
        if not any((c or "").strip() for c in row[:4]):
            continue
        date = parse_date(row[0])
        # Extract ID from link for secondary sort
        link = row[3] if len(row) > 3 else ""
        mid = 0
        m = re.search(r"t\.me/DOC_POOL/(\d+)", link)
        if m:
            mid = int(m.group(1))
        parsed.append((date, mid, row))

    parsed.sort(key=lambda x: (x[0] or datetime.min.date(), x[1]))

    # Dedup by link
    seen = set()
    deduped = []
    for date, mid, row in parsed:
        link = row[3] if len(row) > 3 else ""
        if link and link in seen:
            continue
        if link:
            seen.add(link)
        # Normalize: keep only cols A-E
        clean = [row[0] if len(row) > 0 else "",
                 row[1] if len(row) > 1 else "",
                 row[2] if len(row) > 2 else "",
                 row[3] if len(row) > 3 else "",
                 row[4] if len(row) > 4 else ""]
        deduped.append(clean)

    print(f"  Deduped rows: {len(deduped)}")

    # Build sheet: header + data
    sheet_data = [HEADER] + deduped
    print(f"  Writing {len(sheet_data)} rows...")

    # Write in batches - use wide range to clear leftover columns
    BATCH = 20000
    # First, clear extra columns in one go
    clear_rows = len(sheet_data)
    blank = [[""] * 12 for _ in range(clear_rows)]
    ws.update(range_name=f"A1:L{clear_rows}", values=blank, value_input_option="RAW")
    print(f"  Cleared columns F-L")

    for i in range(0, len(sheet_data), BATCH):
        batch = sheet_data[i:i + BATCH]
        start_row = i + 1
        end_row = start_row + len(batch) - 1
        ws.update(range_name=f"A{start_row}:F{end_row}", values=batch, value_input_option="RAW")
        print(f"    Written rows {start_row}-{end_row}")

    print(f"\n✅ Done: {len(deduped)} rows sorted by date")


if __name__ == "__main__":
    run()
