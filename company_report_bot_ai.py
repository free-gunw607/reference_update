import os, sys, re, json, asyncio, requests, time
import base64
from datetime import datetime
from pathlib import Path
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

CHANNEL_URL = "https://t.me/companyreport"
GSHEET_ID = "19Q3KNbFu0ftr2hAqEdNwhf_UQvYXiXa2Vvk8lv9S6JY"
GSHEET_TAB = "<데이터>[주식] 증권사 리포트"
TZ_NAME = "Asia/Seoul"
ITER_LIMIT = 10000 

STOCKINFO_RE = re.compile(r"https?://stockinfo7\.com/stock/report/url/(\d+)", re.I)
CONSENSUS_RE = re.compile(r"https?://consensus\.hankyung\.com/\S*?report_idx=(\d+)", re.I)
URL_RE = re.compile(r'https?://\S+', re.I)
LEADING_JUNK = re.compile(r'^[\u200B-\u200F\u202A-\u202E\u2060-\u2069\ufeff\s\r\n\t]+', re.S)
RUN_STATE_DIR = Path("run_state")

try:
    TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
    MY_CHAT_ID = os.environ.get('MY_CHAT_ID')
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
except:
    TELEGRAM_TOKEN = None
    MY_CHAT_ID = None
    GEMINI_API_KEY = None

# =========================================================
# [기능 1] AI 요약 모듈 (REST API + 2.0 Model List)
# =========================================================
def get_ai_summary_for_trial(target_url, title):
    if not GEMINI_API_KEY or not target_url:
        return None

    print(f"🤖 [AI Trial] '{title}' 요약 시도 중 (REST API)...")
    
    try:
        # 1. PDF 다운로드
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(target_url, headers=headers, timeout=20, allow_redirects=True)
        
        if response.status_code != 200:
            print(f"  ❌ 다운로드 실패 (Status: {response.status_code})")
            return None

        pdf_bytes = response.content
        if not pdf_bytes.startswith(b'%PDF'):
            print(f"  ❌ PDF 형식이 아닙니다.")
            return None

        # 2. Base64 인코딩
        b64_data = base64.b64encode(pdf_bytes).decode('utf-8')

        # 3. 모델 리스트 순회 (사용자 리스트 기반)
        # 중요: 사용자 계정에 존재하는 모델들만 순서대로 시도
        models_to_try = [
            "gemini-2.0-flash",                # 1순위: 2.0 정식
            "gemini-2.0-flash-001",            # 2순위: 2.0 버전 지정
            "gemini-2.0-flash-lite-preview-02-05", # 3순위: 라이트 (가볍고 무료일 확률 높음)
            "gemini-flash-latest"              # 4순위: 최신 플래시 별명
        ]
        
        summary_text = None

        for model_name in models_to_try:
            print(f"  Trying model: {model_name}...")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
            
            payload = {
                "contents": [{
                    "parts": [
                        {
                            "text": (
                                "이 주식 리포트를 읽고 투자자가 알아야 할 핵심 내용을 3개 항목(bullet point)으로 요약해줘. "
                                "수치(목표주가, 실적 등)가 있다면 반드시 포함해. "
                                "말투는 '~함', '~임'체로 간결하게 한국어로 작성해."
                            )
                        },
                        {
                            "inline_data": {
                                "mime_type": "application/pdf",
                                "data": b64_data
                            }
                        }
                    ]
                }]
            }
            
            try:
                api_res = requests.post(
                    url, 
                    headers={'Content-Type': 'application/json'},
                    data=json.dumps(payload),
                    timeout=30
                )
                
                if api_res.status_code == 200:
                    res_json = api_res.json()
                    try:
                        summary_text = res_json['candidates'][0]['content']['parts'][0]['text']
                        print(f"  ✅ 성공! ({model_name})")
                        break # 성공하면 반복 탈출
                    except:
                        print(f"    ⚠️ 응답 파싱 오류 ({model_name})")
                        continue
                else:
                    # 404(Not Found)나 429(Quota)면 다음 모델 시도
                    # 에러 메시지를 짧게 출력
                    print(f"    Fail ({model_name}): {api_res.status_code}")
                    continue

            except Exception as e:
                print(f"    Error ({model_name}): {e}")
                continue
        
        if summary_text:
            return summary_text.strip()
        else:
            print("  ❌ 모든 모델 시도 실패. (Quota 문제일 수 있음)")
            return None

    except Exception as e:
        print(f"  ⚠️ 시스템 에러 (무시함): {e}")
        return None

