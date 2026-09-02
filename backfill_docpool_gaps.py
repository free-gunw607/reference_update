#!/usr/bin/env python3
"""DOC_POOL gap backfill using iter_messages (more reliable)"""
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

URL_RE = re.compile(r"https?://\S+", re.I)
LEADING_JUNK = re.compile(r"^[\u200B-\u200F\u202A-\u202E\u2060-\u2069\ufeff\s\r\n\t]+", re.S)
SHEET_BATCH = 500

def normalize_leading(s):
    return LEADING_JUNK.sub("", s) if s else ""

def strip_urls_from_text(s):
    if not s: return ""
    s = URL_RE.sub(" ", s)
    s = re.sub(r"#\S+", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def is_pdf_document(msg):
    if not isinstance(msg.media, MessageMediaDocument): return False
    mime = getattr(msg.media.document, "mime_type", "") or ""
    return "pdf" in mime.lower()

def extract_pdf_filename(msg):
    if isinstance(msg.media, MessageMediaDocument):
        for a in (getattr(msg.media.document, "attributes", []) or []):
            if isinstance(a, DocumentAttributeFilename):
                fn = (getattr(a, "file_name", "") or "").strip()
                if fn: return fn
    return ""

def normalize_for_match(s):
    import unicodedata
    s = unicodedata.normalize("NFKC", (s or "").lower())
    return re.sub(r"[^0-9a-z가-힣 ]", " ", s)

def extract_title_from_summary(text):
    if not text: return ""
    m = re.search(r"(?:^|\n)\s*제목:\s*(.+)", text)
    if m: return m.group(1).strip()
    first = text.strip().splitlines()[0].strip() if text.strip() else ""
    return first if first and len(first) <= 200 else ""


GAP_RANGES = [
    (20072, 81549),
    (155561, 155800),
]


async def run():
    cfg = load_config()
    bc = cfg.bots.get("docpool")
    vault = Vault(cfg.timezone)

    print("🚀 [DOC_POOL] GAP BACKFILL starting...")

    ws = get_sheet(cfg.sheet_id, bc.sheet_tab)
    print("📋 Loading existing IDs...")
    vals = ws.get_all_values()
    existing_ids = set()
    last_row = 0
    for idx, row in enumerate(vals, 1):
        if any((c or "").strip() for c in row[:4]):
            last_row = idx
        if len(row) > 3 and row[3]:
            m = re.search(r"t\.me/DOC_POOL/(\d+)", row[3])
            if m:
                existing_ids.add(int(m.group(1)))
    del vals
    print(f"  Existing IDs: {len(existing_ids)}, Last row: {last_row}")

    client = TelegramClient(StringSession(cfg.session_string), cfg.api_id, cfg.api_hash)
    await client.start()
    entity = await client.get_entity("https://t.me/DOC_POOL")

    total_uploaded = 0
    t0 = time.time()

    for gap_start, gap_end in GAP_RANGES:
        print(f"\n🔍 Scanning gap: {gap_start} → {gap_end}")
        rows_dict = {}
        scanned = 0

        async for msg in client.iter_messages(entity, min_id=gap_start - 1, max_id=gap_end):
            scanned += 1
            if not is_pdf_document(msg):
                continue

            text = normalize_leading(msg.message)
            tg_link = f"https://t.me/DOC_POOL/{msg.id}"
            body_raw = strip_urls_from_text(text)
            kst_dt = msg.date.astimezone(ZoneInfo(cfg.timezone))
            date_str = kst_dt.strftime("%Y-%m-%d")
            pdf_name = extract_pdf_filename(msg)
            message_cell = pdf_name or extract_title_from_summary(body_raw) or f"DOC_POOL_{msg.id}.pdf"

            if msg.id in existing_ids:
                continue

            key = (date_str, normalize_for_match(message_cell))
            if key not in rows_dict or msg.id < rows_dict[key]["msg_id"]:
                rows_dict[key] = {
                    "msg_id": msg.id, "date": date_str,
                    "message": message_cell, "tg_link": tg_link,
                    "summary": body_raw,
                }

            if scanned % 5000 == 0:
                elapsed = time.time() - t0
                rate = scanned / elapsed if elapsed > 0 else 0
                print(f"  ... {scanned} scanned, {len(rows_dict)} PDFs ({rate:.0f} msg/s)", flush=True)

        # Upload remaining for this gap
        if rows_dict:
            sorted_rows = sorted(rows_dict.values(), key=lambda r: (r["date"], r["msg_id"]))
            upload_data = [[r["date"], "", r["message"], r["tg_link"], r["summary"]] for r in sorted_rows]
            next_row = last_row + 1
            for i in range(0, len(upload_data), SHEET_BATCH):
                batch = upload_data[i:i + SHEET_BATCH]
                end_row = next_row + len(batch) - 1
                ws.update(range_name=f"A{next_row}:E{end_row}", values=batch, value_input_option="RAW")
                last_row = end_row
                next_row = end_row + 1
            items = [{"msg_id": r["msg_id"], "date": r["date"], "pdf_name": r["message"],
                      "tg_link": r["tg_link"], "summary": r["summary"]} for r in sorted_rows]
            vault.insert_items("docpool_items", items, "msg_id")
            total_uploaded += len(sorted_rows)
            print(f"  📤 Uploaded {len(sorted_rows)} rows (up to row {last_row})")

        elapsed = time.time() - t0
        rate = scanned / elapsed if elapsed > 0 else 0
        print(f"  Gap done: {scanned} scanned, {len(rows_dict)} new PDFs, {rate:.0f} msg/s")

    await client.disconnect()

    vault.set_state("docpool", 205344, datetime.now(ZoneInfo(cfg.timezone)).strftime("%Y-%m-%d"))
    elapsed = time.time() - t0
    print(f"\n🎉 GAP BACKFILL COMPLETE in {elapsed:.0f}s")
    print(f"   Total uploaded: {total_uploaded} rows")
    print(f"   Sheet rows up to: {last_row}")


if __name__ == "__main__":
    asyncio.run(run())
