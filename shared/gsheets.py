import json, os, tempfile
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import gspread

_creds_cache = None


def _read_json_env_or_file(env_key: str, file_path: str) -> dict:
    raw = os.environ.get(env_key, "")
    if raw:
        return json.loads(raw)
    p = Path(file_path).expanduser()
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def get_credentials():
    global _creds_cache
    if _creds_cache and not _creds_cache.expired:
        return _creds_cache

    from shared.config import load_config
    cfg = load_config()

    rt = _read_json_env_or_file("GOOGLE_REFRESH_TOKEN_JSON", cfg.oauth_creds)
    cs = _read_json_env_or_file("GOOGLE_CLIENT_SECRET_JSON", cfg.client_secret)
    installed = cs.get("installed", cs.get("web", {}))

    creds = Credentials(
        token=rt.get("token", ""),
        refresh_token=rt.get("refresh_token", ""),
        token_uri=installed.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=installed.get("client_id", ""),
        client_secret=installed.get("client_secret", ""),
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    creds.refresh(Request())
    _creds_cache = creds
    return creds


def get_gspread_client():
    creds = get_credentials()
    return gspread.authorize(creds)


def get_drive_service():
    from googleapiclient.discovery import build
    creds = get_credentials()
    return build("drive", "v3", credentials=creds)


def get_sheet(sheet_id: str, tab_name: str):
    gc = get_gspread_client()
    ss = gc.open_by_key(sheet_id)
    return ss.worksheet(tab_name)


def ensure_sheet_capacity(ws, required_rows):
    current = ws.row_count
    if required_rows > current:
        new_count = max(required_rows + 1000, int(current * 1.5))
        ws.resize(rows=new_count)
        print(f"📐 Sheet resized: {current} → {new_count} rows")


def write_source_panel(ws, source_url, sheet_tab, last_date, count):
    """Write metadata panel to columns G-H of a source sheet."""
    panel = [
        ["레퍼런스 소스 정보", ""],
        ["소스", source_url],
        ["시트 탭", sheet_tab],
        ["최근 업데이트", last_date],
        ["총 행 수", f"{count:,}"],
    ]
    ws.update("G2:H6", panel, value_input_option="RAW")
