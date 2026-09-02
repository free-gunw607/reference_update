import re, asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from telethon.tl.types import MessageMediaDocument, MessageEntityUrl, MessageEntityTextUrl, DocumentAttributeFilename

from shared.config import load_config
from shared.vault import Vault
from shared.gsheets import get_sheet
from shared.telegram_client import ensure_connected
from shared.notify import send_telegram_chunked, build_schedule_text

URL_RE = re.compile(r"https?://\S+", re.I)
LEADING_JUNK = re.compile(r"^[\u200B-\u200F\u202A-\u202E\u2060-\u2069\ufeff\s\r\n\t]+", re.S)


def normalize_leading(s):
    if not s:
        return ""
    return LEADING_JUNK.sub("", s)


def strip_urls_from_text(s):
    if not s:
        return ""
    s = URL_RE.sub(" ", s)
    s = re.sub(r"#\S+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


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


def is_pdf_document(msg):
    if not isinstance(msg.media, MessageMediaDocument):
        return False
    mime = getattr(msg.media.document, "mime_type", "") or ""
    return "pdf" in mime.lower()


def extract_pdf_filename(msg):
    if isinstance(msg.media, MessageMediaDocument):
        attrs = getattr(msg.media.document, "attributes", []) or []
        for a in attrs:
            if isinstance(a, DocumentAttributeFilename):
                fn = (getattr(a, "file_name", "") or "").strip()
                if fn:
                    return fn
    return ""


def normalize_for_match(s):
    import unicodedata
    s = unicodedata.normalize("NFKC", (s or "").lower())
    return re.sub(r"[^0-9a-z가-힣 ]", " ", s)


def extract_keywords_from_filename(name):
    stop = {"기업", "산업", "증권", "리포트", "주식", "review", "preview", "global", "the",
            "이슈", "코멘트", "daily", "weekly", "morning", "talk", "issue"}
    base = re.sub(r"\.pdf$", "", name or "", flags=re.I)
    parts = [p for p in re.split(r"[_\-\s]+", normalize_for_match(base)) if p]
    return [p for p in parts if len(p) >= 2 and p not in stop and not p.isdigit()][:12]


def score_summary_candidate(text, keywords):
    if not text:
        return 0
    markers = ("제목:", "핵심 요약", "투자의견", "목표주가", "작성일:")
    if not any(m in text for m in markers):
        return 0
    nt = normalize_for_match(text)
    hits = sum(1 for k in keywords if k in nt)
    bonus = 2 if ("핵심 요약" in text and "제목:" in text) else 1
    return hits * 10 + bonus


def looks_like_summary(text):
    if not text:
        return False
    markers = ("핵심 요약", "투자의견", "목표주가", "작성일:", "제목:")
    return text.strip().startswith("**") or any(k in text for k in markers)


def extract_title_from_summary(text):
    if not text:
        return ""
    m = re.search(r"(?:^|\n)\s*제목:\s*(.+)", text)
    if m:
        return m.group(1).strip()
    first = text.strip().splitlines()[0].strip() if text.strip() else ""
    return first if first and len(first) <= 200 else ""


async def run():
    cfg = load_config()
    bc = cfg.bots.get("docpool")
    if not bc:
        print("❌ docpool config not found")
        return

    vault = Vault(cfg.timezone)
    run_id = vault.start_run("docpool")

    print("🚀 [DOC_POOL] Bot starting...")

    ws = get_sheet(cfg.sheet_id, bc.sheet_tab)

    state = vault.get_state("docpool")
    sheet_last_id = state.get("last_msg_id", 0)

    ws = get_sheet(cfg.sheet_id, bc.sheet_tab)

    client = await ensure_connected(cfg)
    entity = await client.get_entity(bc.channel_url)
    latest_msgs = await client.get_messages(entity, limit=1)
    latest_msg_id = latest_msgs[0].id if latest_msgs else 0

    # Read existing IDs from sheet as fallback when vault is empty
    if sheet_last_id == 0:
        vals = ws.get_all_values()
        fallback_ids = set()
        for row in vals[1:]:
            if len(row) > 3 and row[3]:
                m = re.search(r"t\.me/DOC_POOL/(\d+)", row[3])
                if m:
                    fallback_ids.add(int(m.group(1)))
        sheet_last_id = max(fallback_ids) if fallback_ids else 0

    start_id = sheet_last_id if sheet_last_id > 0 else 0
    print(f"📊 start_id={start_id}, latest={latest_msg_id}")

    rows_dict = {}
    async for msg in client.iter_messages(entity, min_id=start_id, limit=bc.iter_limit, reverse=True):
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
        summary_cell = body_raw

        key = (date_str, normalize_for_match(message_cell))
        if key not in rows_dict or msg.id < rows_dict[key]["msg_id"]:
            rows_dict[key] = {
                "msg_id": msg.id,
                "date": date_str,
                "message": message_cell,
                "tg_link": tg_link,
                "summary": summary_cell,
            }

    missing = [r for r in rows_dict.values() if not (r.get("summary") or "").strip()]
    if missing:
        print(f"🧩 Summary fill: {len(missing)} items")
        target_ids = set()
        for r in missing:
            mid = r["msg_id"]
            for cid in range(mid + 1, min(mid + 16, latest_msg_id + 1)):
                target_ids.add(cid)
        nearby = {}
        for i in range(0, len(target_ids), 200):
            batch = list(target_ids)[i:i + 200]
            msgs = await client.get_messages(entity, ids=batch)
            if not isinstance(msgs, list):
                msgs = [msgs]
            for m in msgs:
                if m:
                    nearby[m.id] = m

        filled = 0
        for r in missing:
            mid = r["msg_id"]
            kw = extract_keywords_from_filename(r["message"])
            best_text, best_score = "", 0
            for cid in range(mid + 1, min(mid + 16, latest_msg_id + 1)):
                cm = nearby.get(cid)
                if not cm:
                    continue
                ctext = normalize_leading(cm.message)
                sc = score_summary_candidate(ctext, kw)
                if sc > best_score:
                    best_score = sc
                    best_text = ctext
            if best_text and best_score >= 2:
                r["summary"] = best_text
                filled += 1
        print(f"✅ Summary filled: {filled}/{len(missing)}")

    sorted_rows = sorted(rows_dict.values(), key=lambda r: (r["date"], r["msg_id"]))
    upload_data = [[r["date"], "", r["message"], r["tg_link"], r["summary"]] for r in sorted_rows]

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
        vault.set_state("docpool", max_id, sorted_rows[-1]["date"])

        items = [{"msg_id": r["msg_id"], "date": r["date"], "pdf_name": r["message"],
                  "tg_link": r["tg_link"], "summary": r["summary"]} for r in sorted_rows]
        vault.insert_items("docpool_items", items, "msg_id")

        vault.finish_run(run_id, "ok", len(upload_data))

        schedule_text, seq = build_schedule_text(cfg.schedule_hours, cfg.timezone)
        now = datetime.now(ZoneInfo(cfg.timezone))
        time_tag = f"{now.month}/{now.day} {now.strftime('%H:%M')}"
        seq_title = f"{seq}회차" if seq > 0 else "수시"
        header = f"📚 [{time_tag} | {seq_title}] DOC_POOL Update\nNew: {len(upload_data)} items\n{'=' * 20}\n[Schedule]\n{schedule_text}\n{'=' * 20}\n\n"
        lines = []
        for idx, r in enumerate(sorted_rows[:30], 1):
            clean = r["message"][:35] + "..." if len(r["message"]) > 35 else r["message"]
            link = r["tg_link"]
            lines.append(f"{idx}. [{r['date']}] <a href='{link}'>{clean}</a>")
        body = header + "\n".join(lines)
        send_telegram_chunked(body, cfg)

    except Exception as e:
        print(f"❌ Error: {e}")
        vault.finish_run(run_id, "fail", detail=str(e))


if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    asyncio.run(run())
