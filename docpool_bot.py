import os, sys, re, json, asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaDocument, MessageEntityUrl, MessageEntityTextUrl
import gspread
from google.oauth2.service_account import Credentials

# =========================================================
# [설정] 사용자 정보 & 세션 스트링 (Embed)
# =========================================================
# 1. 텔레그램 API 정보 (기존 파일에서 가져옴)
API_ID = 23502096
API_HASH = "99c1d3f16735873c768f0580a8a6ca58"

# 2. 텔레그램 만능 열쇠 (방금 뽑은 세션 스트링)
# 주의: 이 코드가 공개된 장소에 노출되면 다른 사람이 님 계정으로 접속할 수 있습니다.
SESSION_STRING = "1BVtsOIgBu3Y9HkCwppiILxPqdDwi7Oea8W-GiEJAEN7bbwM3_yMholc0An7WgvDTvUDgwO1yfNLcgYzu-wIehxN7qJJFw6Qk_99gSdwxI-ICytLFNVVVPFfcddntiGTgHABh9w1ZQmf5vKQ0cnKvl88mkRf2MweGbpfvgyzDszb0dMRs0yLctB1fOOFP7m2PtAUDEqJuhmmTs4FIxiyyKBwnVf41rwXx7_Ulm7t1beHE7LnY_m2yS0s3xDtN7maBBfWcrHYA2FAHLMwCvg3l9k-z4xTbJ_SFf85wA9bErkDeM22zpiTNTeD5uwdlVLUzanH87sXVCivPCYl5BkWk9zx8yIO5O-g="

# 3. 타겟 채널 및 시트 설정
CHANNEL_URL = "https://t.me/DOC_POOL"
GSHEET_ID = "19Q3KNbFu0ftr2hAqEdNwhf_UQvYXiXa2Vvk8lv9S6JY"
GSHEET_TAB = "<데이터>소중한추억"
TZ_NAME = "Asia/Seoul"

# 정규식
URL_RE = re.compile(r'https?://\S+', re.I)
PDF_URL_RE = re.compile(r'https?://\S+\.pdf(\b|$)', re.I)
ID_RE = re.compile(r'(\d+)(?=(?:\.pdf\b|/?$))')


# =========================================================
# [기능] 구글 시트 연동
# =========================================================
def get_gsheet_client():
    # GitHub Secrets에 있는 GDRIVE_CREDS 사용
    if 'GDRIVE_CREDS' not in os.environ:
        print("❌ GDRIVE_CREDS 환경변수가 없습니다.")
        sys.exit(1)
        
    creds_dict = json.loads(os.environ['GDRIVE_CREDS'])
    creds = Credentials.from_service_account_info(
        creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return gspread.authorize(creds)

def extract_report_ids(text):
    if not text: return set()
    ids = set()
    for part in str(text).split(","):
        m = ID_RE.search(part.strip())
        if m: ids.add(int(m.group(1)))
    return ids

def fetch_last_id_from_gsheet(ws):
    """
    시트의 D열(Links)을 훑어서 가장 큰 Report ID를 찾습니다.
    (증분 업데이트 기준점)
    """
    try:
        # D열 전체 가져오기 (헤더 제외)
        vals = ws.col_values(4)[1:] 
        if not vals: return 0
        
        max_id = 0
        for cell_val in vals:
            if not cell_val: continue
            ids = extract_report_ids(cell_val)
            if ids:
                max_id = max(max_id, max(ids))
        return max_id
    except Exception as e:
        print(f"⚠️ 시트 마지막 ID 읽기 실패: {e}")
        return 0


# =========================================================
# [기능] 링크 및 본문 추출
# =========================================================
def extract_links_and_filter(msg):
    text = msg.message or ""
    urls = URL_RE.findall(text)
    
    # 숨겨진 링크(TextUrl) 등 추가 추출
    if msg.entities:
        for e in msg.entities:
            if isinstance(e, MessageEntityTextUrl):
                urls.append(e.url)
            elif isinstance(e, MessageEntityUrl):
                urls.append(text[e.offset : e.offset + e.length])
    
    # PDF 관련인지 확인 (제목, 링크, 첨부파일 등)
    is_pdf = False
    if any(PDF_URL_RE.search(u) for u in urls): is_pdf = True
    if ".pdf" in text.lower(): is_pdf = True
    if isinstance(msg.media, MessageMediaDocument):
        mime = getattr(msg.media.document, "mime_type", "")
        if "pdf" in mime: is_pdf = True
    
    if not is_pdf:
        return None, None # PDF 관련 아니면 스킵

    # 링크 정리 (중복 제거)
    tg_link = f"https://t.me/DOC_POOL/{msg.id}"
    final_urls = [tg_link]
    seen = {tg_link}
    
    for u in urls:
        u_clean = u.strip().rstrip(".,)")
        if u_clean and u_clean not in seen:
            seen.add(u_clean)
            final_urls.append(u_clean)
    
    links_str = ", ".join(final_urls)
    
    # 본문 정리 (URL 제거)
    body = URL_RE.sub("", text).strip()
    body = re.sub(r'\s+', ' ', body) # 공백 정리
    
    return body, links_str


# =========================================================
# [메인] 실행 로직
# =========================================================
async def main():
    print("🚀 [소중한추억] 업데이트 봇 가동...")
    
    # 1. 구글 시트 접속
    try:
        gc = get_gsheet_client()
        ws = gc.open_by_key(GSHEET_ID).worksheet(GSHEET_TAB)
    except Exception as e:
        print(f"❌ 구글 시트 접속 에러: {e}")
        return

    # 2. 마지막 ID 확인 (여기부터 긁어옴)
    last_id = fetch_last_id_from_gsheet(ws)
    print(f"📊 기준 ID (Last ID): {last_id}")

    # 3. 텔레그램 접속 (Embed된 세션 사용)
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.connect()
    
    if not await client.is_user_authorized():
        print("❌ 텔레그램 인증 실패. 세션 스트링이 만료되었거나 잘못되었습니다.")
        return

    entity = await client.get_entity(CHANNEL_URL)
    
    new_rows = []
    print(f"🔍 신규 메시지 스캔 중 (ID > {last_id})...")
    
    # 4. 크롤링 (최신순 -> 과거순, last_id 만나면 중단)
    async for msg in client.iter_messages(entity, min_id=last_id, limit=500, reverse=True):
        body, links = extract_links_and_filter(msg)
        if not links: continue # 필터 탈락
        
        # 날짜 (KST 변환)
        kst_dt = msg.date.astimezone(ZoneInfo(TZ_NAME))
        date_str = kst_dt.strftime("%Y-%m-%d")
        
        # 행 추가: [날짜, (빈칸), 메시지, 링크]
        new_rows.append([date_str, "", body, links])
        print(f"  ✅ 수집: {msg.id} | {date_str}")

    await client.disconnect()
    
    # 5. 시트 업로드
    if not new_rows:
        print("💤 업데이트할 새로운 리포트가 없습니다.")
        return

    print(f"📤 총 {len(new_rows)}건 구글 시트에 업로드 중...")
    try:
        ws.append_rows(new_rows, value_input_option="RAW")
        print("✅ 업로드 완료!")
    except Exception as e:
        print(f"❌ 업로드 중 에러 발생: {e}")

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    asyncio.run(main())
