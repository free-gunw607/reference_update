import re, asyncio, html as html_mod
from datetime import datetime
from zoneinfo import ZoneInfo
from telethon.tl.types import MessageEntityUrl, MessageEntityTextUrl

from shared.config import load_config
from shared.vault import Vault
from shared.gsheets import get_sheet, ensure_sheet_capacity
from shared.telegram_client import ensure_connected
from shared.notify import send_telegram_chunked, send_email, build_schedule_text

STOCKINFO_RE = re.compile(r"https?://stockinfo7\.com/stock/report/url/(\d+)", re.I)
CONSENSUS_RE = re.compile(r"https?://consensus\.hankyung\.com/\S*?report_idx=(\d+)", re.I)
URL_RE = re.compile(r"https?://\S+", re.I)
LEADING_JUNK = re.compile(r"^[\u200B-\u200F\u202A-\u202E\u2060-\u2069\ufeff\s\r\n\t]+", re.S)
BRACKET_RE = re.compile(r"\[(.*?)\]")
SKIP_COMPANY_WORDS = [
    "리서치", "증권", "리포트", "분석", "요약", "내용", "시장", "종목",
    "투자", "weekly", "daily", "brief", "live", "watch", "monitor",
    "snapshot", "letter", "update", "핵심", "요약", "개요", "현황",
    "전략", "분석가", "제목", "정보", "동향", "전망",
]


def clean_html(text):
    if not text:
        return ""
    text = html_mod.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    return text


def normalize_leading(s):
    return LEADING_JUNK.sub("", s) if s else ""


def strip_urls_from_text(s):
    if not s:
        return ""
    s = URL_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def get_report_id(text_or_url):
    if not text_or_url:
        return None
    s = str(text_or_url)
    m1 = STOCKINFO_RE.search(s)
    if m1:
        return int(m1.group(1))
    m2 = CONSENSUS_RE.search(s)
    if m2:
        return int(m2.group(1))
    return None


def detect_type_tag(text):
    if not text:
        return ""
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


def extract_all_urls(text, entities, msg):
    urls = []
    if entities:
        for e in entities:
            if isinstance(e, MessageEntityUrl):
                urls.append(text[e.offset:e.offset + e.length])
            elif isinstance(e, MessageEntityTextUrl):
                if getattr(e, "url", None):
                    urls.append(e.url)
    urls.extend(URL_RE.findall(text or ""))
    try:
        if getattr(msg, "buttons", None):
            for row in msg.buttons:
                for b in row:
                    if getattr(b, "url", None):
                        urls.append(b.url)
    except Exception:
        pass
    out, seen = [], set()
    for u in urls:
        u = u.strip().rstrip(".,);]")
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


async def run():
    cfg = load_config()
    bc = cfg.bots.get("company_report")
    if not bc:
        print("❌ company_report config not found")
        return

    vault = Vault(cfg.timezone)
    run_id = vault.start_run("company_report")

    print("🚀 [Company Report] Bot starting...")

    ws = get_sheet(cfg.sheet_id, bc.sheet_tab)
    state = vault.get_state("company_report")
    sheet_last_id = state.get("last_msg_id", 0)

    if sheet_last_id == 0:
        vals = ws.get_all_values()
        fallback_ids = set()
        for row in vals[1:]:
            if len(row) > 4 and row[4]:
                m = re.search(r"/url/(\d+)", row[4])
                if m:
                    fallback_ids.add(int(m.group(1)))
        sheet_last_id = max(fallback_ids) if fallback_ids else 0

    client = await ensure_connected(cfg)
    entity = await client.get_entity(bc.channel_url)

    rows_dict = {}
    print(f"🔍 Scanning (max {bc.iter_limit})...")

    async for msg in client.iter_messages(entity, limit=bc.iter_limit):
        text = normalize_leading(msg.message)
        text = clean_html(text)
        urls = extract_all_urls(text, msg.entities, msg)

        found_rid = None
        target_link = None
        for u in urls:
            rid = get_report_id(u)
            if rid:
                found_rid = rid
                target_link = u
                break

        if not found_rid:
            continue

        if sheet_last_id > 0 and found_rid <= sheet_last_id:
            print(f"🛑 Reached ID {sheet_last_id}")
            break

        tag = detect_type_tag(text)
        company = parse_company_name(text, tag)
        title = parse_title(text)
        summary = parse_summary(text)
        kst_dt = msg.date.astimezone(ZoneInfo(cfg.timezone))
        date_str = kst_dt.strftime("%Y-%m-%d")

        if not target_link:
            target_link = f"https://t.me/companyreport/{msg.id}"

        if found_rid not in rows_dict:
            rows_dict[found_rid] = {
                "rid": found_rid, "date": date_str, "tag": tag,
                "company": company, "title": title, "summary": summary,
                "link": target_link,
            }

    sorted_rows = sorted(rows_dict.values(), key=lambda r: r["rid"])
    upload_data = [[
        r["date"], r["tag"], r["title"], r["summary"], r["link"],
    ] for r in sorted_rows]

    if not upload_data:
        print("💤 No new data")
        vault.finish_run(run_id, "ok", 0)
        return

    print(f"📤 Uploading {len(upload_data)} rows...")
    try:
        vals = ws.get_all_values()
        last_row = 0
        for idx, row in enumerate(vals, 1):
            if any((c or "").strip() for c in row[:5]):
                last_row = idx
        next_row = last_row + 1
        end_row = next_row + len(upload_data) - 1
        ensure_sheet_capacity(ws, end_row)
        ws.update(f"A{next_row}:E{end_row}", upload_data, value_input_option="RAW")
        print(f"✅ Sheet updated: A{next_row}:E{end_row}")

        max_id = max(r["rid"] for r in sorted_rows)
        vault.set_state("company_report", max_id, sorted_rows[-1]["date"])
        items = [{"report_id": r["rid"], "date": r["date"], "tag": r["tag"],
                  "title": r["title"], "summary": r["summary"],
                  "source_url": r["link"]}
                 for r in sorted_rows]
        vault.insert_items("company_report_items", items, "report_id")
        vault.finish_run(run_id, "ok", len(upload_data))

        schedule_text, seq = build_schedule_text(cfg.schedule_hours, cfg.timezone)
        now = datetime.now(ZoneInfo(cfg.timezone))
        time_tag = f"{now.month}/{now.day} {now.strftime('%H:%M')}"
        seq_title = f"{seq}회차" if seq > 0 else "수시"
        header = f"📈 [{time_tag} | {seq_title}] Company Report Update\nNew: {len(upload_data)} items\n{'=' * 20}\n[Schedule]\n{schedule_text}\n{'=' * 20}\n\n"
        lines = []
        for idx, r in enumerate(sorted_rows, 1):
            clean = r["title"][:35] + "..." if len(r["title"]) > 35 else r["title"]
            disp = f"[{r['tag']}] {clean}" if r["tag"] else clean
            lines.append(f"{idx}. [{r['date']}] <a href='{r['link']}'>{html_mod.escape(disp)}</a>")
        send_telegram_chunked(header + "\n".join(lines), cfg)
        send_email("[Company Report] New PDFs", header + "\n".join(lines), cfg)

    except Exception as e:
        print(f"❌ Error: {e}")
        vault.finish_run(run_id, "fail", detail=str(e))


if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    asyncio.run(run())
