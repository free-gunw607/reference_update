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
# YAML 스케줄과 동일하게 맞춰주세요.
# ==============================================================================
SCHEDULE_HOURS = [8, 13, 15, 18, 20]

# =========================================================
# [설정] 인증 정보 및 상수
# =========================================================
API_ID = 23502096
API_HASH = "99c1d3f16735873c768f0580a8a6ca58"
SESSION_STRING = "1BVtsOIgBu3Y9HkCwppiILxPqdDwi7Oea8W-GiEJAEN7bbwM3_yMholc0An7WgvDTvUDgwO1yfNLcgYzu-wIehxN7qJJFw6Qk_99gSdwxI-ICytLFNVVVPFfcddntiGTgHABh9w1ZQmf5vKQ0cnKvl88mkRf2MweGbpfvgyzDszb0dMRs0yLctB1fOOFP7m2PtAUDEqJuhmmTs4FIxiyyKBwnVf41rwXx7_Ulm7t1beHE7LnY_m2yS0s3xDtN7maBBfWcrHYA2FAHLMwCvg3l9k-z4xTbJ_SFf85wA9bErkDeM22zpiTNTeD5uwdlVLUzanH87sXVCivPCYl5BkWk9zx8yIO5O-g="

CHANNEL_URL = "https://t.me/DTpapers"
GSHEET_ID = "19Q3KNbFu0ftr2hAqEdNwhf_UQvYXiXa2Vvk8lv9S6JY"
GSHEET_TAB = "<데이터>Papers"
TZ_NAME = "Asia/Seoul"
ITER_LIMIT = 10000 

# 정규식
URL_RE = re.compile(r'https?://\S+', re.I)
# 로컬 코드의 ID 추출 정규식 활용
ID_FROM_LINK_RE = re.compile(r'/(\d+)(?:\D*$|$)')
LEADING_JUNK = re.compile(r'^[\u200B-\u200F\u202A-\u202E\u2060-\u2069\ufeff\s\r\n\t]+', re.S)

try:
    TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
    MY_CHAT_ID = os.environ.get('MY_CHAT_ID')
except:
    TELEGRAM_TOKEN = None
    MY_CHAT_ID = None

# =========================================================
# [기능 1] 텔레그램 스마트 알림 (통일된 포맷)
# =========================================================
def send_telegram_smart(new_rows):
    if not TELEGRAM_TOKEN or not MY_CHAT_ID: return

    now = datetime.now(ZoneInfo(TZ_NAME))
    current_hour = now.hour
    
    schedule_text_list = []
    current_seq = 0
    
    for idx, h in enumerate(SCHEDULE_HOURS, 1):
        label = f"{idx}회: {h:02d}:00"
        if current_hour == h:
             label += " (현재) 👈"
             current_seq = idx
        schedule_text_list.append(label)
    
    schedule_block = "\n".join(schedule_text_list)
    time_tag = f"{now.month}/{now.day} {now.strftime('%H:%M')}"
    seq_title = f"{current_seq}회차" if current_seq > 0 else "수시"
    total_count = len(new_rows)
    
    header = (
        f"📚 <b>[{time_tag} | {seq_title}] Papers 업데이트</b>\n"
        f"신규: {total_count}건\n"
        f"{'='*20}\n"
        f"[금일 업로드 계획]\n"
        f"{schedule_block}\n"
        f"{'='*20}\n\n"
    )
    
    if total_count == 0:
        msg = header + "(업데이트 된 내용이 없습니다)"
        _send_chunk(msg)
        return

    MAX_LENGTH = 4000
    current_msg = header
    
    for idx, row in enumerate(new_rows, 1):
        # Papers 시트 구조: [Date, "", Message(Title), Link]
        date_str = row[0]
        title = row[2]
        links_str = row[3]

        clean_title = title.replace("<", "&lt;").replace(">", "&gt;") 
        if len(clean_title) > 35: clean_title = clean_title[:35] + "..."
            
        target_link = ""
        if links_str:
            first_link = links_str.split(',')[0].strip()
            if first_link.startswith("http"): target_link = first_link
        
        if target_link:
            line = f"{idx}. [{date_str}] <a href='{target_link}'>{clean_title}</a>\n"
        else:
            line = f"{idx}. [{date_str}] {clean_title}\n"
            
        if len(current_msg) + len(line) > MAX_LENGTH:
            _send_chunk(current_msg)
            current_msg = f"📚 <b>[이어짐] ({idx}번부터~)</b>\n\n" + line
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
# [기능 2] Papers 고유 로직 이식 (Local Code Logic)
# =========================================================
def normalize_leading(s):
    if not s: return ""
    return LEADING_JUNK.sub("", s)

