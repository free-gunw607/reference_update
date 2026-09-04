import io, re, json
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from shared.config import load_config
from shared.vault import Vault
from shared.gsheets import get_sheet, get_drive_service
from shared.notify import send_telegram_chunked, send_email

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
ROOT_URL = "http://snusmic.com/research/"
PAGE_URL = "http://snusmic.com/research/page/{}/"
WP_POSTS_API = "http://snusmic.com/wp-json/wp/v2/posts"


@dataclass
class SmicItem:
    publish_date: str
    company_name: str
    report_title: str
    article_url: str
    pdf_url: str


def parse_ymd(s):
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def split_company_name(full_title):
    if "," in full_title:
        return full_title.split(",")[-1].strip()
    return full_title.strip()


def clean_filename_token(s):
    return re.sub(r"[\\/*?:\"<>|]", "", s or "").strip()


def is_research_article_url(url):
    u = (url or "").strip().lower()
    return any(k in u for k in ["/equity-research", "/industry-report", "/property-research"])


def extract_pdf_url_from_html(html):
    if not html:
        return ""
    m = re.search(r'href="([^"]+\.pdf[^"]*)"', html, flags=re.IGNORECASE)
    return m.group(1).strip() if m else ""


def scrape_page_items_api(page, per_page=30):
    params = {"per_page": per_page, "page": page, "_fields": "date,link,title,content"}
    res = requests.get(WP_POSTS_API, headers=UA, params=params, timeout=20)
    res.raise_for_status()
    rows = res.json()
    out = []
    for row in rows:
        article_url = (row.get("link") or "").strip()
        if not is_research_article_url(article_url):
            continue
        full_title = BeautifulSoup((row.get("title", {}) or {}).get("rendered", "") or "", "html.parser").get_text(" ", strip=True)
        publish_date = (row.get("date") or "")[:10] or "0000-00-00"
        content_html = ((row.get("content", {}) or {}).get("rendered", "") or "")
        pdf_url = extract_pdf_url_from_html(content_html)
        out.append(SmicItem(publish_date=publish_date, company_name=split_company_name(full_title), report_title=full_title, article_url=article_url, pdf_url=pdf_url))
    return out


def scrape_page_items_html(page_url):
    res = requests.get(page_url, headers=UA, timeout=20, allow_redirects=True)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")
    posts = soup.select("article")
    out = []
    for post in posts:
        title_a = post.select_one(".uagb-post__title a") or post.select_one("a[href]")
        date_t = post.select_one("time.uagb-post__date")
        if not title_a:
            continue
        article_url = title_a.get("href", "").strip()
        if not is_research_article_url(article_url):
            continue
        full_title = title_a.get_text(strip=True)
        publish_date = "0000-00-00"
        if date_t and date_t.has_attr("datetime"):
            publish_date = date_t["datetime"][:10]
        pdf_url = ""
        try:
            p_res = requests.get(article_url, headers=UA, timeout=20)
            p_res.raise_for_status()
            p_soup = BeautifulSoup(p_res.text, "html.parser")
            btn = p_soup.select_one("a.wp-block-button__link")
            if btn:
                pdf_url = (btn.get("href") or "").strip()
        except Exception:
            pass
        out.append(SmicItem(publish_date=publish_date, company_name=split_company_name(full_title), report_title=full_title, article_url=article_url, pdf_url=pdf_url))
    return out


def scrape_smic_latest(max_pages):
    items = []
    empty_count = 0
    for p in range(1, min(max_pages, 100) + 1):
        try:
            page_items = scrape_page_items_api(page=p, per_page=30)
        except Exception:
            break
        if not page_items:
            empty_count += 1
            if empty_count >= 2:
                break
            continue
        empty_count = 0
        items.extend(page_items)
    if not items:
        for p in range(1, min(max_pages, 100) + 1):
            url = ROOT_URL if p == 1 else PAGE_URL.format(p)
            try:
                page_items = scrape_page_items_html(url)
            except Exception:
                break
            if not page_items:
                break
            items.extend(page_items)
    dedup = {}
    for x in items:
        if x.article_url and x.article_url not in dedup:
            dedup[x.article_url] = x
    return list(dedup.values())


