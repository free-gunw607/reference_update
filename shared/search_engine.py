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
    now = datetime.now(ZoneInfo(tz_name)).strftime("%Y-%m-%d %H:%M")
    lines = ["레퍼런스 업데이트 현황", ""]
    labels = {
        "docpool": "<데이터>소중한추억",
        "papers": "<데이터>Papers",
        "company_report": "증권사 리포트",
        "quick_report": "Quick Report",
        "smic": "SMIC 리포트",
    }
    for i, (name, info) in enumerate(sources.items(), 1):
        if info.get("paused"):
            emoji = "Paused"
        elif info.get("new"):
            emoji = "NEW"
        elif info.get("ok"):
            emoji = "OK"
        else:
            emoji = "ERR"
        label = labels.get(name, name)
        count = info.get("count", 0)
        last = info.get("last_date", "N/A")
        lines.append(f"<{i}> {label}: latest={last} | {emoji} | {count:,} rows")
    lines.append(f"\nLast run: {now} KST")
    ws.update("H2", [["\n".join(lines)]])


def search_keyword(ws, keyword: str) -> list:
    all_vals = ws.batch_get(["A4:G50000"])[0]
    results = []
    kw = keyword.lower()
    for row in all_vals:
        row_text = " ".join(str(c) for c in row).lower()
        if kw in row_text:
            results.append({
                "id": row[0] if len(row) > 0 else "",
                "date": row[1] if len(row) > 1 else "",
                "name": row[3] if len(row) > 3 else "",
                "link": row[4] if len(row) > 4 else "",
                "notes": row[5] if len(row) > 5 else "",
                "source": row[6] if len(row) > 6 else "",
            })
    return results


def extract_keywords(name: str) -> str:
    import re
    stop = {"기업", "산업", "증권", "리포트", "주식", "review", "preview", "global", "the",
            "이슈", "코멘트", "daily", "weekly", "morning", "talk", "issue"}
    base = re.sub(r"\.pdf$", "", name or "", flags=re.I)
    parts = [p for p in re.split(r"[_\-\s]+", base.lower()) if p and len(p) >= 2 and p not in stop and not p.isdigit()]
    return " ".join(parts[:12])
