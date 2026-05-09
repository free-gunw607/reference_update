import os, sys, re, json, asyncio, requests, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaDocument, MessageEntityUrl, MessageEntityTextUrl, DocumentAttributeFilename
import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

# ==============================================================================
# 📝 [사용자 수정 가이드]
# YAML 파일의 스케줄(시간)을 변경하면, 아래 리스트의 숫자도 맞춰주세요.
# 그래야 메시지에 "현재" 위치가 정확히 표시됩니다.
# ==============================================================================
SCHEDULE_HOURS = [8, 13, 15, 18, 20]

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
BACKFILL_FROM = os.getenv("DOCPOOL_BACKFILL_FROM", "").strip()  # YYYY-MM-DD
BACKFILL_TO = os.getenv("DOCPOOL_BACKFILL_TO", "").strip()      # YYYY-MM-DD
OUTPUT_MODE = os.getenv("DOCPOOL_OUTPUT_MODE", "gsheet").strip().lower()  # gsheet | local
# backfill에서 기존 시트 중복 차단을 무시할지 여부 (기본: local 모드 백필이면 True)
BACKFILL_IGNORE_EXISTING = os.getenv("DOCPOOL_BACKFILL_IGNORE_EXISTING", "").strip().lower()

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
TG_LINK_ID_RE = re.compile(r'https?://t\.me/DOC_POOL/(\d+)', re.I)
LEADING_JUNK = re.compile(r'^[\u200B-\u200F\u202A-\u202E\u2060-\u2069\ufeff\s\r\n\t]+', re.S)

STATE_TAB = "_state_docpool"
STATE_KEY = "last_id"

