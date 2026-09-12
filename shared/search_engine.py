import re
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


# Company abbreviation -> full name mapping
COMPANY_MAP = {
    "gs": "Goldman Sachs",
    "jpm": "JP Morgan",
    "jpmorgan": "JP Morgan",
    "ms": "Morgan Stanley",
    "morgan stanley": "Morgan Stanley",
    "boa": "Bank of America",
    "bofa": "Bank of America",
    "bank of america": "Bank of America",
    "ubs": "UBS",
    "cs": "Credit Suisse",
    "db": "Deutsche Bank",
    "deutsche": "Deutsche Bank",
    "barc": "Barclays",
    "barclays": "Barclays",
    "citi": "Citigroup",
    "citigroup": "Citigroup",
    "hsbc": "HSBC",
    "nomura": "Nomura",
    "daiwa": "Daiwa",
    "macquarie": "Macquarie",
    "clsa": "CLSA",
    "ubs": "UBS",
    "socgen": "Societe Generale",
    "societe generale": "Societe Generale",
    "bnp": "BNP Paribas",
    "socgen": "Societe Generale",
    "moelis": "Moelis",
    "lazard": "Lazard",
    "rbc": "Royal Bank of Canada",
    "scotiabank": "Scotiabank",
    "td": "TD Securities",
    "canaccord": "Canaccord Genuity",
    "pj": "PJ Solomon",
    "bernstein": "Sanford Bernstein",
    "alpha": "AlphaSearch",
}

# Korean company short names -> full names
KOREAN_COMPANY_MAP = {
    "삼성": "삼성전자",
    "sk": "SK하이닉스",
    "sk하이닉스": "SK하이닉스",
    "lg": "LG화학",
    "현대": "현대자동차",
    "기아": "기아",
    "네이버": "네이버",
    "카카오": "카카오",
    "셀트리온": "셀트리온",
    "삼성바이오": "삼성바이오로직스",
    "삼성생명": "삼성생명",
    "삼성물산": "삼성물산",
    "삼성증권": "삼성증권",
    "현대모비스": "현대모비스",
    "현대건설": "현대건설",
    "LG화학": "LG화학",
    "LG전자": "LG전자",
    "LG에너지솔루션": "LG에너지솔루션",
    "POSCO": "포스코",
    "포스코": "포스코",
    "한화": "한화솔루션",
    "롯데": "롯데케미칼",
    "신세계": "신세계",
    "쿠팡": "쿠팡",
    "카카오뱅크": "카카오뱅크",
    "한국전력": "한국전력",
    "KT": "KT",
    "SK텔레콤": "SK텔레콤",
    "아모레": "아모레퍼시픽",
    "CJ": "CJ제일제당",
    "LIG": "LIG손해보험",
}


def normalize_company(name: str) -> str:
    """Extract company name from report title."""
    name_lower = (name or "").lower().strip()

    # Try Korean company match first
    for short, full in KOREAN_COMPANY_MAP.items():
        if short.lower() in name_lower:
            return full

    # Try English abbreviation match
    parts = re.split(r"[_\-\s/]+", name_lower)
    for part in parts:
        if part in COMPANY_MAP:
            return COMPANY_MAP[part]

    return ""


def extract_keywords(name: str) -> str:
    """Extract searchable keywords from report title.

    Extracts: company names, abbreviations, key terms, and date references.
    """
    stop = {
        "기업", "산업", "증권", "리포트", "주식", "review", "preview", "global", "the",
        "이슈", "코멘트", "daily", "weekly", "morning", "talk", "issue", "report",
        "pdf", "summary", "note", "update", "analysis", "research", "strategy",
        "equity", "fixed", "income", "commodity", "fx", "rates",
    }

    base = re.sub(r"\.pdf$", "", name or "", flags=re.I)
    parts = [p for p in re.split(r"[_\-\s]+", base.lower()) if p and len(p) >= 2 and p not in stop and not p.isdigit()]

    # Add company name
    company = normalize_company(name)
    if company:
        parts.insert(0, company.lower())

    # Add abbreviation expansions
    for part in parts[:]:
        if part in COMPANY_MAP:
            expanded = COMPANY_MAP[part].lower()
            if expanded not in parts:
                parts.append(expanded)

    return " ".join(parts[:15])
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
    """Write structured monitoring table to H2:K10 of Search Engine tab."""
    now = datetime.now(ZoneInfo(tz_name)).strftime("%Y-%m-%d %H:%M")
    rows = [
        ["레퍼런스 업데이트 현황", "", "", ""],
        ["소스", "최근 날짜", "상태", "행 수"],
    ]
    for name, info in sources.items():
        label = info.get("tab", name)
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
    """Extract searchable keywords from report title.

    Extracts: company names, abbreviations, key terms, and date references.
    """
    stop = {
        "기업", "산업", "증권", "리포트", "주식", "review", "preview", "global", "the",
        "이슈", "코멘트", "daily", "weekly", "morning", "talk", "issue", "report",
        "pdf", "summary", "note", "update", "analysis", "research", "strategy",
        "equity", "fixed", "income", "commodity", "fx", "rates",
    }

    base = re.sub(r"\.pdf$", "", name or "", flags=re.I)
    parts = [p for p in re.split(r"[_\-\s]+", base.lower()) if p and len(p) >= 2 and p not in stop and not p.isdigit()]

    # Add company name
    company = normalize_company(name)
    if company:
        parts.insert(0, company.lower())

    # Add abbreviation expansions
    for part in parts[:]:
        if part in COMPANY_MAP:
            expanded = COMPANY_MAP[part].lower()
            if expanded not in parts:
                parts.append(expanded)

    return " ".join(parts[:15])


