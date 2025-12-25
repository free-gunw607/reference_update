import os, sys, re, json, asyncio, requests, time
from datetime import datetime
from zoneinfo import ZoneInfo
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaDocument, MessageEntityUrl, MessageEntityTextUrl
import gspread
from google.oauth2.service_account import Credentials

# =========================================================
# [설정] 인증 정보 및 상수
# =========================================================
API_ID = 23502096
API_HASH = "99c1d3f16735873c768f0580a8a6ca58"
SESSION_STRING = "1BVtsOIgBu3Y9HkCwppiILxPqdDwi7Oea8W-GiEJAEN7bbwM3_yMholc0An7WgvDTvUDgwO1yfNLcgYzu-wIehxN7qJJFw6Qk_99gSdwxI-ICytLFNVVVPFfcddntiGTgHABh9w1ZQmf5vKQ0cnKvl88mkRf2MweGbpfvgyzDszb0dMRs0yLctB1fOOFP7m2PtAUDEqJuhmmTs4FIxiyyKBwnVf41rwXx7_Ulm7t1beHE7LnY_m2yS0s3xDtN7maBBfWcrHYA2FAHLMwCvg3l9k-z4xTbJ_SFf85wA9bErkDeM22zpiTNTeD5uwdlVLUzanH87sXVCivPCYl5BkWk9zx8yIO5O-g="

CHANNEL_URL = "https://t.me/DOC_POOL"
GSHEET_ID = "19Q3KNbFu0ftr2hAqEdNwhf_UQvYXiXa2Vvk8lv9S6JY"
GSHEET_TAB = "<데이터>소중한추억"
TZ_NAME = "Asia/Seoul"

# [핵심] 로컬 코드처럼 최대 10,000개까지 넉넉하게 수집
ITER_LIMIT = 10000 

# 알림용 토큰 로드
try:
    TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
    MY_CHAT_ID = os.environ.get('MY_CHAT_ID')
except:
    TELEGRAM_TOKEN = None
    MY_CHAT_ID = None

# 정규식
URL_RE = re.compile(r'https?://\S+', re.I)
PDF_URL_RE = re.compile(r'https?://\S+\.pdf(\b|$)', re.I)
ID_RE = re.compile(r'(\d+)(?=(?:\.pdf\b|/?$))')
LEADING_JUNK = re.compile(r'^[\u200B-\u200F\u202A-\u202E\u2060-\u2069\ufeff\s\r\n\t]+', re.S)

# =========================================================
# [기능 1] 텔레그램 스마트 알림 (동적 시간 제목 + 꽉 채우기)
# =========================================================
def send_telegram_smart(new_rows):
    if not TELEGRAM_TOKEN or not MY_CHAT_ID:
        return

    # 1. 현재 한국 시간 구하기 (예: 12/25 14:00)
    now = datetime.now(ZoneInfo(TZ_NAME))
    time_tag = f"{now.month}/{now.day} {now.strftime('%H:%M')}"

    # 2. 제목에 시간 박아넣기
    total_count = len(new_rows)
    header = f"📚 <b>[{time_tag} 소중한추억] 업데이트</b>\n신규 리포트: {total_count}건\n{'='*20}\n\n"
    
    # 텔레그램 메시지 한계 (안전하게 4000자)
    MAX_LENGTH = 4000
    current_msg = header
    
    # 리스트 순회
    for idx, row in enumerate(new_rows, 1):
        # row: [date, "", message, links]
        date_str = row[0]
        title = row[2]
        links_str = row[3]

        # 제목 HTML 이스케이프 및 길이 제한
        clean_title = title.replace("<", "&lt;").replace(">", "&gt;") 
        if len(clean_title) > 35: 
            clean_title = clean_title[:35] + "..."
            
        # 첫 번째 링크 추출
        target_link = ""
        if links_str:
            first_link = links_str.split(',')[0].strip()
            if first_link.startswith("http"):
                target_link = first_link
        
        # 한 줄 생성
        if target_link:
            line = f"{idx}. [{date_str}] <a href='{target_link}'>{clean_title}</a>\n"
        else:
            line = f"{idx}. [{date_str}] {clean_title}\n"
            
        # [스마트 분할 로직]
        if len(current_msg) + len(line) > MAX_LENGTH:
            _send_chunk(current_msg)
            # 다음 메시지 헤더 (이어짐 표시)
            current_msg = f"📚 <b>[이어짐] ({idx}번부터~)</b>\n\n" + line
        else:
            current_msg += line
            
    # 남은 내용 발송
    if current_msg:
        _send_chunk(current_msg)

