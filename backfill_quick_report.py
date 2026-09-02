#!/usr/bin/env python3
"""Quick Report backfill: 2025-05 gap + 2026-09"""
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
FIRM_RE = re.compile(r"🏢\s*(.+?)\s*\|")
SHEET_BATCH = 500


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

    # Scan 2025-05 to 2025-06 (the gap period)
    # iter_messages from oldest to newest, stop when we pass 2025-06-30
    print("\n🔍 Scanning 2025-05 ~ 2025-06...")
    rows_dict = {}
    scanned = 0
    async for msg in client.iter_messages(entity, reverse=True):
        kst = msg.date.astimezone(tz)
        if kst.year == 2024 or (kst.year == 2025 and kst.month < 5):
            continue
        if kst.year == 2025 and kst.month > 6:
            break

        scanned += 1
        if not is_pdf_message(msg):
            continue
        if msg.id in existing_ids:
            continue

        text = normalize_leading(msg.message)
        tag, title, firm, bullets = parse_quick_report(text)
        if not title:
            title = extract_pdf_filename(msg) or f"quick_report_{msg.id}.pdf"
        tg_link = f"https://t.me/quick_report/{msg.id}"
        date_str = kst.strftime("%Y-%m-%d")

        key = (date_str, title)
        if key not in rows_dict or msg.id < rows_dict[key]["msg_id"]:
            rows_dict[key] = {
                "msg_id": msg.id, "date": date_str, "tag": tag,
                "title": title, "firm": firm, "tg_link": tg_link,
                "summary": bullets,
            }

        if scanned % 1000 == 0:
            elapsed = time.time() - t0
            rate = scanned / elapsed if elapsed > 0 else 0
            print(f"  ... {scanned} scanned, {len(rows_dict)} PDFs ({rate:.0f} msg/s)", flush=True)

    # Upload 2025-05~06 batch
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
                  "title": r["title"], "firm": r["firm"], "tg_link": r["tg_link"],
                  "summary": r["summary"]} for r in sorted_rows]
        vault.insert_items("quick_report_items", items, "msg_id")
        total_uploaded += len(sorted_rows)
        print(f"  📤 2025-05~06: {len(sorted_rows)} rows uploaded (up to row {last_row})")

    elapsed = time.time() - t0
    print(f"\n🎉 BACKFILL COMPLETE in {elapsed:.0f}s")
    print(f"   Total uploaded: {total_uploaded} rows")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(run())
