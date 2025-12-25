import os, sys, re, json, asyncio, requests, time
from datetime import datetime
from zoneinfo import ZoneInfo
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaDocument, MessageEntityUrl, MessageEntityTextUrl
import gspread
from google.oauth2.service_account import Credentials

# ==============================================================================
# 📝 [사용자 수정 가이드]
# 1. YAML 파일에서 스케줄(cron) 시간을 변경했다면?
#    -> 아래 'SCHEDULE_HOURS' 리스트의 숫자도 똑같이 바꿔주세요.
#    -> 그래야 텔레그램 메시지에 "몇 회차(현재)" 표시가 정확하게 나옵니다.
#
# 2. 예시: YAML에서 09:00, 14:00으로 바꿨다면?
#    -> SCHEDULE_HOURS = [9, 14] 로 수정
# ==============================================================================
SCHEDULE_HOURS = [8, 13, 15, 18, 20] 

# =========================================================
# [설정] 인증 정보 및 상수
# =========================================================
API_ID = 23502096
API_HASH = "99c1d3f16735873c768f0580a8a6ca58"
SESSION_STRING = "1BVtsOIgBu3Y9HkCwppiILxPqdDwi7Oea8W-GiEJAEN7bbwM3_yMholc0An7WgvDTvUDgwO1yfNLcgYzu-wIehxN7qJJFw6Qk_99gSdwxI-ICytLFNVVVPFfcddntiGTgHABh9w1ZQmf5vKQ0cnKvl88mkRf2MweGbpfvgyzDszb0dMRs0yLctB1fOOFP7m2PtAUDEqJuhmmTs4FIxiyyKBwnVf41rwXx7_Ulm7t1beHE7LnY_m2yS0s3xDtN7maBBfWcrHYA2FAHLMwCvg3l9k-z4xTbJ_SFf85wA9bErkDeM22zpiTNTeD5uwdlVLUzanH87sXVCivPCYl5BkWk9zx8yIO5O-g="

CHANNEL_URL = "https://t.me/companyreport"
GSHEET_ID = "19Q3KNbFu0ftr2hAqEdNwhf_UQvYXiXa2Vvk8lv9S6JY"
GSHEET_TAB = "<데이터>[주식] 증권사 리포트"
TZ_NAME = "Asia/Seoul"

# 로컬 코드처럼 넉넉하게
ITER_LIMIT = 10000 

STOCKINFO_RE = re.compile(r"https?://stockinfo7\.com/stock/report/url/(\d+)", re.I)
CONSENSUS_RE = re.compile(r"https?://consensus\.hankyung\.com/\S*?report_idx=(\d+)", re.I)
URL_RE = re.compile(r'https?://\S+', re.I)
LEADING_JUNK = re.compile(r'^[\u200B-\u200F\u202A-\u202E\u2060-\u2069\ufeff\s\r\n\t]+', re.S)

try:
    TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
    MY_CHAT_ID = os.environ.get('MY_CHAT_ID')
except:
    TELEGRAM_TOKEN = None
    MY_CHAT_ID = None

# =========================================================
# [기능 1] 텔레그램 스마트 알림 (일정표 포함)
# =========================================================
def send_telegram_smart(new_rows):
    if not TELEGRAM_TOKEN or not MY_CHAT_ID: return

    now = datetime.now(ZoneInfo(TZ_NAME))
    current_hour = now.hour
    
    # 1. 일정표 생성 로직
    schedule_text_list = []
    current_seq = 0
    
    for idx, h in enumerate(SCHEDULE_HOURS, 1):
        label = f"{idx}회: {h:02d}:00"
        # 현재 시간이 스케줄 시간과 같거나, 스케줄을 조금 지났지만 다음 스케줄 전이면 '현재'로 표시
        # (간단하게 hour가 일치하면 현재로 처리)
        if current_hour == h:
             label += " (현재) 👈"
             current_seq = idx
        schedule_text_list.append(label)
    
    schedule_block = "\n".join(schedule_text_list)
    
    time_tag = f"{now.month}/{now.day} {now.strftime('%H:%M')}"
    seq_title = f"{current_seq}회차" if current_seq > 0 else "수시"
    total_count = len(new_rows)
    
    # 2. 헤더 조립
    header = (
        f"📈 <b>[{time_tag} | {seq_title}] 증권사 리포트 업데이트</b>\n"
        f"신규: {total_count}건\n"
        f"{'='*20}\n"
        f"[금일 업로드 계획]\n"
        f"{schedule_block}\n"
        f"{'='*20}\n\n"
    )
    
    # [빈 결과 알림]
    if total_count == 0:
        msg = header + "(업데이트 된 내용이 없습니다)"
        _send_chunk(msg)
        return

    # 3. 데이터 리스트 조립 (4000자 제한)
    MAX_LENGTH = 4000
    current_msg = header
    
    # [주의] 크롤링은 최신순으로 했지만, 보낼 때는 번호가 1번부터 나오게 정렬된 상태여야 함 (main에서 정렬됨)
    for idx, row in enumerate(new_rows, 1):
        date_str = row[0]
        tag = row[1]
        title = row[2]
        link = row[3]

        clean_title = title.replace("<", "&lt;").replace(">", "&gt;") 
        if len(clean_title) > 35: clean_title = clean_title[:35] + "..."
        
        display_title = f"[{tag}] {clean_title}" if tag else clean_title

        if link:
            line = f"{idx}. [{date_str}] <a href='{link}'>{display_title}</a>\n"
        else:
            line = f"{idx}. [{date_str}] {display_title}\n"
            
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
# [기능 2] 리포트 ID 및 태그 추출
# =========================================================
def get_report_id(text_or_url):
    if not text_or_url: return None
    s = str(text_or_url)
    m1 = STOCKINFO_RE.search(s)
    if m1: return int(m1.group(1))
    m2 = CONSENSUS_RE.search(s)
    if m2: return int(m2.group(1))
    return None

