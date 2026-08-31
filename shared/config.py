import os, json
from pathlib import Path
from dataclasses import dataclass, field

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)

@dataclass
class BotConfig:
    channel_url: str = ""
    sheet_tab: str = ""
    iter_limit: int = 10000

@dataclass
class Config:
    timezone: str = "Asia/Seoul"
    schedule_hours: list[int] = field(default_factory=lambda: [8, 13, 15, 18, 20])
    sheet_id: str = ""
    oauth_creds: str = ""
    client_secret: str = ""
    drive_folder_id: str = ""
    api_id: int = 0
    api_hash: str = ""
    session_string: str = ""
    bot_token: str = ""
    chat_id: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    email_from: str = ""
    email_to: str = ""
    email_subject_prefix: str = "[Reference]"
    bots: dict[str, BotConfig] = field(default_factory=dict)
    search_engine_tab: str = "Search Engine"
    search_engine_cell: str = "H2"

def load_config() -> Config:
    import yaml
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    cfg = Config()
    tz = raw.get("project", {})
    cfg.timezone = tz.get("timezone", "Asia/Seoul")
    cfg.schedule_hours = tz.get("schedule_hours", [8, 13, 15, 18, 20])
    g = raw.get("google", {})
    cfg.sheet_id = g.get("sheet_id", "")
    cfg.oauth_creds = os.path.expanduser(g.get("oauth_creds", ""))
    cfg.client_secret = os.path.expanduser(g.get("client_secret", ""))
    cfg.drive_folder_id = g.get("drive_folder_id", "")
    t = raw.get("telegram", {})
    cfg.api_id = int(_env("TELEGRAM_API_ID", str(t.get("api_id", 0))))
    cfg.api_hash = _env("TELEGRAM_API_HASH", t.get("api_hash", ""))
    cfg.session_string = _env("DOCPOOL_SESSION_STRING", "")
    cfg.bot_token = _env("BOT_TOKEN", "")
    cfg.chat_id = _env("CHAT_ID", "")
    s = raw.get("smtp", {})
    cfg.smtp_host = s.get("host", "smtp.gmail.com")
    cfg.smtp_port = int(s.get("port", 587))
    cfg.smtp_user = _env(s.get("user_env", "SMTP_USER"), "")
    cfg.smtp_password = _env(s.get("password_env", "SMTP_PASSWORD"), "")
    cfg.smtp_starttls = s.get("starttls", True)
    e = raw.get("email", {})
    cfg.email_from = _env(e.get("from_env", "EMAIL_FROM"), "")
    cfg.email_to = _env(e.get("to_env", "EMAIL_TO"), "")
    cfg.email_subject_prefix = e.get("subject_prefix", "[Reference]")
    for name, bc in raw.get("bots", {}).items():
        cfg.bots[name] = BotConfig(
            channel_url=bc.get("channel_url", ""),
            sheet_tab=bc.get("sheet_tab", ""),
            iter_limit=int(bc.get("iter_limit", 10000)),
        )
    se = raw.get("search_engine", {})
    cfg.search_engine_tab = se.get("tab_name", "Search Engine")
    cfg.search_engine_cell = se.get("status_cell", "H2")
    return cfg