# ─── Search Engine v2 ───────────────────────────────────────────────

SE_V2_HEADER = ["", "Date", "분류", "리포트 명", "링크", "비고", "소스", "키워드"]


def build_search_engine_v2(cfg) -> dict:
    """Build Search Engine v2 tab from all source sheets.

    Returns: {total_rows: int, by_source: {name: count}}
    """
    from shared.gsheets import get_sheet

    se_ws = get_sheet(cfg.sheet_id, cfg.search_engine_tab_v2)
    all_rows = []
    by_source = {}

    for name, bc in cfg.bots.items():
        tab = bc.sheet_tab
        print(f"  Reading {tab}...")
        try:
            ws = get_sheet(cfg.sheet_id, tab)
            vals = ws.get_all_values()
            count = 0
            for row in vals[1:]:
                if len(row) < 3:
                    continue
                date_raw = row[0]
                date = _normalize_date(date_raw)
                if not date:
                    continue

                classification = (row[1] or "").strip()
                name_text = (row[2] or "").strip()
                link = (row[3] or "").strip()
                note = (row[4] or "").strip() if len(row) > 4 else ""

                if not name_text and not link:
                    continue

                keywords = extract_keywords(name_text)

                all_rows.append({
                    "date": date,
                    "classification": classification,
                    "name": name_text,
                    "link": link,
                    "note": note,
                    "source": tab,
                    "keywords": keywords,
                })
                count += 1
            by_source[tab] = count
            print(f"    -> {count} rows")
        except Exception as e:
            print(f"    Error: {e}")
            by_source[tab] = 0

    # Sort by date descending (newest first)
    all_rows.sort(key=lambda r: r["date"], reverse=True)

    print(f"\n  Total rows: {len(all_rows)}")

    # Build sheet data
    sheet_data = [SE_V2_HEADER]
    for i, r in enumerate(all_rows, 1):
        sheet_data.append([
            f"C{i}",
            r["date"],
            r["classification"],
            r["name"],
            r["link"],
            r["note"],
            r["source"],
            r["keywords"],
        ])

    # Write in batches of 20000
    BATCH = 20000
    # Ensure sheet has enough rows
    from shared.gsheets import ensure_sheet_capacity
    ensure_sheet_capacity(se_ws, len(sheet_data) + 10)
    for i in range(0, len(sheet_data), BATCH):
        batch = sheet_data[i:i + BATCH]
        start_row = 3 + i
        end_row = start_row + len(batch) - 1
        se_ws.update(f"A{start_row}:H{end_row}", batch, value_input_option="RAW")
        print(f"    Written rows {start_row}-{end_row}")

    print(f"\n  Search Engine v2 refreshed: {len(all_rows)} rows")
    return {"total_rows": len(all_rows), "by_source": by_source}


def search_keyword_v2(ws, keyword: str = "", source: str = "",
                      date_from: str = "", date_to: str = "") -> list:
    """Search across Search Engine v2 tab with keyword, source, and date filters."""
    all_vals = ws.batch_get(["A4:H100000"])[0]
    results = []
    kw = keyword.lower() if keyword else ""

    for row in all_vals:
        if not row or not any((c or "").strip() for c in row):
            continue

        row_source = row[6] if len(row) > 6 else ""
        row_date = row[1] if len(row) > 1 else ""
        row_keywords = row[7] if len(row) > 7 else ""

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

        # Keyword filter: search in name, keywords, and all columns
        if kw:
            searchable = " ".join(str(c) for c in row).lower()
            kw_in_keywords = kw in row_keywords.lower() if row_keywords else False
            if kw not in searchable and not kw_in_keywords:
                continue

        results.append({
            "id": row[0] if len(row) > 0 else "",
            "date": row_date,
            "classification": row[2] if len(row) > 2 else "",
            "name": row[3] if len(row) > 3 else "",
            "link": row[4] if len(row) > 4 else "",
            "notes": row[5] if len(row) > 5 else "",
            "source": row_source,
            "keywords": row_keywords,
        })

    return results


def _normalize_date(s):
    """Normalize date to 'YYYY. MM. DD' format."""
    s = (s or "").strip()
    if not s:
        return ""
    for fmt in ("%Y. %m. %d", "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y. %m. %d")
        except ValueError:
            pass
    return s
