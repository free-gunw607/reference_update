#!/usr/bin/env python3
"""Quick Report backfill: IDs 5743-60745 (gap between 2025-06-02 and 2026-08-03)"""
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
BATCH_SIZE = 500

MIN_ID = 5743
MAX_ID = 60745


def normalize_leading(s):
    return LEADING_JUNK.sub("", s) if s else ""


def is_pdf_message(msg):
    if isinstance(msg.media, MessageMediaDocument):
        doc = getattr(msg.media, "document", None)
        mime = getattr(doc, "mime_type", "") or ""
        if mime == "application/pdf":
            return True
        for attr in getattr(doc, "attributes", []):
            if isinstance(attr, DocumentAttributeFilename):
                if attr.file_name.lower().endswith(".pdf"):
                    return True
    return False


def extract_pdf_filename(msg):
    if isinstance(msg.media, MessageMediaDocument):
        doc = getattr(msg.media, "document", None)
        for attr in getattr(doc, "attributes", []):
            if isinstance(attr, DocumentAttributeFilename):
                if attr.file_name.lower().endswith(".pdf"):
                    return attr.file_name
    return None


def parse_quick_report(text):
    text = normalize_leading(text)
    tag = ""
    title = ""
    firm = ""
    m = TAG_RE.match(text)
    if m:
        tag = m.group(1)
    tm = TITLE_RE.match(text)
    if tm:
        title = tm.group(1).strip()
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if len(lines) > 1:
        firm = lines[1]
    return tag, title, firm, lines


async def backfill():
    cfg = load_config()
    bc = cfg.bots["quick_report"]
    vault = Vault(cfg.timezone)
    ws = get_sheet(cfg.sheet_id, bc.sheet_tab)

    print("🚀 [Quick Report] BACKFILL starting...")
    print(f"   Range: {MIN_ID} - {MAX_ID}")

    # Get existing IDs from sheet
    vals = ws.get_all_values()
    existing_ids = set()
    for row in vals[1:]:
        m = re.search(r"t\.me/quick_report/(\d+)", str(row[3]) if len(row) > 3 else "")
        if m:
            existing_ids.add(int(m.group(1)))
    print(f"   Existing IDs: {len(existing_ids)}")

    # Get IDs to backfill
    all_ids = [i for i in range(MIN_ID, MAX_ID + 1) if i not in existing_ids]
    print(f"   IDs to fetch: {len(all_ids)}")

    if not all_ids:
        print("   Nothing to backfill!")
        return

    # Connect to Telegram
    client = TelegramClient(
        StringSession(cfg.session_string),
        cfg.api_id,
        cfg.api_hash,
    )
    await client.start()
    entity = await client.get_entity(bc.channel_url)

    upload_data = []
    success = 0
    fail = 0

    for batch_start in range(0, len(all_ids), BATCH_SIZE):
        batch_ids = all_ids[batch_start:batch_start + BATCH_SIZE]
        print(f"   Fetching batch {batch_start // BATCH_SIZE + 1} ({len(batch_ids)} IDs)...")

        for mid in batch_ids:
            try:
                msgs = await client.get_messages(entity, ids=mid)
                msg = msgs[0] if msgs else None
                if not msg or not msg.message:
                    fail += 1
                    continue

                if not is_pdf_message(msg):
                    fail += 1
                    continue

                text = normalize_leading(msg.message)
                tag, title, firm, bullets = parse_quick_report(text)
                if not title:
                    title = extract_pdf_filename(msg) or f"quick_report_{msg.id}.pdf"

                tg_link = f"https://t.me/quick_report/{msg.id}"
                kst_dt = msg.date.astimezone(ZoneInfo(cfg.timezone))
                date_str = kst_dt.strftime("%Y-%m-%d")

                upload_data.append([date_str, tag, title, tg_link, firm])
                success += 1

                # Save to vault
                try:
                    vault.upsert_item(
                        "quick_report",
                        msg_id=msg.id,
                        date=date_str,
                        tag=tag,
                        title=title,
                        firm=firm,
                        tg_link=tg_link,
                        summary="",
                    )
                except Exception:
                    pass

            except Exception as e:
                fail += 1
                if "flood" in str(e).lower() or "420" in str(e):
                    print(f"   ⚠️ Flood wait, sleeping 60s...")
                    await asyncio.sleep(60)
                continue

        # Upload batch to sheet
        if upload_data:
            next_row = len(vals) + 1
            for i in range(0, len(upload_data), SHEET_BATCH):
                batch = upload_data[i:i + SHEET_BATCH]
                start_row = next_row + i
                end_row = start_row + len(batch) - 1
                ws.update(
                    range_name=f"A{start_row}:E{end_row}",
                    values=batch,
                    value_input_option="RAW",
                )
            vals = ws.get_all_values()
            print(f"   Uploaded {len(upload_data)} rows, total: {len(vals)}")
            upload_data = []

        await asyncio.sleep(1)

    await client.disconnect()
    print(f"\n✅ Backfill complete! Success: {success}, Failed: {fail}")


if __name__ == "__main__":
    asyncio.run(backfill())