# =========================================================
# [기능 2] 텔레그램 스마트 알림
# =========================================================
def send_telegram_smart(new_rows, ai_summary_text=None):
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
        f"📈 <b>[{time_tag} | {seq_title}] 증권사 리포트 업데이트</b>\n"
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
    last_item_idx = len(new_rows) 
    
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
        
        if idx == last_item_idx and ai_summary_text:
            line += f"\n🤖 <b>[AI 핵심 요약]</b>\n{ai_summary_text}\n"

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
# [기능 3] 리포트 ID 및 태그 추출
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
# [기능 4] 구글 시트 유틸
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

def choose_effective_start_id(sheet_last_id):
    candidates = [x for x in (sheet_last_id,) if isinstance(x, int) and x >= 0]
    if not candidates:
        return 0
    return max(candidates)

def write_run_state(payload):
    RUN_STATE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(ZoneInfo(TZ_NAME)).strftime("%Y%m%d_%H%M%S")
    path = RUN_STATE_DIR / f"companyreport_state_{ts}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"🧾 런 상태 로그 저장: {path}")

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
# [기능 5] 파싱 유틸
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
# [메인] 실행 로직
# =========================================================
async def main():
    print("🚀 [주식 증권사 리포트] 봇 가동 (AI Trial - Validated Models)...")
    
    try:
        gc = get_gsheet_client()
        ss = gc.open_by_key(GSHEET_ID)
        ws = ss.worksheet(GSHEET_TAB)
    except Exception as e:
        print(f"❌ 시트 접속 에러: {e}")
        return

    sheet_last_id, existing_ids, last_row_num = fetch_sheet_info(ws)
    last_id = choose_effective_start_id(sheet_last_id)
    print(
        f"📊 시작 ID 결정 | sheet={sheet_last_id} -> start={last_id}"
    )

    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.connect()
    
    entity = await client.get_entity(CHANNEL_URL)
    rows_dict = {}
    
    print(f"🔍 스캔 시작 (최대 {ITER_LIMIT}개)...")

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
        
        if last_id > 0 and found_rid <= last_id:
            print(f"🛑 기준 ID({last_id}) 도달. 스캔 종료.")
            break
            
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
    
    sorted_rows = sorted(rows_dict.values(), key=lambda r: r["rid"])
    
    upload_data = []
    for r in sorted_rows:
        upload_data.append([r["date"], r["tag"], r["message"], r["link"]])

    if not upload_data:
        print("💤 신규 업데이트 없음.")
        write_run_state({
            "bot": "company_report_ai",
            "timestamp_kst": datetime.now(ZoneInfo(TZ_NAME)).isoformat(),
            "sheet_tab": GSHEET_TAB,
            "sheet_last_id": sheet_last_id,
            "start_id": last_id,
            "new_rows": 0,
            "max_seen_id": None,
        })
        send_telegram_smart([])
        return

    print(f"📤 {len(upload_data)}건 처리 중...")
    
    # [AI Trial Logic]
    ai_summary = None
    if upload_data:
        latest_row = upload_data[-1]
        latest_title = latest_row[2]
        latest_link = latest_row[3]
        
        if latest_link.startswith("http") and "t.me" not in latest_link:
             ai_summary = get_ai_summary_for_trial(latest_link, latest_title)
        else:
             print("  ⚠️ 최신 항목 링크가 요약 가능한 URL이 아님 (Skip)")
    
    try:
        next_row = last_row_num + 1
        end_row = next_row + len(upload_data) - 1
        cell_range = f"A{next_row}:D{end_row}"
        
        ws.update(range_name=cell_range, values=upload_data, value_input_option="RAW")
        print(f"✅ 시트 저장 완료 (범위: {cell_range})")
        max_seen = max(x["rid"] for x in sorted_rows) if sorted_rows else None
        write_run_state({
            "bot": "company_report_ai",
            "timestamp_kst": datetime.now(ZoneInfo(TZ_NAME)).isoformat(),
            "sheet_tab": GSHEET_TAB,
            "sheet_last_id": sheet_last_id,
            "start_id": last_id,
            "new_rows": len(upload_data),
            "max_seen_id": max_seen,
            "ai_summary_generated": bool(ai_summary),
        })
        
        send_telegram_smart(upload_data, ai_summary_text=ai_summary)
        
    except Exception as e:
        print(f"❌ 에러 발생: {e}")

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    asyncio.run(main())
