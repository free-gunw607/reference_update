#!/usr/bin/env python3
"""Refresh Search Engine tab from all source tabs (unified A~E columns)"""
import re, sys, os, argparse
from datetime import datetime
from zoneinfo import ZoneInfo

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ".")
from shared.config import load_config
from shared.gsheets import get_sheet

SHEET_ID = "19Q3KNbFu0ftr2hAqEdNwhf_UQvYXiXa2Vvk8lv9S6JY"

# All sources now share: A=날짜, B=구분, C=제목, D=링크, E=요약/비고
SOURCES = [
    {"tab": "<데이터>소중한추억", "label": "<데이터>소중한추억"},
    {"tab": "<데이터>Papers", "label": "<데이터>Papers"},
    {"tab": "<데이터>[주식] 증권사 리포트", "label": "<데이터>[주식] 증권사 리포트"},
    {"tab": "<데이터>Quick Report", "label": "<데이터>Quick Report"},
    {"tab": "SMIC 리포트", "label": "SMIC 리포트"},
]

SE_HEADER = ["", "Date", "분류", "리포트 명", "링크", "비고", "Search Engine"]


def normalize_date(s):
    s = (s or "").strip()
    if not s:
        return ""
    for fmt in ("%Y. %m. %d", "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y. %m. %d")
        except ValueError:
            pass
    return s


def run(args=None):
    cfg = load_config()
    se_ws = get_sheet(SHEET_ID, cfg.search_engine_tab)

    source_filter = None
    date_from = None
    date_to = None
    if args:
        source_filter = getattr(args, "source", None)
        date_from = getattr(args, "date_from", None)
        date_to = getattr(args, "date_to", None)

    print("🔄 Refreshing Search Engine data...")

    all_rows = []
    for src in SOURCES:
        if source_filter and source_filter not in src["tab"]:
            continue
        print(f"  Reading {src['tab']}...")
        try:
            ws = get_sheet(SHEET_ID, src["tab"])
            vals = ws.get_all_values()
            count = 0
            for row in vals[1:]:
                if len(row) < 3:
                    continue
                date_raw = row[0]
                date = normalize_date(date_raw)
                if not date:
                    continue

                # Date range filter
                if date_from or date_to:
                    try:
                        dt = datetime.strptime(date, "%Y. %m. %d")
                        if date_from and dt < datetime.strptime(date_from, "%Y-%m-%d"):
                            continue
                        if date_to and dt > datetime.strptime(date_to, "%Y-%m-%d"):
                            continue
                    except ValueError:
                        pass

                classification = (row[1] or "").strip()
                name = (row[2] or "").strip()
                link = (row[3] or "").strip()
                note = (row[4] or "").strip() if len(row) > 4 else ""

                if not name and not link:
                    continue

                all_rows.append({
                    "date": date,
                    "classification": classification,
                    "name": name,
                    "link": link,
                    "note": note,
                    "source": src["label"],
                })
                count += 1
            print(f"    → {count} rows")
        except Exception as e:
            print(f"    ⚠️ Error: {e}")

    # Sort by date descending (newest first)
    all_rows.sort(key=lambda r: r["date"], reverse=True)

    # No dedup - keep all rows
    print(f"\n  Total rows: {len(all_rows)}")

    # Build sheet data
    sheet_data = [SE_HEADER]
    for i, r in enumerate(all_rows, 1):
        sheet_data.append([
            f"C{i}",
            r["date"],
            r["classification"],
            r["name"],
            r["link"],
            r["note"],
            r["source"],
        ])

    print(f"  Writing {len(sheet_data)} rows...")
    BATCH = 20000
    for i in range(0, len(sheet_data), BATCH):
        batch = sheet_data[i:i + BATCH]
        start_row = 3 + i
        end_row = start_row + len(batch) - 1
        se_ws.update(f"A{start_row}:G{end_row}", batch, value_input_option="RAW")
        print(f"    Written rows {start_row}-{end_row}")

    print(f"\n✅ Search Engine refreshed: {len(all_rows)} rows")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=str, help="Filter by source tab name")
    parser.add_argument("--from", dest="date_from", type=str, help="Start date YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", type=str, help="End date YYYY-MM-DD")
    run(parser.parse_args())
