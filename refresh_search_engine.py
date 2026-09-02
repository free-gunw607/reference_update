#!/usr/bin/env python3
"""Refresh Search Engine tab from all source tabs"""
import re, sys, os
from datetime import datetime
from zoneinfo import ZoneInfo

os.chdir("/home/liam2/agent-coding/agent-projects/A4-worker-repos/reference_update")
sys.path.insert(0, ".")
from shared.config import load_config
from shared.gsheets import get_sheet

SHEET_ID = "19Q3KNbFu0ftr2hAqEdNwhf_UQvYXiXa2Vvk8lv9S6JY"

SOURCES = [
    {
        "tab": "<데이터>소중한추억",
        "source_label": "<데이터>소중한추억",
        "date_col": 0,   # A
        "name_col": 2,   # C
        "link_col": 3,   # D
        "note_col": 4,   # E
        "date_format": "dot",  # "2025. 3. 31"
    },
    {
        "tab": "<데이터>Papers",
        "source_label": "<데이터>Papers",
        "date_col": 0,
        "name_col": 2,
        "link_col": 3,
        "note_col": -1,
        "date_format": "dot",
    },
    {
        "tab": "<데이터>[주식] 증권사 리포트",
        "source_label": "<데이터>[주식] 증권사 리포트",
        "date_col": 0,
        "name_col": 2,  # message text
        "link_col": 3,  # stockinfo7_url
        "note_col": 1,  # tag
        "date_format": "dot",
    },
    {
        "tab": "<데이터>Quick Report",
        "source_label": "<데이터>Quick Report",
        "date_col": 0,
        "name_col": 2,
        "link_col": 3,
        "note_col": 4,
        "date_format": "dot",
    },
    {
        "tab": "SMIC 리포트",
        "source_label": "SMIC 리포트",
        "date_col": 0,
        "name_col": 2,
        "link_col": 3,
        "note_col": 4,
        "date_format": "dot",
    },
]

HEADER = ["", "Date", "분류", "리포트 명", "링크", "비고", "Search Engine"]


def normalize_date(date_str, fmt="dot"):
    s = (date_str or "").strip()
    if not s:
        return ""
    # Try common formats
    for f in ("%Y. %m. %d", "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            dt = datetime.strptime(s, f)
            return dt.strftime("%Y. %m. %d")
        except ValueError:
            pass
    return s


def extract_name_from_text(text):
    if not text:
        return ""
    # Remove URLs
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"#\S+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    # Take first meaningful line
    for line in text.split("\n"):
        line = line.strip()
        if line and len(line) > 3:
            return line[:200]
    return text[:200]


def run():
    cfg = load_config()
    se_ws = get_sheet(SHEET_ID, cfg.search_engine_tab)
    print("🔄 Refreshing Search Engine data...")

    all_rows = []
    for src in SOURCES:
        print(f"  Reading {src['tab']}...")
        try:
            ws = get_sheet(SHEET_ID, src["tab"])
            vals = ws.get_all_values()
            count = 0
            for row in vals[1:]:  # skip header
                date_raw = row[src["date_col"]] if src["date_col"] < len(row) else ""
                date = normalize_date(date_raw)
                if not date:
                    continue

                name_raw = row[src["name_col"]] if src["name_col"] < len(row) else ""
                name = name_raw.strip() if src["name_col"] >= 0 else ""

                link = row[src["link_col"]] if src["link_col"] >= 0 and src["link_col"] < len(row) else ""
                link = (link or "").strip()

                note = ""
                if src["note_col"] >= 0 and src["note_col"] < len(row):
                    note = (row[src["note_col"]] or "").strip()

                if not name and not link:
                    continue

                all_rows.append({
                    "date": date,
                    "name": name,
                    "link": link,
                    "note": note,
                    "source": src["source_label"],
                })
                count += 1
            print(f"    → {count} rows")
        except Exception as e:
            print(f"    ⚠️ Error: {e}")

    # Sort by date descending
    all_rows.sort(key=lambda r: r["date"], reverse=True)

    # Dedup by link
    seen = set()
    deduped = []
    for r in all_rows:
        key = r["link"] or r["name"]
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    print(f"\n  Total rows: {len(deduped)} (deduped from {len(all_rows)})")

    # Build sheet data
    sheet_data = [HEADER]
    for i, r in enumerate(deduped, 1):
        sheet_data.append([
            f"C{i}",
            r["date"],
            "",
            r["name"],
            r["link"],
            r["note"],
            r["source"],
        ])

    print(f"  Writing {len(sheet_data)} rows...")
    # Write in batches (overwrite directly, no need to clear)
    BATCH = 20000
    for i in range(0, len(sheet_data), BATCH):
        batch = sheet_data[i:i + BATCH]
        start_row = 3 + i
        end_row = start_row + len(batch) - 1
        se_ws.update(f"A{start_row}:G{end_row}", batch, value_input_option="RAW")
        print(f"    Written rows {start_row}-{end_row}")

    print(f"\n✅ Search Engine refreshed: {len(deduped)} rows")


if __name__ == "__main__":
    run()
