#!/usr/bin/env python3
"""Deduplicate sheets by keeping only the latest row per unique ID."""
import sys
sys.path.insert(0, "/home/liam2/agent-coding/agent-projects/A4-worker-repos/reference_update")

import re
from shared.gsheets import get_sheet

SHEET_ID = "19Q3KNbFu0ftr2hAqEdNwhf_UQvYXiXa2Vvk8lv9S6JY"

SHEETS = [
    {
        "tab": "<데이터>[주식] 증권사 리포트",
        "name": "Company Report",
        "pattern": r"/url/(\d+)",
        "col": 3,
    },
    {
        "tab": "<데이터>Papers",
        "name": "Papers",
        "pattern": r"t\.me/DTpapers/(\d+)",
        "col": 3,
    },
    {
        "tab": "<데이터>Quick Report",
        "name": "Quick Report",
        "pattern": r"t\.me/quick_report/(\d+)",
        "col": 3,
    },
    {
        "tab": "<데이터>소중한추억",
        "name": "DOC_POOL",
        "pattern": r"t\.me/DOC_POOL/(\d+)",
        "col": 3,
    },
]


def dedup_sheet(tab, name, pattern):
    print(f"\n{'='*50}")
    print(f"Deduplicating: {name} ({tab})")
    ws = get_sheet(SHEET_ID, tab)
    vals = ws.get_all_values()
    header = vals[0]
    rows = vals[1:]
    print(f"  Before: {len(rows)} rows")

    # Find the ID column by matching the pattern
    id_col = None
    for i, h in enumerate(header):
        if re.search(pattern, str(h)):
            id_col = i
            break
    if id_col is None:
        # Try to find by scanning data rows
        for row in rows[:5]:
            for i, cell in enumerate(row):
                if re.search(pattern, str(cell)):
                    id_col = i
                    break
            if id_col is not None:
                break

    if id_col is None:
        print(f"  WARNING: Could not find ID column for pattern {pattern}")
        return

    # Dedup: keep last occurrence per ID
    seen = {}
    for row in rows:
        if len(row) > id_col:
            m = re.search(pattern, str(row[id_col]))
            if m:
                rid = int(m.group(1))
                seen[rid] = row

    deduped = list(seen.values())
    # Sort by ID ascending
    id_col_final = None
    for i, h in enumerate(header):
        if "date" in str(h).lower() or "날짜" in str(h):
            id_col_final = i
            break
    if id_col_final is not None:
        deduped.sort(key=lambda r: r[id_col_final] if len(r) > id_col_final else "")

    print(f"  After: {len(deduped)} rows (removed {len(rows) - len(deduped)} duplicates)")

    # Rebuild sheet
    new_vals = [header] + deduped
    ws.clear()
    ws.resize(rows=len(new_vals))
    ws.update(range_name="A1", values=new_vals)
    print(f"  ✅ Sheet updated")


if __name__ == "__main__":
    for s in SHEETS:
        dedup_sheet(s["tab"], s["name"], s["pattern"])
    print("\n🎉 All sheets deduplicated!")
