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

# [로컬코드 반영] 채널 및 시트 설정
CHANNEL_URL = "https://t.me/companyreport"
GSHEET_ID = "19Q3KNbFu0ftr2hAqEdNwhf_UQvYXiXa2Vvk8lv9S6JY"
GSHEET_TAB = "<데이터>[주식] 증권사 리포트" # 탭 이름 정확히 일치
TZ_NAME = "Asia/Seoul"

# 로컬 코드처럼 넉넉하게 수집 (최대 2만개까지)
ITER_LIMIT = 20000 

# [핵심] 고유 ID 추출용 정규식 (로컬 코드 100% 동일)
# stockinfo7 또는 consensus URL 뒤에 붙은 숫자를 ID로 인식
STOCKINFO_RE = re.compile(r"https?://stockinfo7\.com/stock/report/url/(\d+)", re.I)
CONSENSUS_RE = re.compile(r"https?://consensus\.hankyung\.com/\S*?report_idx=(\d+)", re.I)

# 기타 정규식
URL_RE = re.compile(r'https?://\S+', re.I)
LEADING_JUNK = re.compile(r'^[\u200B-\u200F\u202A-\u202E\u2060-\u2069\ufeff\s\r\n\t]+', re.S)

try:
    TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
    MY_CHAT_ID = os.environ.get('MY_CHAT_ID')
except:
    TELEGRAM_TOKEN = None
    MY_CHAT_ID = None

# =========================================================
# [기능 1] 로컬 코드의 핵심 로직 이식 (ID 추출 & 태그 감지)
# =========================================================
def get_report_id(text_or_url):
    """
    로컬 코드의 extract_report_id_from_urls 로직과 동일.
    URL에서 고유 리포트 번호(숫자)를 찾아냅니다.
    """
    if not text_or_url: return None
    s = str(text_or_url)
    
    # 1. stockinfo7 패턴 확인
    m1 = STOCKINFO_RE.search(s)
    if m1: return int(m1.group(1))
    
    # 2. consensus 패턴 확인
    m2 = CONSENSUS_RE.search(s)
    if m2: return int(m2.group(1))
    
    return None

def detect_type_tag(text):
    """
    로컬 코드의 detect_type_tag 로직.
    문장 맨 앞의 [기업], [산업], [시장] 등을 B열에 넣기 위해 추출.
    """
    if not text: return ""
    m = re.match(r"^\[(.*?)\]", text.strip())
    return m.group(1).strip() if m else ""

# =========================================================
# [기능 2] 텔레그램 스마트 알림 (동적 시간 + 분할 전송)
# =========================================================
def send_telegram_smart(new_rows):
    if not TELEGRAM_TOKEN or not MY_CHAT_ID: return

    # 현재 시간 (예: 12/25 14:00)
    now = datetime.now(ZoneInfo(TZ_NAME))
    time_tag = f"{now.month}/{now.day} {now.strftime('%H:%M')}"
    
    total_count = len(new_rows)
    header = f"📈 <b>[{time_tag} 증권사 리포트] 업데이트</b>\n신규: {total_count}건\n{'='*20}\n\n"
    
    MAX_LENGTH = 4000
    current_msg = header
    
    for idx, row in enumerate(new_rows, 1):
        # row: [date, tag, message, link]
        date_str = row[0]
        tag = row[1]
        title = row[2]
        link = row[3]

        clean_title = title.replace("<", "&lt;").replace(">", "&gt;") 
        if len(clean_title) > 35: clean_title = clean_title[:35] + "..."
        
        # 태그가 있으면 제목 앞에 붙여서 보여줌
        display_title = f"[{tag}] {clean_title}" if tag else clean_title

        if link:
            line = f"{idx}. [{date_str}] <a href='{link}'>{display_title}</a>\n"
        else:
            line = f"{idx}. [{date_str}] {display_title}\n"
            
        # 메시지 분할 전송 로직
        if len(current_msg) + len(line) > MAX_LENGTH:
            _send_chunk(current_msg)
            current_msg = f"📈 <b>[이어짐] ({idx}번부터~)</b>\n\n" + line
        else:
            current_msg += line
            
    if current_msg:
        _send_chunk(current_msg)

def _send_chunk(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={'chat_id': MY_CHAT_ID, 'text': text, 'parse_mode': 'HTML'})
        time.sleep(1) 
    except Exception as e:
        print(f"❌ 전송 실패: {e}")