# =========================================================
# [기능 1] 텔레그램 스마트 알림 (일정표 포함 + 꽉 채우기)
# =========================================================
def send_telegram_smart(new_rows):
    if not TELEGRAM_TOKEN or not MY_CHAT_ID:
        return

    # 1. 현재 시간 및 회차 계산
    now = datetime.now(ZoneInfo(TZ_NAME))
    current_hour = now.hour
    
    schedule_text_list = []
    current_seq = 0
    
    # 일정표 만들기
    for idx, h in enumerate(SCHEDULE_HOURS, 1):
        label = f"{idx}회: {h:02d}:00"
        # 현재 시간이 스케줄과 같으면 '현재' 표시
        if current_hour == h:
             label += " (현재) 👈"
             current_seq = idx
        schedule_text_list.append(label)
    
    schedule_block = "\n".join(schedule_text_list)
    
    time_tag = f"{now.month}/{now.day} {now.strftime('%H:%M')}"
    seq_title = f"{current_seq}회차" if current_seq > 0 else "수시"
    total_count = len(new_rows)

    # 2. 헤더 조립 (요청하신 포맷 적용)
    header = (
        f"📚 <b>[{time_tag} | {seq_title}] 소중한추억 업데이트</b>\n"
        f"신규: {total_count}건\n"
        f"{'='*20}\n"
        f"[금일 업로드 계획]\n"
        f"{schedule_block}\n"
        f"{'='*20}\n\n"
    )
    
    # [빈 결과 알림] 데이터가 없어도 알림 전송
    if total_count == 0:
        msg = header + "(업데이트 된 내용이 없습니다)"
        _send_chunk(msg)
        return

    # 3. 메시지 본문 생성 (4000자 제한)
    MAX_LENGTH = 4000
    current_msg = header
    
    for idx, row in enumerate(new_rows, 1):
        # row: [date, "", message, links]
        date_str = row[0]
        title = row[2]
        links_str = row[3]

        clean_title = title.replace("<", "&lt;").replace(">", "&gt;") 
        if len(clean_title) > 35: 
            clean_title = clean_title[:35] + "..."
            
        target_link = ""
        if links_str:
            first_link = links_str.split(',')[0].strip()
            if first_link.startswith("http"):
                target_link = first_link
        
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
    """실제 전송 함수"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={'chat_id': MY_CHAT_ID, 'text': text, 'parse_mode': 'HTML'})
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
    return key

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

def extract_tg_message_ids_from_text(text):
    if not text:
        return set()
    return {int(x) for x in TG_LINK_ID_RE.findall(str(text))}

def find_last_data_row(vals):
    last = 0
    for idx, row in enumerate(vals, start=1):
        if any((c or "").strip() for c in row[:4]):
            last = idx
    return last


def get_or_create_state_ws(spreadsheet):
    try:
        return spreadsheet.worksheet(STATE_TAB)
    except Exception:
        return spreadsheet.add_worksheet(title=STATE_TAB, rows=20, cols=3)


def load_state_last_id(state_ws):
    try:
        vals = state_ws.get_all_values()
        for row in vals:
            if len(row) >= 2 and row[0].strip() == STATE_KEY:
                return int(row[1])
    except Exception:
        pass
    return 0


def save_state_last_id(state_ws, last_id):
    now_str = datetime.now(ZoneInfo(TZ_NAME)).strftime("%Y-%m-%d %H:%M:%S")
    vals = state_ws.get_all_values()
    target_row = None
    for i, row in enumerate(vals, start=1):
        if len(row) >= 1 and row[0].strip() == STATE_KEY:
            target_row = i
            break
    if target_row is None:
        target_row = 1
    state_ws.update(
        range_name=f"A{target_row}:C{target_row}",
        values=[[STATE_KEY, str(int(last_id)), now_str]],
        value_input_option="RAW",
    )


def choose_effective_start_id(sheet_last_id, state_last_id, latest_msg_id):
    candidates = [x for x in (sheet_last_id, state_last_id) if isinstance(x, int) and x >= 0]
    if not candidates:
        return 0
    # Drop suspicious IDs far above current channel ID.
    sane = [x for x in candidates if x <= latest_msg_id + 1000]
    if sane:
        return max(sane)
    return min(candidates)


def parse_backfill_window():
    if not BACKFILL_FROM:
        return None
    tz = ZoneInfo(TZ_NAME)
    try:
        start_local = datetime.fromisoformat(BACKFILL_FROM).replace(tzinfo=tz)
    except ValueError:
        print(f"⚠️ invalid DOCPOOL_BACKFILL_FROM={BACKFILL_FROM}, ignoring backfill")
        return None

    if BACKFILL_TO:
        try:
            end_local = datetime.fromisoformat(BACKFILL_TO).replace(tzinfo=tz) + timedelta(days=1)
        except ValueError:
            print(f"⚠️ invalid DOCPOOL_BACKFILL_TO={BACKFILL_TO}, using open-ended")
            end_local = datetime.now(tz) + timedelta(minutes=1)
    else:
        end_local = datetime.now(tz) + timedelta(minutes=1)
    return start_local, end_local


def save_local_output(upload_data):
    out_dir = Path("docpool_outputs")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(ZoneInfo(TZ_NAME)).strftime("%Y%m%d_%H%M%S")
    out_csv = out_dir / f"docpool_{ts}.csv"
    df = pd.DataFrame(upload_data, columns=["date", "blank", "message", "tg_link", "summary"])
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"💾 로컬 저장 모드: {out_csv}")
    return out_csv

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
                ids = extract_tg_message_ids_from_text(row[3])
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


def extract_pdf_filename(msg, urls):
    if isinstance(msg.media, MessageMediaDocument):
        attrs = getattr(msg.media.document, "attributes", []) or []
        for a in attrs:
            if isinstance(a, DocumentAttributeFilename):
                fn = (getattr(a, "file_name", "") or "").strip()
                if fn:
                    return fn
    for u in urls:
        m = re.search(r'/([^/?#]+\.pdf)(?:[?#].*)?$', u, re.I)
        if m:
            return m.group(1)
    return ""


def is_pdf_document_message(msg):
    if not isinstance(msg.media, MessageMediaDocument):
        return False
    mime = getattr(msg.media.document, "mime_type", "") or ""
    return "pdf" in mime.lower()


def looks_like_summary_text(text):
    if not text:
        return False
    markers = ("핵심 요약", "투자의견", "목표주가", "작성일:", "제목:")
    return text.strip().startswith("**") or any(k in text for k in markers)


def extract_title_from_summary_text(text):
    if not text:
        return ""
    m = re.search(r'(?:^|\n)\s*제목:\s*(.+)', text)
    if m:
        return m.group(1).strip()
    # 일부 포맷은 첫 줄 자체가 제목 성격일 수 있음
    first = text.strip().splitlines()[0].strip() if text.strip() else ""
    if first and len(first) <= 200:
        return first
    return ""

# =========================================================
# [메인] 실행 로직 (크롤링 메커니즘 유지: reverse=True, min_id)
# =========================================================
async def main():
    print("🚀 [소중한추억] 업데이트 봇 가동...")
    
    # 1. 시트 접속
    try:
        gc = get_gsheet_client()
        ss = gc.open_by_key(GSHEET_ID)
        ws = ss.worksheet(GSHEET_TAB)
        state_ws = get_or_create_state_ws(ss)
    except Exception as e:
        print(f"❌ 구글 시트 에러: {e}")
        return

    # 2. 시트 정보 로드
    sheet_last_id, existing_ids, last_row_num = fetch_sheet_info(ws)
    state_last_id = load_state_last_id(state_ws)

    # 3. 텔레그램 접속
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.connect()
    
    entity = await client.get_entity(CHANNEL_URL)
    latest = await client.get_messages(entity, limit=1)
    latest_msg_id = latest[0].id if latest else 0
    last_id = choose_effective_start_id(sheet_last_id, state_last_id, latest_msg_id)
    print(
        f"📊 시작 ID 결정 | sheet={sheet_last_id}, state={state_last_id}, latest={latest_msg_id} -> start={last_id}"
    )
    rows_dict = {}
    
    backfill_window = parse_backfill_window()
    ignore_existing_for_backfill = (
        BACKFILL_IGNORE_EXISTING in {"1", "true", "yes", "y"}
        or (BACKFILL_IGNORE_EXISTING == "" and backfill_window is not None and OUTPUT_MODE == "local")
    )
    if backfill_window:
        print(
            f"🔍 백필 스캔 시작 (기간: {backfill_window[0].date()} ~ {(backfill_window[1]-timedelta(seconds=1)).date()}, 최대 {ITER_LIMIT}개)..."
        )
        if ignore_existing_for_backfill:
            print("🧪 백필 모드: existing_ids 중복 차단을 무시하고 로컬 결과를 생성합니다.")
    else:
        print(f"🔍 스캔 시작 (기준 ID > {last_id}, 최대 {ITER_LIMIT}개)...")
    
    # 4. 수집 (기존 로직 유지: 과거->최신, min_id 사용)
    # [검증 완료] reverse=True를 사용하여 과거 메시지부터 순차적으로 가져오므로 데이터 누락 없음
    iter_kwargs = dict(entity=entity, limit=ITER_LIMIT, reverse=True)
    if backfill_window:
        _, end_local = backfill_window
        # 백필은 end 시점부터 과거로 내려가며(start 미만에서 중단) 수집해야 효율적이다.
        iter_kwargs["reverse"] = False
        iter_kwargs["limit"] = None
        iter_kwargs["offset_date"] = end_local.astimezone(timezone.utc)
    else:
        iter_kwargs["min_id"] = last_id

    async for msg in client.iter_messages(**iter_kwargs):
        if backfill_window:
            start_local, end_local = backfill_window
            msg_local = msg.date.astimezone(ZoneInfo(TZ_NAME))
            if msg_local >= end_local:
                continue
            if msg_local < start_local:
                break
        text = normalize_leading(msg.message)
        urls = extract_all_urls(text, msg.entities, msg)

        # 핵심 전환: A/B 번들 매칭 대신, 실제 PDF 첨부 메시지만 저장한다.
        if not is_pdf_document_message(msg):
            continue
            
        tg_link = f"https://t.me/DOC_POOL/{msg.id}"
            
        body_raw = strip_urls_from_text(text)
        kst_dt = msg.date.astimezone(ZoneInfo(TZ_NAME))
        date_str = kst_dt.strftime("%Y-%m-%d")
        
        if (not ignore_existing_for_backfill) and msg.id in existing_ids:
            continue

        pdf_name = extract_pdf_filename(msg, urls)
        message_cell = pdf_name or extract_title_from_summary_text(body_raw) or f"DOC_POOL_{msg.id}.pdf"
        summary_cell = body_raw

        row = {
            "msg_id": msg.id,
            "date": date_str,
            "message": message_cell,
            "tg_link": tg_link,
            "summary": summary_cell,
        }
        dedup_insert(rows_dict, row)
        
        if len(rows_dict) % 50 == 0:
            print(f"  ... {len(rows_dict)}건 수집 중")

    await client.disconnect()
    
    # 5. 정렬 (날짜 -> ID순)
    sorted_rows = sorted(rows_dict.values(), key=lambda r: (r["date"], r["msg_id"]))
    
    # 업로드 포맷 변환
    upload_data = []
    for r in sorted_rows:
        upload_data.append([r["date"], "", r["message"], r["tg_link"], r["summary"]])

    # [수정] 빈 결과 알림 전송 로직 추가
    if not upload_data:
        print("💤 업데이트할 신규 데이터가 없습니다.")
        send_telegram_smart([])
        return

    print(f"📤 {len(upload_data)}건 업로드 준비 중...")
    
    # 6. 업로드/로컬저장 & 알림
    try:
        if OUTPUT_MODE == "local":
            save_local_output(upload_data)
            print("🧪 테스트 모드(local): GSheet 미반영, state 미업데이트")
            print("🔕 테스트 모드(local): 텔레그램 알림 미전송")
        else:
            next_row = last_row_num + 1
            end_row = next_row + len(upload_data) - 1
            cell_range = f"A{next_row}:E{end_row}"
            ws.update(range_name=cell_range, values=upload_data, value_input_option="RAW")
            print(f"✅ 시트 업데이트 완료! (범위: {cell_range})")
            if sorted_rows:
                max_seen = max(x["msg_id"] for x in sorted_rows)
                save_state_last_id(state_ws, max_seen)
                print(f"✅ state 업데이트 완료: {max_seen}")
        
        if OUTPUT_MODE != "local":
            print("🔔 텔레그램 스마트 알림 전송 중...")
            send_telegram_smart([[r[0], r[1], r[2], r[3]] for r in upload_data])
        
    except Exception as e:
        print(f"❌ 처리 중 에러 발생: {e}")

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    asyncio.run(main())