def guess_title_from_msg(msg):
    """
    [로컬 코드 이식]
    메시지 텍스트가 없으면 PDF 파일명을 제목으로 사용
    """
    text = normalize_leading(msg.message).strip()
    if text:
        return text

    if isinstance(msg.media, MessageMediaDocument):
        doc = getattr(msg.media, "document", None)
        if doc is not None:
            for attr in getattr(doc, "attributes", []):
                fn = getattr(attr, "file_name", None)
                if fn:
                    return fn
    return "제목 없음"

def is_pdf_message(msg):
    """
    [로컬 코드 이식] PDF 파일인지 판별
    """
    if isinstance(msg.media, MessageMediaDocument):
        doc = getattr(msg.media, "document", None)
        mime = getattr(doc, "mime_type", "") or ""
        if mime.lower() == "application/pdf":
            return True
        for attr in getattr(doc, "attributes", []):
            fn = getattr(attr, "file_name", None)
            if fn and fn.lower().endswith(".pdf"):
                return True
    # 텍스트 링크에 pdf가 포함된 경우도 체크
    if msg.message and ".pdf" in msg.message.lower():
        return True
    return False

def extract_report_ids_from_text(text):
    """시트 D열 링크에서 ID 추출 (t.me/DTpapers/1234)"""
    if not text: return set()
    ids = set()
    # 로컬 코드의 정규식 활용
    for m in ID_FROM_LINK_RE.finditer(str(text)):
        ids.add(int(m.group(1)))
    return ids

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
                ids = extract_report_ids_from_text(row[3])
                if ids:
                    existing_ids.update(ids)
                    max_id = max(max_id, max(ids))
        return max_id, existing_ids, last_row_idx
    except Exception as e:
        print(f"⚠️ 시트 읽기 실패: {e}")
        return 0, set(), 0

# =========================================================
# [메인] 실행 로직 (Mode 2: GSheet Incremental)
# =========================================================
async def main():
    print("🚀 [Papers] 업데이트 봇 가동...")
    
    try:
        gc = get_gsheet_client()
        ws = gc.open_by_key(GSHEET_ID).worksheet(GSHEET_TAB)
    except Exception as e:
        print(f"❌ 구글 시트 에러: {e}")
        return

    last_id, existing_ids, last_row_num = fetch_sheet_info(ws)
    print(f"📊 시트 상태: Max ID={last_id}, 총 데이터={len(existing_ids)}건")
    
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.connect()
    
    entity = await client.get_entity(CHANNEL_URL)
    # 중복 제거용 딕셔너리 (날짜+제목 기준)
    rows_dict = {} 
    
    print(f"🔍 스캔 시작 (기준 ID > {last_id})...")
    
    # [핵심] reverse=True (과거->최신) + min_id (증분)
    async for msg in client.iter_messages(entity, min_id=last_id, limit=ITER_LIMIT, reverse=True):
        
        # [로컬 로직] PDF가 아니면 스킵
        if not is_pdf_message(msg):
            continue
            
        # [로컬 로직] 제목 추론
        title = guess_title_from_msg(msg)
        tg_link = f"https://t.me/DTpapers/{msg.id}"
        
        # 날짜
        kst_dt = msg.date.astimezone(ZoneInfo(TZ_NAME))
        date_str = kst_dt.strftime("%Y-%m-%d")
        
        # 이미 수집된 ID면 스킵
        if msg.id in existing_ids:
            continue

        # 중복 제거 키: (날짜, 제목) - Papers 특성상 같은 파일이 다시 올라올 수 있음
        key = (date_str, title)
        
        # 딕셔너리에 저장 (기존에 없거나, msg_id가 더 작으면(원본이면) 유지)
        # Papers는 같은 내용이면 msg_id가 작은 걸(먼저 올라온 걸) 유지하는 게 좋음
        if key not in rows_dict:
            rows_dict[key] = {
                "msg_id": msg.id,
                "date": date_str,
                "message": title,
                "links": tg_link
            }
        
        if len(rows_dict) % 50 == 0:
            print(f"  ... {len(rows_dict)}건 수집 중")

    await client.disconnect()
    
    # ID 순 정렬
    sorted_rows = sorted(rows_dict.values(), key=lambda r: (r["date"], r["msg_id"]))
    
    upload_data = []
    for r in sorted_rows:
        upload_data.append([r["date"], "", r["message"], r["links"]])

    if not upload_data:
        print("💤 업데이트할 신규 데이터가 없습니다.")
        send_telegram_smart([])
        return

    print(f"📤 {len(upload_data)}건 업로드 준비 중...")
    
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
