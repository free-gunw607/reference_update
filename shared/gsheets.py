import json
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import gspread

_creds_cache = None

def get_credentials():
    global _creds_cache
    if _creds_cache and not _creds_cache.expired:
        return _creds_cache

    from shared.config import load_config
    cfg = load_config()

    rt_path = Path(cfg.oauth_creds)
    cs_path = Path(cfg.client_secret)

    rt = json.loads(rt_path.read_text(encoding="utf-8"))
    cs = json.loads(cs_path.read_text(encoding="utf-8"))
    installed = cs.get("installed", {})

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
