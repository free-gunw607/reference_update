import sys, html as html_mod, re, time
sys.path.insert(0, ".")
from shared.gsheets import get_sheet, ensure_sheet_capacity

SHEET_ID = "19Q3KNbFu0ftr2hAqEdNwhf_UQvYXiXa2Vvk8lv9S6JY"
TAB = "<데이터>[주식] 증권사 리포트"

SKIP_COMPANY_WORDS = [
    "리서치", "증권", "리포트", "분석", "요약", "내용", "시장", "종목",
    "투자", "weekly", "daily", "brief", "live", "watch", "monitor",
    "snapshot", "letter", "update", "핵심", "요약", "개요", "현황",
    "전략", "분석가", "제목", "정보", "동향", "전망",
]
BRACKET_RE = re.compile(r"\[(.*?)\]")


def clean_html(text):
    if not text:
        return ""
    text = html_mod.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    return text


def detect_type_tag(text):
    m = re.match(r"^\[(.*?)\]", text.strip())
    return m.group(1).strip() if m else ""


def parse_company_name(text, tag):
    if tag != "기업":
        return ""
    matches = BRACKET_RE.findall(text)
    if len(matches) >= 2:
        candidate = matches[1].strip()
        if candidate and not any(w in candidate.lower() for w in SKIP_COMPANY_WORDS):
            return candidate
    return ""


def parse_title(text):
    cleaned = BRACKET_RE.sub("", text).strip()
    if ";" in cleaned:
        return cleaned.split(";", 1)[0].strip()
    idx = cleaned.find("📌")
    if idx > 0:
        return cleaned[:idx].strip()
    m = re.match(r"^(.+?[.!?])\s", cleaned)
    if m:
        return m.group(1).strip()
    return cleaned[:80] if len(cleaned) > 80 else cleaned


def parse_summary(text):
    cleaned = BRACKET_RE.sub("", text).strip()
    if ";" in cleaned:
        summary = cleaned.split(";", 1)[1].strip()
    else:
        idx = cleaned.find("📌")
        summary = cleaned[idx:].strip() if idx > 0 else cleaned
    summary = re.sub(r"🔗\s*원문보기\s*$", "", summary).strip()
    return summary


def main():
    ws = get_sheet(SHEET_ID, TAB)
    vals = ws.get_all_values()
    print(f"📊 Total rows: {len(vals)}")

    new_rows = []
    for idx, row in enumerate(vals):
        if idx == 0:
            new_rows.append(["날짜", "분류", "회사명", "제목", "요약", "리포트ID", "링크"])
            continue
        if not row or not any((c or "").strip() for c in row[:4]):
            new_rows.append(row[:7] if len(row) >= 7 else row + [""] * (7 - len(row)))
            continue

        old_date = row[0] if len(row) > 0 else ""
        old_tag = row[1] if len(row) > 1 else ""
        old_msg = row[2] if len(row) > 2 else ""
        old_link = row[3] if len(row) > 3 else ""

        cleaned = clean_html(old_msg)
        tag = detect_type_tag(cleaned) or old_tag.strip()
        company = parse_company_name(cleaned, tag)
        title = parse_title(cleaned)
        summary = parse_summary(cleaned)

        m = re.search(r"/url/(\d+)", old_link)
        report_id = m.group(1) if m else ""

        new_rows.append([old_date, tag, company, title, summary, report_id, old_link])

        if (idx + 1) % 5000 == 0:
            print(f"  Processed {idx + 1} rows...")

    print(f"📝 Prepared {len(new_rows)} rows for upload")

    batch_size = 5000
    for start in range(0, len(new_rows), batch_size):
        end = min(start + batch_size, len(new_rows))
        batch = new_rows[start:end]
        row_start = start + 1
        row_end = end
        rng = f"A{row_start}:G{row_end}"
        ensure_sheet_capacity(ws, row_end)
        ws.update(rng, batch, value_input_option="RAW")
        print(f"✅ Uploaded rows {row_start}-{row_end}")
        if end < len(new_rows):
            time.sleep(2)

    print("🎉 Migration complete!")


if __name__ == "__main__":
    main()