# =========================================================
# [기능 3] 구글 시트 유틸 (로컬 Mode 2 로직 반영)
# =========================================================
def get_gsheet_client():
    if 'GDRIVE_CREDS' not in os.environ: sys.exit(1)
    creds_dict = json.loads(os.environ['GDRIVE_CREDS'])
    creds = Credentials.from_service_account_info(
        creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return gspread.authorize(creds)

def find_last_data_row(vals):
    # A~D열 중 하나라도 값이 있는 마지막 줄 찾기
    last = 0
    for idx, row in enumerate(vals, start=1):
        if any((c or "").strip() for c in row[:4]):
            last = idx
    return last

def fetch_sheet_info(ws):
    """
    [로컬 코드 Mode 2의 핵심]
    D열(Link)을 훑어서 '이미 존재하는 Report ID'를 모두 수집하고,
    그 중 가장 큰 값(Max ID)을 찾아서 수집 종료 시점을 잡습니다.
    """
    try:
        vals = ws.get_all_values()
        if not vals: return 0, set(), 0
        
        last_row_idx = find_last_data_row(vals)
        existing_ids = set()
        max_id = 0
        
        for i in range(1, last_row_idx):
            row = vals[i]
            if len(row) > 3:
                # D열 URL에서 ID 추출
                rid = get_report_id(row[3])
                if rid:
                    existing_ids.add(rid)
                    max_id = max(max_id, rid)
        
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
    # 인라인 버튼 URL 추출
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
            seen.add(u)
            out.append(u)
    return out

# =========================================================
# [메인] 실행 로직
# =========================================================
async def main():
    print("🚀 [주식 증권사 리포트] 봇 가동 (Mode 2 Logic)...")
    
    # 1. 시트 접속
    try:
        gc = get_gsheet_client()
        ws = gc.open_by_key(GSHEET_ID).worksheet(GSHEET_TAB)
    except Exception as e:
        print(f"❌ 시트 접속 에러: {e}")
        return

    # 2. 기존 데이터 파악 (중복 방지 & 증분 기준)
    # 로컬 코드처럼 'Max ID'를 가져와서 그 이후 데이터만 긁어오도록 준비
    last_id, existing_ids, last_row_num = fetch_sheet_info(ws)
    print(f"📊 기준 Report ID: {last_id}, 기존 DB: {len(existing_ids)}건")

    # 3. 텔레그램 접속
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.connect()
    
    entity = await client.get_entity(CHANNEL_URL)
    rows_dict = {} # 중복 제거용 임시 저장소
    
    print(f"🔍 스캔 시작 (최대 {ITER_LIMIT}개)...")

    # 4. 메시지 스캔
    # 최신부터 과거 순으로 탐색 (reverse=True가 아님! iter_messages 기본이 최신순)
    # 하지만 여기선 로컬 코드 로직(최신->과거)을 따르되, 
    # Max ID보다 작은 ID가 나오면 '이미 다 긁었구나' 하고 멈추는 방식이 효율적.
    
    async for msg in client.iter_messages(entity, limit=ITER_LIMIT):
        text = normalize_leading(msg.message)
        urls = extract_all_urls(text, msg.entities, msg)
        
        # [핵심] 메시지 내 링크들에서 Report ID 찾기
        found_rid = None
        target_link = None
        for u in urls:
            rid = get_report_id(u)
            if rid:
                found_rid = rid
                target_link = u
                break
        
        # 리포트 ID가 없으면 이 봇의 수집 대상이 아님 (로컬 코드 규칙)
        if not found_rid:
            continue
        
        # [증분 로직] 발견된 ID가 이미 시트에 있는 Max ID보다 작거나 같다?
        # -> 예전 데이터에 도달했다고 판단하고 스캔 종료 (로컬 Mode 2 방식)
        if last_id > 0 and found_rid <= last_id:
            # 안전을 위해 바로 끄진 않고, existing_ids에 있는지 확인 후 continue
            # 하지만 ID 구조상 작으면 옛날 것이 확실하므로 break 해도 됨.
            # 로컬 코드의 안전성을 위해 '이미 있는 ID면 스킵'만 수행
            if found_rid in existing_ids:
                continue
        
        # 중복 ID (순서가 뒤섞여 들어온 경우 대비)
        if found_rid in existing_ids:
            continue
            
        # 데이터 정제
        body_raw = strip_urls_from_text(text)
        tag = detect_type_tag(text) # [기업] 등 추출
        kst_dt = msg.date.astimezone(ZoneInfo(TZ_NAME))
        date_str = kst_dt.strftime("%Y-%m-%d")
        
        if not target_link:
            target_link = f"https://t.me/companyreport/{msg.id}"

        row = {
            "rid": found_rid,
            "date": date_str,
            "tag": tag,
            "message": body_raw,
            "link": target_link
        }
        
        # 딕셔너리에 저장 (같은 ID가 나오면 덮어쓰기)
        if found_rid not in rows_dict:
            rows_dict[found_rid] = row
            
        if len(rows_dict) % 50 == 0:
            print(f"  ... {len(rows_dict)}건 신규 수집 중")

    await client.disconnect()
    
    # 5. ID 오름차순 정렬 (옛날 -> 최신 순으로 시트에 쌓기 위해)
    sorted_rows = sorted(rows_dict.values(), key=lambda r: r["rid"])
    
    # 업로드 포맷 [Date, Tag, Message, Link] (로컬 코드와 컬럼 일치)
    upload_data = []
    for r in sorted_rows:
        upload_data.append([r["date"], r["tag"], r["message"], r["link"]])

    if not upload_data:
        print("💤 신규 업데이트 없음.")
        return

    print(f"📤 {len(upload_data)}건 업로드 및 알림...")
    
    # 6. 업로드 및 알림
    try:
        next_row = last_row_num + 1
        end_row = next_row + len(upload_data) - 1
        cell_range = f"A{next_row}:D{end_row}"
        
        ws.update(range_name=cell_range, values=upload_data, value_input_option="RAW")
        print(f"✅ 시트 저장 완료 (범위: {cell_range})")
        
        send_telegram_smart(upload_data)
        
    except Exception as e:
        print(f"❌ 에러 발생: {e}")

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    asyncio.run(main())
