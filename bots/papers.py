import re, asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from telethon.tl.types import MessageMediaDocument, DocumentAttributeFilename

from shared.config import load_config
from shared.vault import Vault
from shared.gsheets import get_sheet
from shared.telegram_client import ensure_connected
from shared.notify import send_telegram_chunked, build_schedule_text

LEADING_JUNK = re.compile(r"^[\u200B-\u200F\u202A-\u202E\u2060-\u2069\ufeff\s\r\n\t]+", re.S)


def normalize_leading(s):
    if not s:
        return ""
    return LEADING_JUNK.sub("", s)


def is_pdf_message(msg):
    if isinstance(msg.media, MessageMediaDocument):
        doc = getattr(msg.media, "document", None)
        mime = getattr(doc, "mime_type", "") or ""
        if mime.lower() == "application/pdf":
            return True
        for attr in getattr(doc, "attributes", []):
            fn = getattr(attr, "file_name", None)
            if fn and fn.lower().endswith(".pdf"):
                return True
    if msg.message and ".pdf" in msg.message.lower():
        return True
    return False


def guess_title(msg):
    text = normalize_leading(msg.message).strip()
    if text:
        return text
    if isinstance(msg.media, MessageMediaDocument):
        doc = getattr(msg.media, "document", None)
        if doc is not None:
            for attr in getattr(doc, "attributes", []):
                fn = getattr(attr, "file_name", None)
                if fn:
                    return fn
    return "No title"


async def run():
    cfg = load_config()
    bc = cfg.bots.get("papers")
    if not bc:
        print("❌ papers config not found")
        return

    vault = Vault(cfg.timezone)
    run_id = vault.start_run("papers")

    print("🚀 [Papers] Bot starting...")

    ws = get_sheet(cfg.sheet_id, bc.sheet_tab)
    state = vault.get_state("papers")
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
                m = re.search(r"t\.me/DTpapers/(\d+)", row[3])
                if m:
                    fallback_ids.add(int(m.group(1)))
        sheet_last_id = max(fallback_ids) if fallback_ids else 0

    start_id = sheet_last_id if sheet_last_id > 0 else 0
    print(f"📊 start_id={start_id}, latest={latest_msg_id}")

    rows_dict = {}
    async for msg in client.iter_messages(entity, min_id=start_id, limit=bc.iter_limit, reverse=True):
        if not is_pdf_message(msg):
            continue
        title = guess_title(msg)
        tg_link = f"https://t.me/DTpapers/{msg.id}"
        kst_dt = msg.date.astimezone(ZoneInfo(cfg.timezone))
        date_str = kst_dt.strftime("%Y-%m-%d")

        key = (date_str, title)
        if key not in rows_dict or msg.id < rows_dict[key]["msg_id"]:
            rows_dict[key] = {"msg_id": msg.id, "date": date_str, "message": title, "links": tg_link}

    sorted_rows = sorted(rows_dict.values(), key=lambda r: (r["date"], r["msg_id"]))
    upload_data = [[r["date"], "", r["message"], r["links"]] for r in sorted_rows]

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
        ws.update(f"A{next_row}:D{end_row}", upload_data, value_input_option="RAW")
        print(f"✅ Sheet updated: A{next_row}:D{end_row}")

        max_id = max(r["msg_id"] for r in sorted_rows)
        vault.set_state("papers", max_id, sorted_rows[-1]["date"])
        items = [{"msg_id": r["msg_id"], "date": r["date"], "title": r["message"],
                  "tg_link": r["links"]} for r in sorted_rows]
        vault.insert_items("papers_items", items, "msg_id")
        vault.finish_run(run_id, "ok", len(upload_data))

        schedule_text, seq = build_schedule_text(cfg.schedule_hours, cfg.timezone)
        now = datetime.now(ZoneInfo(cfg.timezone))
        time_tag = f"{now.month}/{now.day} {now.strftime('%H:%M')}"
        seq_title = f"{seq}회차" if seq > 0 else "수시"
        header = f"📚 [{time_tag} | {seq_title}] Papers Update\nNew: {len(upload_data)} items\n{'=' * 20}\n[Schedule]\n{schedule_text}\n{'=' * 20}\n\n"
        lines = []
        for idx, r in enumerate(sorted_rows[:30], 1):
            clean = r["message"][:35] + "..." if len(r["message"]) > 35 else r["message"]
            lines.append(f"{idx}. [{r['date']}] <a href='{r['links']}'>{clean}</a>")
        send_telegram_chunked(header + "\n".join(lines), cfg)

    except Exception as e:
        print(f"❌ Error: {e}")
        vault.finish_run(run_id, "fail", detail=str(e))


if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    asyncio.run(run())