def _send_chunk(text):
    """실제 전송 함수"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        r = requests.post(url, data={'chat_id': MY_CHAT_ID, 'text': text, 'parse_mode': 'HTML'})
        time.sleep(1)
    except Exception as e:
        print(f"❌ 전송 실패: {e}")

# =========================================================
# [기능 2] 중복 제거 로직 (로컬 코드 완벽 이식)
# =========================================================
def normalize_for_dedup(msg_text: str) -> str:
    if not msg_text: return ""
    s = msg_text
    s = re.sub(r'^Preview page\s+\d+\s+of\s+', '', s, flags=re.IGNORECASE)
    s = re.sub(r'#\S+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def dedup_insert(row_dict, row):
    # 키: (날짜, 정규화된 내용)
    key = (row["date"], normalize_for_dedup(row["message"]))
    prev = row_dict.get(key)
    # 기존에 없거나, 현재 ID가 더 작으면(원본에 가까우면) 업데이트
    if (prev is None) or (row["msg_id"] < prev["msg_id"]):
        row_dict[key] = row

# =========================================================
# [기능 3] 구글 시트 유틸 (빈 행 무시 + 전체 ID 스캔)
# =========================================================
def get_gsheet_client():
    if 'GDRIVE_CREDS' not in os.environ:
        sys.exit(1)
    creds_dict = json.loads(os.environ['GDRIVE_CREDS'])
    creds = Credentials.from_service_account_info(
        creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return gspread.authorize(creds)

def extract_report_ids_from_text(text):
    if not text: return set()
    ids = set()
    for part in str(text).split(","):
        m = ID_RE.search(part.strip())
        if m: ids.add(int(m.group(1)))
    return ids

def find_last_data_row(vals):
    last = 0
    for idx, row in enumerate(vals, start=1):
        if any((c or "").strip() for c in row[:4]):
            last = idx
    return last

def fetch_sheet_info(ws):
    try:
        vals = ws.get_all_values()
        if not vals: return 0, set(), 0
        
        last_row_idx = find_last_data_row(vals)
        existing_ids = set()
        max_id = 0
        
        for i in range(1, last_row_idx):
            row = vals[i]
            if len(row) > 3:
                ids = extract_report_ids_from_text(row[3])
                if ids:
                    existing_ids.update(ids)
                    max_id = max(max_id, max(ids))
        return max_id, existing_ids, last_row_idx
    except Exception as e:
        print(f"⚠️ 시트 읽기 실패: {e}")
        return 0, set(), 0

# =========================================================
# [기능 4] 파싱 유틸
# =========================================================
def normalize_leading(s):
    if not s: return ""
    return LEADING_JUNK.sub("", s)

def strip_urls_from_text(s):
    if not s: return ""
    s = URL_RE.sub(" ", s)
    s = re.sub(r'#\S+', ' ', s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def extract_all_urls(text, entities, msg):
    urls = []
    if entities:
        for e in entities:
            if isinstance(e, MessageEntityUrl):
                urls.append(text[e.offset:e.offset + e.length])
            elif isinstance(e, MessageEntityTextUrl):
                if getattr(e, "url", None): urls.append(e.url)
    urls.extend(URL_RE.findall(text or ""))
    out, seen = [], set()
    for u in urls:
        u = u.strip().rstrip(".,);]")
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out

def is_pdf_message(msg_text, urls, msg):
    if any(PDF_URL_RE.search(u) for u in urls): return True
    if msg_text and ".pdf" in msg_text.lower(): return True
    if isinstance(msg.media, MessageMediaDocument):
        mime = getattr(msg.media.document, "mime_type", "") or ""
        if "pdf" in mime.lower(): return True
    return False

# =========================================================
# [메인] 실행 로직
# =========================================================
async def main():
    print("🚀 [소중한추억] 업데이트 봇 가동 (Dynamic Time)...")
    
    # 1. 시트 접속
    try:
        gc = get_gsheet_client()
        ws = gc.open_by_key(GSHEET_ID).worksheet(GSHEET_TAB)
    except Exception as e:
        print(f"❌ 구글 시트 에러: {e}")
        return

    # 2. 시트 정보 로드
    last_id, existing_ids, last_row_num = fetch_sheet_info(ws)
    print(f"📊 시트 상태: Max ID={last_id}, 총 데이터={len(existing_ids)}건, 마지막 줄={last_row_num}")

    # 3. 텔레그램 접속
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.connect()
    
    entity = await client.get_entity(CHANNEL_URL)
    rows_dict = {} 
    
    print(f"🔍 스캔 시작 (기준 ID > {last_id}, 최대 {ITER_LIMIT}개)...")
    
    # 4. 수집
    async for msg in client.iter_messages(entity, min_id=last_id, limit=ITER_LIMIT, reverse=True):
        text = normalize_leading(msg.message)
        urls = extract_all_urls(text, msg.entities, msg)
        
        if not is_pdf_message(text, urls, msg):
            continue
            
        tg_link = f"https://t.me/DOC_POOL/{msg.id}"
        pdf_urls = [u for u in urls if PDF_URL_RE.search(u)]
        if pdf_urls:
            links = ", ".join([tg_link] + pdf_urls)
        else:
            links = tg_link
            
        body_raw = strip_urls_from_text(text)
        kst_dt = msg.date.astimezone(ZoneInfo(TZ_NAME))
        date_str = kst_dt.strftime("%Y-%m-%d")
        
        if msg.id in existing_ids:
            continue

        row = {
            "msg_id": msg.id,
            "date": date_str,
            "message": body_raw,
            "links": links,
        }
        
        dedup_insert(rows_dict, row)
        
        if len(rows_dict) % 50 == 0:
            print(f"  ... {len(rows_dict)}건 수집 중")

    await client.disconnect()
    
    # 5. 정렬
    sorted_rows = sorted(rows_dict.values(), key=lambda r: (r["date"], r["msg_id"]))
    
    # 업로드 포맷 변환
    upload_data = []
    for r in sorted_rows:
        upload_data.append([r["date"], "", r["message"], r["links"]])

    if not upload_data:
        print("💤 업데이트할 신규 데이터가 없습니다.")
        return

    print(f"📤 {len(upload_data)}건 업로드 준비 중...")
    
    # 6. 업로드 & 알림
    try:
        next_row = last_row_num + 1
        end_row = next_row + len(upload_data) - 1
        cell_range = f"A{next_row}:D{end_row}"
        
        ws.update(range_name=cell_range, values=upload_data, value_input_option="RAW")
        print(f"✅ 시트 업데이트 완료! (범위: {cell_range})")
        
        print("🔔 텔레그램 스마트 알림 전송 중...")
        send_telegram_smart(upload_data)
        
    except Exception as e:
        print(f"❌ 처리 중 에러 발생: {e}")

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    asyncio.run(main())
