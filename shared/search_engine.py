from datetime import datetime
from zoneinfo import ZoneInfo


def get_sheet_stats(sheet_id: str, sheet_tab: str) -> dict:
    """Read row count and latest date directly from a Google Sheet tab."""
    from shared.gsheets import get_sheet
    ws = get_sheet(sheet_id, sheet_tab)
    vals = ws.get_all_values()
    data_rows = [row for row in vals[1:] if any((c or "").strip() for c in row)]
    count = len(data_rows)
    last_date = ""
    for row in reversed(data_rows):
        d = (row[0] if row else "").strip()
        if d:
            last_date = d
            break
    return {"count": count, "last_date": last_date, "ok": True}


def update_status_panel(ws, sources: dict, tz_name: str = "Asia/Seoul"):
    """Write structured monitoring table to H2:K9 of Search Engine tab."""
    now = datetime.now(ZoneInfo(tz_name)).strftime("%Y-%m-%d %H:%M")
    labels = {
        "docpool": "<데이터>소중한추억",
        "papers": "<데이터>Papers",
        "company_report": "<데이터>[주식] 증권사 리포트",
        "quick_report": "<데이터>Quick Report",
        "smic": "SMIC 리포트",
    }
    rows = [
        ["레퍼런스 업데이트 현황", "", "", ""],
        ["소스", "최근 날짜", "상태", "행 수"],
    ]
    for name, info in sources.items():
        label = labels.get(name, name)
        status = "OK" if info.get("ok") else "ERR"
        count = info.get("count", 0)
        last = info.get("last_date", "")
        rows.append([label, last, status, f"{count:,}"])
    rows.append([f"마지막 실행: {now} KST", "", "", ""])

    ws.update("H2:K10", rows, value_input_option="RAW")


def search_keyword(ws, keyword: str = "", source: str = "",
                   date_from: str = "", date_to: str = "") -> list:
    """Search across all data rows in Search Engine tab with optional filters."""
    all_vals = ws.batch_get(["A4:G100000"])[0]
    results = []
    kw = keyword.lower() if keyword else ""
    for row in all_vals:
        if not row or not any((c or "").strip() for c in row):
            continue

        row_source = row[6] if len(row) > 6 else ""
        row_date = row[1] if len(row) > 1 else ""

        # Source filter
        if source and source not in (row_source or ""):
            continue

        # Date range filter
        if date_from or date_to:
            try:
                dt = datetime.strptime(row_date, "%Y. %m. %d")
                if date_from and dt < datetime.strptime(date_from, "%Y-%m-%d"):
                    continue
                if date_to and dt > datetime.strptime(date_to, "%Y-%m-%d"):
                    continue
            except (ValueError, TypeError):
                if date_from or date_to:
                    continue

        # Keyword filter
        if kw:
            row_text = " ".join(str(c) for c in row).lower()
            if kw not in row_text:
                continue

        results.append({
            "id": row[0] if len(row) > 0 else "",
            "date": row_date,
            "classification": row[2] if len(row) > 2 else "",
            "name": row[3] if len(row) > 3 else "",
            "link": row[4] if len(row) > 4 else "",
            "notes": row[5] if len(row) > 5 else "",
            "source": row_source,
        })

    return results


def print_search_stats(results: list):
    """Print search result statistics by source and date range."""
    if not results:
        print("  No results found.")
        return

    from collections import Counter
    source_counts = Counter(r["source"] for r in results)
    dates = [r["date"] for r in results if r["date"]]

    print(f"\n  📊 Total: {len(results)} results")
    print(f"  📁 By source:")
    for src, cnt in source_counts.most_common():
        print(f"    {src}: {cnt}")
    if dates:
        print(f"  📅 Date range: {min(dates)} ~ {max(dates)}")


def extract_keywords(name: str) -> str:
    import re
    stop = {"기업", "산업", "증권", "리포트", "주식", "review", "preview", "global", "the",
            "이슈", "코멘트", "daily", "weekly", "morning", "talk", "issue"}
    base = re.sub(r"\.pdf$", "", name or "", flags=re.I)
    parts = [p for p in re.split(r"[_\-\s]+", base.lower()) if p and len(p) >= 2 and p not in stop and not p.isdigit()]
    return " ".join(parts[:12])
