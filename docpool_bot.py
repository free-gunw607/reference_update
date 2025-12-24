import os, sys, re, json, asyncio, requests
from datetime import datetime
from zoneinfo import ZoneInfo
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaDocument, MessageEntityUrl, MessageEntityTextUrl
import gspread
from google.oauth2.service_account import Credentials

# =========================================================
# [설정] 인증 정보 & 환경변수
# =========================================================
API_ID = 23502096
API_HASH = "99c1d3f16735873c768f0580a8a6ca58"
SESSION_STRING = "1BVtsOIgBu3Y9HkCwppiILxPqdDwi7Oea8W-GiEJAEN7bbwM3_yMholc0An7WgvDTvUDgwO1yfNLcgYzu-wIehxN7qJJFw6Qk_99gSdwxI-ICytLFNVVVPFfcddntiGTgHABh9w1ZQmf5vKQ0cnKvl88mkRf2MweGbpfvgyzDszb0dMRs0yLctB1fOOFP7m2PtAUDEqJuhmmTs4FIxiyyKBwnVf41rwXx7_Ulm7t1beHE7LnY_m2yS0s3xDtN7maBBfWcrHYA2FAHLMwCvg3l9k-z4xTbJ_SFf85wA9bErkDeM22zpiTNTeD5uwdlVLUzanH87sXVCivPCYl5BkWk9zx8yIO5O-g="

CHANNEL_URL = "https://t.me/DOC_POOL"
GSHEET_ID = "19Q3KNbFu0ftr2hAqEdNwhf_UQvYXiXa2Vvk8lv9S6JY"
GSHEET_TAB = "<데이터>소중한추억"
TZ_NAME = "Asia/Seoul"

# 알림용 토큰 (Secrets에서 로드)
try:
    TELEGRAM_TOKEN = os.environ['TELEGRAM_TOKEN']
    MY_CHAT_ID = os.environ['MY_CHAT_ID']
except KeyError:
    TELEGRAM_TOKEN = None
    MY_CHAT_ID = None

# 정규식
URL_RE = re.compile(r'https?://\S+', re.I)
PDF_URL_RE = re.compile(r'https?://\S+\.pdf(\b|$)', re.I)
ID_RE = re.compile(r'(\d+)(?=(?:\.pdf\b|/?$))')
LEADING_JUNK = re.compile(r'^[\u200B-\u200F\u202A-\u202E\u2060-\u2069\ufeff\s\r\n\t]+', re.S)

# =========================================================
# [기능 1] 알림 전송 (날짜 + 링크 포함)
# =========================================================
def send_telegram_alert(new_rows):
    if not TELEGRAM_TOKEN or not MY_CHAT_ID:
        return

    count = len(new_rows)
    msg_head = f"📚 <b>[소중한추억] 업데이트 완료</b>\n신규 리포트: {count}건\n{'='*20}\n\n"
    
    body_list = []
    for idx, row in enumerate(new_rows, 1):
        # row 구조: [date, "", message, links]
        date_str = row[0] if len(row) > 0 else ""
        title = row[2] if len(row) > 2 else "제목 없음"
        links_str = row[3] if len(row) > 3 else ""
        
        # 1. 제목 길이 정리
        clean_title = title.replace("<", "&lt;").replace(">", "&gt;") 
        if len(clean_title) > 35: 
            clean_title = clean_title[:35] + "..."
            
        # 2. 링크 추출 (첫 번째 링크 사용)
        target_link = ""
        if links_str:
            first_link = links_str.split(',')[0].strip()
            if first_link.startswith("http"):
                target_link = first_link
        
        # 3. HTML 포맷: "번호. [날짜] 제목 (링크)"
        # 날짜를 대괄호[]로 감싸서 잘 보이게 함
        if target_link:
            line = f"{idx}. [{date_str}] <a href='{target_link}'>{clean_title}</a>"
        else:
            line = f"{idx}. [{date_str}] {clean_title}"
            
        body_list.append(line)
    
    msg_body = "\n".join(body_list)
    full_text = msg_head + msg_body
    
    if len(full_text) > 4000:
        full_text = full_text[:4000] + "\n...(생략)"

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, data={'chat_id': MY_CHAT_ID, 'text': full_text, 'parse_mode': 'HTML'})
    except Exception as e:
        print(f"❌ 텔레그램 알림 실패: {e}")

# =========================================================
# [기능 2] 구글 시트 & 파싱 유틸
# =========================================================
def get_gsheet_client():
    if 'GDRIVE_CREDS' not in os.environ:
        print("❌ GDRIVE_CREDS 환경변수가 없습니다.")
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

def fetch_last_id_from_gsheet(ws):
    try:
        vals = ws.col_values(4)[1:] 
        if not vals: return 0
        max_id = 0
        for cell_val in vals:
            if not cell_val: continue
            ids = extract_report_ids_from_text(cell_val)
            if ids:
                max_id = max(max_id, max(ids))
        return max_id
    except Exception as e:
        print(f"⚠️ 시트 ID 읽기 실패: {e}")
        return 0

# =========================================================
# [기능 3] 메시지 정규화
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
    print("🚀 [소중한추억] 업데이트 봇 가동...")
    
    try:
        gc = get_gsheet_client()
        ws = gc.open_by_key(GSHEET_ID).worksheet(GSHEET_TAB)
    except Exception as e:
        print(f"❌ 구글 시트 에러: {e}")
        return

    last_id = fetch_last_id_from_gsheet(ws)
    print(f"📊 기준 ID: {last_id}")

    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        print("❌ 인증 실패: 세션 스트링 확인 필요")
        return

    entity = await client.get_entity(CHANNEL_URL)
    
    new_rows = []
    print(f"🔍 스캔 시작 (ID > {last_id})...")
    
    async for msg in client.iter_messages(entity, min_id=last_id, limit=300, reverse=True):
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
            
        body = strip_urls_from_text(text)
        kst_dt = msg.date.astimezone(ZoneInfo(TZ_NAME))
        date_str = kst_dt.strftime("%Y-%m-%d")
        
        # [날짜, 빈칸, 메시지, 링크] 순서로 저장
        new_rows.append([date_str, "", body, links])
        print(f"  ✅ 수집: {msg.id}")

    await client.disconnect()
    
    if not new_rows:
        print("💤 업데이트 내역 없음.")
        return

    print(f"📤 {len(new_rows)}건 업로드 중...")
    try:
        ws.append_rows(new_rows, value_input_option="RAW")
        print("✅ 업로드 성공!")
        print("🔔 텔레그램 알림 전송 중...")
        send_telegram_alert(new_rows)
    except Exception as e:
        print(f"❌ 업로드/전송 중 에러: {e}")

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    asyncio.run(main())