def upload_pdf_to_drive(drive_service, pdf_url, publish_date, company_name, folder_id):
    if not pdf_url:
        return ""
    from googleapiclient.http import MediaIoBaseUpload
    res = requests.get(pdf_url, headers=UA, timeout=30)
    res.raise_for_status()
    filename = f"{publish_date}_{clean_filename_token(company_name)}.pdf"
    media = MediaIoBaseUpload(io.BytesIO(res.content), mimetype="application/pdf", resumable=False)
    file_metadata = {"name": filename, "parents": [folder_id]}
    created = drive_service.files().create(body=file_metadata, media_body=media, fields="id,webViewLink", supportsAllDrives=True).execute()
    drive_service.permissions().create(fileId=created["id"], body={"type": "anyone", "role": "reader"}, supportsAllDrives=True).execute()
    return created.get("webViewLink", "")


def run():
    cfg = load_config()
    bc = cfg.bots.get("smic")
    if not bc:
        print("❌ smic config not found")
        return

    vault = Vault(cfg.timezone)
    run_id = vault.start_run("smic")
    print("🚀 [SMIC] Bot starting...")

    ws = get_sheet(cfg.sheet_id, bc.sheet_tab)
    drive = get_drive_service()

    vals = ws.get_all_values()
    existing_urls = set()
    last_row = 0
    for idx, row in enumerate(vals, 1):
        if any((c or "").strip() for c in row[:5]):
            last_row = idx
        e = row[4] if len(row) > 4 else ""
        if e and "http" in str(e):
            m = re.search(r"https?://\S+", str(e))
            if m:
                existing_urls.add(m.group(0).rstrip("|"))

    all_items = scrape_smic_latest(bc.iter_limit)
    new_items = [x for x in all_items if x.article_url and x.article_url not in existing_urls]
    new_items.sort(key=lambda x: (x.publish_date, x.report_title))

    main_rows = []
    uploaded = 0
    for x in new_items:
        drive_link = ""
        if x.pdf_url:
            try:
                drive_link = upload_pdf_to_drive(drive, x.pdf_url, x.publish_date, x.company_name, cfg.drive_folder_id)
                uploaded += 1
            except Exception as e:
                print(f"⚠️ Drive upload failed: {x.report_title[:40]} | {e}")
        links = drive_link or x.pdf_url or x.article_url
        note = f"{x.report_title} | {x.article_url}"
        main_rows.append([x.publish_date, "Equity Research", x.company_name, links, note])

    if not main_rows:
        print("💤 No new data")
        vault.finish_run(run_id, "ok", 0)
        return

    print(f"📤 Uploading {len(main_rows)} rows...")
    try:
        from shared.gsheets import ensure_sheet_capacity
        end_row = last_row + len(main_rows)
        ensure_sheet_capacity(ws, end_row)
        start_row = last_row + 1
        end_row = start_row + len(main_rows) - 1
        ws.update(f"A{start_row}:E{end_row}", main_rows, value_input_option="RAW")
        print(f"  ✅ Appended at rows {start_row}-{end_row}")

        for x in new_items:
            vault.conn.execute(
                "INSERT OR IGNORE INTO smic_items (article_url, publish_date, company_name, pdf_url, first_seen_at) VALUES (?, ?, ?, ?, ?)",
                (x.article_url, x.publish_date, x.company_name, x.pdf_url, vault.now_iso()),
            )
        vault.conn.commit()
        vault.set_state("smic", len(new_items), new_items[-1].publish_date)
        vault.finish_run(run_id, "ok", len(main_rows))

        now = datetime.now(ZoneInfo(cfg.timezone))
        msg = f"📈 [{now.strftime('%m/%d %H:%M')}] SMIC Update\nNew: {len(main_rows)} items\nUploaded to Drive: {uploaded}"
        send_telegram_chunked(msg, cfg)
        send_email("[SMIC] New Reports", msg, cfg)

    except Exception as e:
        print(f"❌ Error: {e}")
        vault.finish_run(run_id, "fail", detail=str(e))


if __name__ == "__main__":
    run()
