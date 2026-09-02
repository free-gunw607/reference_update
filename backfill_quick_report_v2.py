#!/usr/bin/env python3
"""Quick Report backfill: batch fetch missing PDFs by ID"""
import re, asyncio, sys, os, time
from datetime import datetime
from zoneinfo import ZoneInfo
from telethon.tl.types import MessageMediaDocument, DocumentAttributeFilename

os.chdir("/home/liam2/agent-coding/agent-projects/A4-worker-repos/reference_update")
sys.path.insert(0, ".")
from shared.config import load_config
from shared.vault import Vault
from shared.gsheets import get_sheet
from telethon import TelegramClient
from telethon.sessions import StringSession

LEADING_JUNK = re.compile(r"^[\u200B-\u200F\u202A-\u202E\u2060-\u2069\ufeff\s\r\n\t]+", re.S)
TAG_RE = re.compile(r"^📋\s*\[(.*?)\]")
TITLE_RE = re.compile(r"^📋\s*\[.*?\]\s*(.+)")
SHEET_BATCH = 500
BATCH_SIZE = 5000


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
    tag, title = "", ""
    m_tag = TAG_RE.search(text)
    if m_tag:
        tag = m_tag.group(1).strip()
    m_title = TITLE_RE.search(text)
    if m_title:
        title = m_title.group(1).strip()
    return tag, title


async def run():
    cfg = load_config()
    bc = cfg.bots.get("quick_report")
    vault = Vault(cfg.timezone)

    print("🚀 [Quick Report] BACKFILL starting...")

    ws = get_sheet(cfg.sheet_id, bc.sheet_tab)

    # Load existing IDs
    print("📋 Loading existing IDs...")
    vals = ws.get_all_values()
    existing_ids = set()
    last_row = 0
    for idx, row in enumerate(vals, 1):
        if any((c or "").strip() for c in row[:4]):
            last_row = idx
        if len(row) > 3 and row[3]:
            m = re.search(r"t\.me/quick_report/(\d+)", row[3])
            if m:
                existing_ids.add(int(m.group(1)))
    del vals
    print(f"  Existing IDs: {len(existing_ids)}, Last row: {last_row}")

    client = TelegramClient(StringSession(cfg.session_string), cfg.api_id, cfg.api_hash)
    await client.start()
    entity = await client.get_entity("https://t.me/quick_report")

    tz = ZoneInfo(cfg.timezone)
    total_uploaded = 0
    t0 = time.time()

    # Build list of IDs to check (1 to 6000, excluding existing)
    all_ids = [i for i in range(1, 6001) if i not in existing_ids]
    print(f"  IDs to check: {len(all_ids)}")

    rows_dict = {}
    scanned = 0

    for batch_start in range(0, len(all_ids), BATCH_SIZE):
        batch_ids = all_ids[batch_start:batch_start + BATCH_SIZE]
        try:
            msgs = await client.get_messages(entity, ids=batch_ids)
        except Exception as e:
            print(f"  ⚠️ Batch error: {e}, retrying in 5s...")
            await asyncio.sleep(5)
            msgs = await client.get_messages(entity, ids=batch_ids)

        if not isinstance(msgs, list):
            msgs = [msgs]

        for msg in msgs:
            if not msg:
                continue
            scanned += 1
            if not is_pdf_message(msg):
                continue

            text = normalize_leading(msg.message)
            tag, title = parse_quick_report(text)
            if not title:
                title = extract_pdf_filename(msg) or f"quick_report_{msg.id}.pdf"
            tg_link = f"https://t.me/quick_report/{msg.id}"
            kst_dt = msg.date.astimezone(tz)
            date_str = kst_dt.strftime("%Y-%m-%d")

            key = (date_str, title)
            if key not in rows_dict or msg.id < rows_dict[key]["msg_id"]:
                rows_dict[key] = {
                    "msg_id": msg.id, "date": date_str, "tag": tag,
                    "title": title, "tg_link": tg_link, "summary": "",
                }

        if scanned % 5000 == 0:
            elapsed = time.time() - t0
            rate = scanned / elapsed if elapsed > 0 else 0
            print(f"  ... {scanned}/{len(all_ids)} checked, {len(rows_dict)} PDFs ({rate:.0f}/s)", flush=True)

    # Upload
    if rows_dict:
        sorted_rows = sorted(rows_dict.values(), key=lambda r: (r["date"], r["msg_id"]))
        upload_data = [[r["date"], r["tag"], r["title"], r["tg_link"], r["summary"]] for r in sorted_rows]
        next_row = last_row + 1
        for i in range(0, len(upload_data), SHEET_BATCH):
            batch = upload_data[i:i + SHEET_BATCH]
            end_row = next_row + len(batch) - 1
            ws.update(range_name=f"A{next_row}:E{end_row}", values=batch, value_input_option="RAW")
            last_row = end_row
            next_row = end_row + 1
        items = [{"msg_id": r["msg_id"], "date": r["date"], "tag": r["tag"],
                  "title": r["title"], "tg_link": r["tg_link"],
                  "summary": r["summary"]} for r in sorted_rows]
        vault.insert_items("quick_report_items", items, "msg_id")
        total_uploaded += len(sorted_rows)
        print(f"  📤 Uploaded {len(sorted_rows)} rows (up to row {last_row})")

    elapsed = time.time() - t0
    print(f"\n🎉 BACKFILL COMPLETE in {elapsed:.0f}s")
    print(f"   Total uploaded: {total_uploaded} rows")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(run())
