import os, sys, re, json, asyncio, requests, time
from datetime import datetime
from zoneinfo import ZoneInfo
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaDocument, MessageEntityUrl, MessageEntityTextUrl
import gspread
from google.oauth2.service_account import Credentials

# =========================================================
# [설정] 인증 정보
# =========================================================
API_ID = 23502096
API_HASH = "99c1d3f16735873c768f0580a8a6ca58"
SESSION_STRING = "1BVtsOIgBu3Y9HkCwppiILxPqdDwi7Oea8W-GiEJAEN7bbwM3_yMholc0An7WgvDTvUDgwO1yfNLcgYzu-wIehxN7qJJFw6Qk_99gSdwxI-ICytLFNVVVPFfcddntiGTgHABh9w1ZQmf5vKQ0cnKvl88mkRf2MweGbpfvgyzDszb0dMRs0yLctB1fOOFP7m2PtAUDEqJuhmmTs4FIxiyyKBwnVf41rwXx7_Ulm7t1beHE7LnY_m2yS0s3xDtN7maBBfWcrHYA2FAHLMwCvg3l9k-z4xTbJ_SFf85wA9bErkDeM22zpiTNTeD5uwdlVLUzanH87sXVCivPCYl5BkWk9zx8yIO5O-g="

CHANNEL_URL = "https://t.me/DOC_POOL"
# 님 시트 ID (코드에서 확인된 ID)
GSHEET_ID = "19Q3KNbFu0ftr2hAqEdNwhf_UQvYXiXa2Vvk8lv9S6JY"
GSHEET_TAB = "<데이터>소중한추억"
TZ_NAME = "Asia/Seoul"

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
# [기능 1] 알림 전송 (분할 발송)
# =========================================================
def send_telegram_alert(new_rows):
    if not TELEGRAM_TOKEN or not MY_CHAT_ID:
        return

    total_count = len(new_rows)
    # 한 번에 보낼 개수 (텔레그램 메시지 길이 제한 고려)
    CHUNK_SIZE = 30 
    
    # 데이터를 CHUNK_SIZE 만큼 잘라서 반복 전송
    for i in range(0, total_count, CHUNK_SIZE):
        chunk = new_rows[i : i + CHUNK_SIZE]
        is_first = (i == 0)
        is_last = (i + CHUNK_SIZE >= total_count)
        
        # 헤더: 첫 메시지에만 표시
        if is_first:
            msg_head = f"📚 <b>[소중한추억] 업데이트 완료</b>\n신규 리포트: {total_count}건\n{'='*20}\n\n"
        else:
            msg_head = f"📚 <b>[소중한추억] 이어지는 목록 ({i+1}~{min(i+CHUNK_SIZE, total_count)})</b>\n\n"
            
        body_list = []
        for idx, row in enumerate(chunk, start=i+1):
            date_str = row[0] if len(row) > 0 else ""
            title = row[2] if len(row) > 2 else "제목 없음"
            links_str = row[3] if len(row) > 3 else ""
            
            # HTML 태그 충돌 방지
            clean_title = title.replace("<", "&lt;").replace(">", "&gt;") 
            if len(clean_title) > 35: 
                clean_title = clean_title[:35] + "..."
                
            target_link = ""
            if links_str:
                first_link = links_str.split(',')[0].strip()
                if first_link.startswith("http"):
                    target_link = first_link
            
            if target_link:
                line = f"{idx}. [{date_str}] <a href='{target_link}'>{clean_title}</a>"
            else:
                line = f"{idx}. [{date_str}] {clean_title}"
            body_list.append(line)
        
        msg_body = "\n".join(body_list)
        full_text = msg_head + msg_body

        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        try:
            # parse_mode='HTML' 필수
            r = requests.post(url, data={'chat_id': MY_CHAT_ID, 'text': full_text, 'parse_mode': 'HTML'})
            if r.status_code != 200:
                print(f"❌ 전송 실패 ({i+1}~): {r.text}")
            else:
                print(f"✅ 텔레그램 전송 성공 ({i+1}~{min(i+CHUNK_SIZE, total_count)})")
            
            # 메시지 순서 꼬임 방지 및 도배 방지 딜레이
            time.sleep(1) 
        except Exception as e:
            print(f"❌ 텔레그램 연결 실패: {e}")


# =========================================================
# [기능 2] 구글 시트 & 파싱 유틸 (빈 행 처리 로직 개선)
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

# 시트의 마지막 데이터 행 찾기 (로컬 코드 로직 반영)
def find_last_data_row(vals):
    last = 0
    # vals는 헤더 포함 전체 데이터
    for idx, row in enumerate(vals, start=1):
        # A~D (index 0~3) 중 하나라도 값이 있으면 데이터 행으로 간주
        if any((c or "").strip() for c in row[:4]):
            last = idx
    return last

def fetch_last_id_and_row(ws):
    try:
        # 시트 전체 데이터 가져오기 (A:D 열)
        # get_all_values()를 써야 빈 행 포함 전체 구조 파악 가능
        vals = ws.get_all_values()
        
        if not vals: 
            return 0, 0 # 데이터 없음
            
        last_row_idx = find_last_data_row(vals)
        
        # 마지막 ID 찾기 (데이터 있는 행들만 뒤져서)
        max_id = 0
        # 헤더(1행) 제외하고 스캔
        for i in range(1, last_row_idx):
            row = vals[i]
            if len(row) > 3:
                cell_val = row[3] # D열 (Links)
                ids = extract_report_ids_from_text(cell_val)
                if ids:
                    max_id = max(max_id, max(ids))
                    
        return max_id, last_row_idx
        
    except Exception as e:
        print(f"⚠️ 시트 읽기 실패: {e}")
        return 0, 0

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

    # 마지막 ID와 데이터가 있는 마지막 행 번호(last_row)를 같이 가져옴
    last_id, last_row_num = fetch_last_id_and_row(ws)
    print(f"📊 기준 ID: {last_id} | 마지막 데이터 위치: {last_row_num}행")

    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.connect()
    
    entity = await client.get_entity(CHANNEL_URL)
    
    new_rows = []
    print(f"🔍 스캔 시작 (ID > {last_id})...")
    
    # 텔레그램 오류 방지를 위해 최대 200개까지만 수집
    async for msg in client.iter_messages(entity, min_id=last_id, limit=200, reverse=True):
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
        
        new_rows.append([date_str, "", body, links])
        print(f"  ✅ 수집: {msg.id}")

    await client.disconnect()
    
    if not new_rows:
        print("💤 업데이트 내역 없음.")
        return

    print(f"📤 {len(new_rows)}건 업로드 중...")
    try:
        # [수정] append_rows 대신 update 사용
        # 빈 공간을 무시하고 last_row_num 바로 다음 줄부터 작성
        
        next_row = last_row_num + 1
        end_row = next_row + len(new_rows) - 1
        
        # A열부터 D열까지 범위 지정 (예: A156:D160)
        cell_range = f"A{next_row}:D{end_row}"
        
        # 구글 시트에 데이터 쓰기
        ws.update(range_name=cell_range, values=new_rows, value_input_option="RAW")
        print(f"✅ 시트 업데이트 성공! (위치: {cell_range})")
        
        print("🔔 텔레그램 알림 전송 중...")
        send_telegram_alert(new_rows)
        
    except Exception as e:
        print(f"❌ 에러: {e}")

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    asyncio.run(main())
