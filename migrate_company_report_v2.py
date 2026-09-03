import sys, time
sys.path.insert(0, ".")
from shared.gsheets import get_sheet, ensure_sheet_capacity
from datetime import datetime
from zoneinfo import ZoneInfo

SHEET_ID = "19Q3KNbFu0ftr2hAqEdNwhf_UQvYXiXa2Vvk8lv9S6JY"
TAB = "<데이터>[주식] 증권사 리포트"


def main():
    ws = get_sheet(SHEET_ID, TAB)
    vals = ws.get_all_values()
    print(f"📊 Total rows: {len(vals)}")

    new_rows = []
    for idx, row in enumerate(vals):
        if idx == 0:
            new_rows.append(["날짜", "분류", "제목", "요약", "링크"])
            continue
        if not row or not any((c or "").strip() for c in row[:7]):
            new_rows.append([""] * 5)
            continue

        old_date = row[0] if len(row) > 0 else ""
        old_tag = row[1] if len(row) > 1 else ""
        old_title = row[3] if len(row) > 3 else ""
        old_summary = row[4] if len(row) > 4 else ""
        old_link = row[6] if len(row) > 6 else ""

        new_rows.append([old_date, old_tag, old_title, old_summary, old_link])

        if (idx + 1) % 5000 == 0:
            print(f"  Processed {idx + 1} rows...")

    print(f"📝 Prepared {len(new_rows)} rows for upload")

    batch_size = 5000
    for start in range(0, len(new_rows), batch_size):
        end = min(start + batch_size, len(new_rows))
        batch = new_rows[start:end]
        row_start = start + 1
        row_end = end
        rng = f"A{row_start}:E{row_end}"
        ensure_sheet_capacity(ws, row_end)
        ws.update(rng, batch, value_input_option="RAW")
        print(f"✅ Uploaded rows {row_start}-{row_end}")
        if end < len(new_rows):
            time.sleep(2)

    now = datetime.now(ZoneInfo("Asia/Seoul"))
    date_str = f"{now.year}. {now.month}. {now.day}"
    metadata = [
        ["레퍼런스 소스 정보", ""],
        ["분류", "텔레그램([주식] 증권사 리포트)"],
        ["링크", "https://t.me/companyreport"],
        ["최종 업데이트일", date_str],
    ]
    ws.update("G2:H5", metadata, value_input_option="RAW")
    print("✅ Metadata panel restored (G2:H5)")

    print("🎉 Migration complete!")


if __name__ == "__main__":
    main()