def detect_type_tag(text):
    if not text: return ""
    m = re.match(r"^\[(.*?)\]", text.strip())
    return m.group(1).strip() if m else ""

# =========================================================
# [기능 3] 구글 시트 유틸
# =========================================================
def get_gsheet_client():
    if 'GDRIVE_CREDS' not in os.environ: sys.exit(1)
    creds_dict = json.loads(os.environ['GDRIVE_CREDS'])
    creds = Credentials.from_service_account_info(
        creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return gspread.authorize(creds)

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
# [메인] 실행 로직 (로컬 Mode 2 방식: 최신->과거 Break)
# =========================================================
async def main():
    print("🚀 [주식 증권사 리포트] 봇 가동...")
    
    try:
        gc = get_gsheet_client()
        ws = gc.open_by_key(GSHEET_ID).worksheet(GSHEET_TAB)
    except Exception as e:
        print(f"❌ 시트 접속 에러: {e}")
        return

    last_id, existing_ids, last_row_num = fetch_sheet_info(ws)
    print(f"📊 기준 Report ID: {last_id}, 기존 DB: {len(existing_ids)}건")

    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.connect()
    
    entity = await client.get_entity(CHANNEL_URL)
    rows_dict = {}
    
    print(f"🔍 스캔 시작 (최대 {ITER_LIMIT}개)...")

    # [핵심] 최신부터 과거로 훑기 (reverse=False, default)
    # 로컬 코드의 scan_mode_gsheet 로직 그대로 적용
    async for msg in client.iter_messages(entity, limit=ITER_LIMIT):
        text = normalize_leading(msg.message)
        urls = extract_all_urls(text, msg.entities, msg)
        
        found_rid = None
        target_link = None
        for u in urls:
            rid = get_report_id(u)
            if rid:
                found_rid = rid
                target_link = u
                break
        
        if not found_rid:
            continue
        
        # [중단 조건] 이미 시트에 있는 최신 ID보다 작거나 같은 ID가 나오면
        # "여기서부터는 옛날 거구나" 하고 멈춤. (Strict Incremental)
        if last_id > 0 and found_rid <= last_id:
            print(f"🛑 기준 ID({last_id}) 도달. 스캔 종료.")
            break
            
        # 혹시 모를 중복 방지
        if found_rid in existing_ids:
            continue
            
        body_raw = strip_urls_from_text(text)
        tag = detect_type_tag(text)
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
        
        if found_rid not in rows_dict:
            rows_dict[found_rid] = row
            
        if len(rows_dict) % 50 == 0:
            print(f"  ... {len(rows_dict)}건 신규 수집 중")

    await client.disconnect()
    
    # ID 오름차순 정렬 (옛날 -> 최신 순으로 시트에 쌓기)
    sorted_rows = sorted(rows_dict.values(), key=lambda r: r["rid"])
    
    upload_data = []
    for r in sorted_rows:
        upload_data.append([r["date"], r["tag"], r["message"], r["link"]])

    # 빈 결과도 알림 전송
    if not upload_data:
        print("💤 신규 업데이트 없음.")
        send_telegram_smart([])
        return

    print(f"📤 {len(upload_data)}건 업로드 및 알림...")
    
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
