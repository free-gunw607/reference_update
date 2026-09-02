#!/usr/bin/env python3
"""DOC_POOL full backfill: batched processing"""
import re, asyncio, sys, os, time
from datetime import datetime
from zoneinfo import ZoneInfo
from telethon.tl.types import MessageMediaDocument, MessageEntityUrl, MessageEntityTextUrl, DocumentAttributeFilename

os.chdir("/home/liam2/agent-coding/agent-projects/A4-worker-repos/reference_update")
sys.path.insert(0, ".")
from shared.config import load_config
from shared.vault import Vault
from shared.gsheets import get_sheet
from telethon import TelegramClient
from telethon.sessions import StringSession

URL_RE = re.compile(r"https?://\S+", re.I)
LEADING_JUNK = re.compile(r"^[\u200B-\u200F\u202A-\u202E\u2060-\u2069\ufeff\s\r\n\t]+", re.S)
BATCH_SIZE = 5000
SHEET_BATCH = 500

def normalize_leading(s):
    return LEADING_JUNK.sub("", s) if s else ""

def strip_urls_from_text(s):
    if not s: return ""
    s = URL_RE.sub(" ", s)
    s = re.sub(r"#\S+", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def extract_all_urls(text, entities, msg):
    urls = []
    if entities:
        for e in entities:
            if isinstance(e, MessageEntityUrl):
                urls.append(text[e.offset:e.offset + e.length])
            elif isinstance(e, MessageEntityTextUrl):
                if getattr(e, "url", None): urls.append(e.url)
    urls.extend(URL_RE.findall(text or ""))
    try:
        if getattr(msg, "buttons", None):
            for row in msg.buttons:
                for b in row:
                    if getattr(b, "url", None): urls.append(b.url)
    except: pass
    out, seen = [], set()
    for u in urls:
        u = u.strip().rstrip(".,);]")
        if u and u not in seen:
            seen.add(u); out.append(u)
    return out

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


async def run():
    cfg = load_config()
    bc = cfg.bots.get("docpool")
    vault = Vault(cfg.timezone)
    run_id = vault.start_run("docpool_backfill")

    print("🚀 [DOC_POOL] FULL BACKFILL starting...")
    ws = get_sheet(cfg.sheet_id, bc.sheet_tab)

    print("📋 Scanning sheet for existing IDs...")
    vals = ws.get_all_values()
    existing_ids = set()
    for row in vals[1:]:
        if len(row) > 3 and row[3]:
            m = re.search(r"t\.me/DOC_POOL/(\d+)", row[3])
            if m:
                existing_ids.add(int(m.group(1)))
    print(f"  Existing IDs: {len(existing_ids)}")

    last_row = 0
    for idx, row in enumerate(vals, 1):
        if any((c or "").strip() for c in row[:4]):
            last_row = idx
    print(f"  Last data row: {last_row}")

    # Compute start_id from existing sheet data
    start_id = 10071
    for row in vals[1:]:
        if len(row) > 3 and row[3]:
            m = re.search(r"t\.me/DOC_POOL/(\d+)", row[3])
            if m:
                mid = int(m.group(1))
                if mid > start_id:
                    start_id = mid
    del vals  # free memory

    client = TelegramClient(StringSession(cfg.session_string), cfg.api_id, cfg.api_hash)
    await client.start()

    entity = await client.get_entity("https://t.me/DOC_POOL")
    latest_msgs = await client.get_messages(entity, limit=1)
    latest_id = latest_msgs[0].id if latest_msgs else 0
    print(f"  Channel latest ID: {latest_id}")
    print(f"  Resuming from ID: {start_id}")
    rows_dict = {}
    scanned = 0
    t0 = time.time()

    # Batch processing
    for batch_start in range(start_id + 1, latest_id + 1, BATCH_SIZE):
        batch_end = min(batch_start + BATCH_SIZE - 1, latest_id)
        batch_ids = list(range(batch_start, batch_end + 1))

        msgs = await client.get_messages(entity, ids=batch_ids)
        if not isinstance(msgs, list):
            msgs = [msgs]

        for msg in msgs:
            if not msg:
                continue
            scanned += 1
            if not is_pdf_document(msg):
                continue

            text = normalize_leading(msg.message)
            urls = extract_all_urls(text, msg.entities, msg)
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

        elapsed = time.time() - t0
        rate = scanned / elapsed if elapsed > 0 else 0
        print(f"  ... scanned {scanned}/{latest_id - start_id} ({rate:.0f} msg/s), PDFs: {len(rows_dict)}", flush=True)

        # Upload accumulated rows periodically
        if len(rows_dict) >= 2000:
            sorted_rows = sorted(rows_dict.values(), key=lambda r: (r["date"], r["msg_id"]))
            upload_data = [[r["date"], "", r["message"], r["tg_link"], r["summary"]] for r in sorted_rows]
            next_row = last_row + 1
            for i in range(0, len(upload_data), SHEET_BATCH):
                batch = upload_data[i:i + SHEET_BATCH]
                end_row = next_row + len(batch) - 1
                ws.update(f"A{next_row}:E{end_row}", batch, value_input_option="RAW")
                last_row = end_row
                next_row = end_row + 1
                print(f"  📤 Uploaded batch: {len(batch)} rows (up to row {end_row})", flush=True)
            # Save to vault
            items = [{"msg_id": r["msg_id"], "date": r["date"], "pdf_name": r["message"],
                      "tg_link": r["tg_link"], "summary": r["summary"]} for r in sorted_rows]
            vault.insert_items("docpool_items", items, "msg_id")
            rows_dict = {}  # reset

    await client.disconnect()

    # Final upload
    if rows_dict:
        sorted_rows = sorted(rows_dict.values(), key=lambda r: (r["date"], r["msg_id"]))
        upload_data = [[r["date"], "", r["message"], r["tg_link"], r["summary"]] for r in sorted_rows]
        next_row = last_row + 1
        for i in range(0, len(upload_data), SHEET_BATCH):
            batch = upload_data[i:i + SHEET_BATCH]
            end_row = next_row + len(batch) - 1
            ws.update(f"A{next_row}:E{end_row}", batch, value_input_option="RAW")
            last_row = end_row
            next_row = end_row + 1
            print(f"  📤 Final batch: {len(batch)} rows (up to row {end_row})", flush=True)
        items = [{"msg_id": r["msg_id"], "date": r["date"], "pdf_name": r["message"],
                  "tg_link": r["tg_link"], "summary": r["summary"]} for r in sorted_rows]
        vault.insert_items("docpool_items", items, "msg_id")

    vault.set_state("docpool", latest_id, datetime.now(ZoneInfo(cfg.timezone)).strftime("%Y-%m-%d"))
    vault.finish_run(run_id, "ok", scanned)
    elapsed = time.time() - t0
    print(f"\n🎉 BACKFILL COMPLETE in {elapsed:.0f}s")
    print(f"   Scanned: {scanned} messages")
    print(f"   Sheet rows up to: {last_row}")

if __name__ == "__main__":
    asyncio.run(run())
