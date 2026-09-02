import re, asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from telethon.tl.types import MessageMediaDocument, DocumentAttributeFilename

from shared.config import load_config
from shared.vault import Vault
from shared.gsheets import get_sheet
from shared.telegram_client import ensure_connected
from shared.notify import send_telegram_chunked, send_email, build_schedule_text

LEADING_JUNK = re.compile(r"^[\u200B-\u200F\u202A-\u202E\u2060-\u2069\ufeff\s\r\n\t]+", re.S)
TAG_RE = re.compile(r"^📋\s*\[(.*?)\]")
TITLE_RE = re.compile(r"^📋\s*\[.*?\]\s*(.+)")
FIRM_RE = re.compile(r"🏢\s*(.+?)\s*\|")


def normalize_leading(s):
    return LEADING_JUNK.sub("", s) if s else ""


def is_pdf_message(msg):
    if isinstance(msg.media, MessageMediaDocument):
        doc = getattr(msg.media, "document", None)
        mime = getattr(doc, "mime_type", "") or ""
        if "pdf" in mime.lower():
            return True
        for attr in getattr(doc, "attributes", []):
            fn = getattr(attr, "file_name", None)
            if fn and fn.lower().endswith(".pdf"):
                return True
    return False


def extract_pdf_filename(msg):
    if isinstance(msg.media, MessageMediaDocument):
        attrs = getattr(msg.media.document, "attributes", []) or []
        for a in attrs:
            if isinstance(a, DocumentAttributeFilename):
                fn = (getattr(a, "file_name", "") or "").strip()
                if fn:
                    return fn
    return ""


def parse_quick_report(text):
    tag, title, firm, bullets = "", "", "", ""
    m_tag = TAG_RE.search(text)
    if m_tag:
        tag = m_tag.group(1).strip()
    m_title = TITLE_RE.search(text)
    if m_title:
        title = m_title.group(1).strip()
    m_firm = FIRM_RE.search(text)
    if m_firm:
        firm = m_firm.group(1).strip()
    bullet_lines = [line.lstrip("• ").strip() for line in text.split("\n") if line.startswith("•")]
    if bullet_lines:
        bullets = "\n".join(bullet_lines)
    return tag, title, firm, bullets


async def run():
    cfg = load_config()
    bc = cfg.bots.get("quick_report")
    if not bc:
        print("❌ quick_report config not found")
        return

    vault = Vault(cfg.timezone)
    run_id = vault.start_run("quick_report")

    print("🚀 [Quick Report] Bot starting...")

    ws = get_sheet(cfg.sheet_id, bc.sheet_tab)
    state = vault.get_state("quick_report")
    sheet_last_id = state.get("last_msg_id", 0)

    client = await ensure_connected(cfg)
    entity = await client.get_entity(bc.channel_url)
    latest_msgs = await client.get_messages(entity, limit=1)
    latest_msg_id = latest_msgs[0].id if latest_msgs else 0

    if sheet_last_id == 0:
        vals = ws.get_all_values()
        fallback_ids = set()
        for row in vals[1:]:
            if len(row) > 3 and row[3]:
                m = re.search(r"t\.me/quick_report/(\d+)", row[3])
                if m:
                    fallback_ids.add(int(m.group(1)))
        sheet_last_id = max(fallback_ids) if fallback_ids else 0

    start_id = sheet_last_id if sheet_last_id > 0 else 0
    print(f"📊 start_id={start_id}, latest={latest_msg_id}")

    rows_dict = {}
    async for msg in client.iter_messages(entity, min_id=start_id, limit=bc.iter_limit, reverse=True):
        if not is_pdf_message(msg):
            continue

        text = normalize_leading(msg.message)
        tag, title, firm, bullets = parse_quick_report(text)
        if not title:
            title = extract_pdf_filename(msg) or f"quick_report_{msg.id}.pdf"

        tg_link = f"https://t.me/quick_report/{msg.id}"
        kst_dt = msg.date.astimezone(ZoneInfo(cfg.timezone))
        date_str = kst_dt.strftime("%Y-%m-%d")

        key = (date_str, title)
        if key not in rows_dict or msg.id < rows_dict[key]["msg_id"]:
            rows_dict[key] = {
                "msg_id": msg.id, "date": date_str, "tag": tag,
                "title": title, "firm": firm, "tg_link": tg_link,
                "summary": bullets,
            }

    sorted_rows = sorted(rows_dict.values(), key=lambda r: (r["date"], r["msg_id"]))
    upload_data = [[r["date"], r["tag"], r["title"], r["tg_link"], r["summary"]] for r in sorted_rows]

    if not upload_data:
        print("💤 No new data")
        vault.finish_run(run_id, "ok", 0)
        return

    print(f"📤 Uploading {len(upload_data)} rows...")
    try:
        vals = ws.get_all_values()
        last_row = 0
        for idx, row in enumerate(vals, 1):
            if any((c or "").strip() for c in row[:4]):
                last_row = idx
        next_row = last_row + 1
        end_row = next_row + len(upload_data) - 1
        ws.update(f"A{next_row}:E{end_row}", upload_data, value_input_option="RAW")
        print(f"✅ Sheet updated: A{next_row}:E{end_row}")

        max_id = max(r["msg_id"] for r in sorted_rows)
        vault.set_state("quick_report", max_id, sorted_rows[-1]["date"])
        items = [{"msg_id": r["msg_id"], "date": r["date"], "tag": r["tag"],
                  "title": r["title"], "firm": r["firm"], "tg_link": r["tg_link"],
                  "summary": r["summary"]} for r in sorted_rows]
        vault.insert_items("quick_report_items", items, "msg_id")
        vault.finish_run(run_id, "ok", len(upload_data))

        schedule_text, seq = build_schedule_text(cfg.schedule_hours, cfg.timezone)
        now = datetime.now(ZoneInfo(cfg.timezone))
        time_tag = f"{now.month}/{now.day} {now.strftime('%H:%M')}"
        seq_title = f"{seq}회차" if seq > 0 else "수시"
        header = f"📋 [{time_tag} | {seq_title}] Quick Report Update\nNew: {len(upload_data)} items\n{'=' * 20}\n[Schedule]\n{schedule_text}\n{'=' * 20}\n\n"
        lines = []
        for idx, r in enumerate(sorted_rows, 1):
            clean = r["title"][:35] + "..." if len(r["title"]) > 35 else r["title"]
            disp = f"[{r['tag']}] {clean}" if r["tag"] else clean
            lines.append(f"{idx}. [{r['date']}] <a href='{r['tg_link']}'>{disp}</a>")
        send_telegram_chunked(header + "\n".join(lines), cfg)
        send_email("[Quick Report] New PDFs", header + "\n".join(lines), cfg)

    except Exception as e:
        print(f"❌ Error: {e}")
        vault.finish_run(run_id, "fail", detail=str(e))


if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    asyncio.run(run())
