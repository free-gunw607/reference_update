import json, sqlite3
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

DB_PATH = Path(__file__).parent.parent / "data" / "vault.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS crawl_runs (
    run_id TEXT PRIMARY KEY,
    bot_name TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    trigger TEXT,
    status TEXT,
    new_count INTEGER DEFAULT 0,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS bot_state (
    bot_name TEXT PRIMARY KEY,
    last_msg_id INTEGER DEFAULT 0,
    last_date TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT,
    topic TEXT,
    payload TEXT,
    created_at TEXT,
    sent_at TEXT,
    attempts INTEGER DEFAULT 0,
    last_error TEXT,
    status TEXT DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS docpool_items (
    msg_id INTEGER PRIMARY KEY,
    date TEXT,
    pdf_name TEXT,
    tg_link TEXT,
    summary TEXT,
    first_seen_at TEXT
);
CREATE TABLE IF NOT EXISTS papers_items (
    msg_id INTEGER PRIMARY KEY,
    date TEXT,
    title TEXT,
    tg_link TEXT,
    first_seen_at TEXT
);
CREATE TABLE IF NOT EXISTS company_report_items (
    report_id INTEGER PRIMARY KEY,
    date TEXT,
    tag TEXT,
    title TEXT,
    summary TEXT,
    source_url TEXT,
    first_seen_at TEXT
);
CREATE TABLE IF NOT EXISTS quick_report_items (
    msg_id INTEGER PRIMARY KEY,
    date TEXT,
    tag TEXT,
    title TEXT,
    firm TEXT,
    tg_link TEXT,
    summary TEXT,
    first_seen_at TEXT
);
CREATE TABLE IF NOT EXISTS smic_items (
    article_url TEXT PRIMARY KEY,
    publish_date TEXT,
    company_name TEXT,
    pdf_url TEXT,
    drive_link TEXT,
    first_seen_at TEXT
);
CREATE TABLE IF NOT EXISTS search_index (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_tab TEXT,
    date TEXT,
    report_name TEXT,
    link TEXT,
    notes TEXT,
    keywords TEXT,
    UNIQUE(source_tab, link)
);
"""

class Vault:
    def __init__(self, tz: str = "Asia/Seoul", db_path: Path | str | None = None):
        self.tz = ZoneInfo(tz)
        self.db_path = Path(db_path) if db_path else DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def now_iso(self) -> str:
        return datetime.now(self.tz).isoformat()

    def start_run(self, bot_name: str, trigger: str = "cron") -> str:
        run_id = f"{bot_name}_{datetime.now(self.tz).strftime('%Y%m%d_%H%M%S')}"
        self.conn.execute(
            "INSERT INTO crawl_runs (run_id, bot_name, started_at, trigger, status) VALUES (?, ?, ?, ?, 'running')",
            (run_id, bot_name, self.now_iso(), trigger),
        )
        self.conn.commit()
        return run_id

    def finish_run(self, run_id: str, status: str, new_count: int = 0, detail: str = ""):
        self.conn.execute(
            "UPDATE crawl_runs SET finished_at=?, status=?, new_count=?, detail=? WHERE run_id=?",
            (self.now_iso(), status, new_count, detail, run_id),
        )
        self.conn.commit()

    def get_state(self, bot_name: str) -> dict:
        row = self.conn.execute("SELECT * FROM bot_state WHERE bot_name=?", (bot_name,)).fetchone()
        if row:
            return dict(row)
        return {"bot_name": bot_name, "last_msg_id": 0, "last_date": "", "updated_at": ""}

    def set_state(self, bot_name: str, last_msg_id: int, last_date: str = ""):
        self.conn.execute(
            "INSERT OR REPLACE INTO bot_state (bot_name, last_msg_id, last_date, updated_at) VALUES (?, ?, ?, ?)",
            (bot_name, last_msg_id, last_date, self.now_iso()),
        )
        self.conn.commit()

    def get_all_source_stats(self) -> dict:
        stats = {}
        for bot_name, table in [
            ("docpool", "docpool_items"),
            ("papers", "papers_items"),
            ("company_report", "company_report_items"),
            ("quick_report", "quick_report_items"),
            ("smic", "smic_items"),
        ]:
            try:
                row = self.conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
                count = row["cnt"] if row else 0
                state = self.get_state(bot_name)
                stats[bot_name] = {
                    "count": count,
                    "last_date": state.get("last_date", ""),
                    "ok": True,
                }
            except Exception:
                stats[bot_name] = {"count": 0, "last_date": "", "ok": False}
        return stats

    def insert_items(self, table: str, items: list[dict], key_col: str):
        now = self.now_iso()
        for item in items:
            cols = list(item.keys())
            vals = list(item.values())
            if "first_seen_at" not in cols:
                cols.append("first_seen_at")
                vals.append(now)
            placeholders = ", ".join(["?"] * len(cols))
            col_str = ", ".join(cols)
            self.conn.execute(
                f"INSERT OR IGNORE INTO {table} ({col_str}) VALUES ({placeholders})",
                vals,
            )
        self.conn.commit()

    def add_to_search_index(self, source_tab: str, date: str, name: str, link: str, notes: str = "", keywords: str = ""):
        self.conn.execute(
            "INSERT OR IGNORE INTO search_index (source_tab, date, report_name, link, notes, keywords) VALUES (?, ?, ?, ?, ?, ?)",
            (source_tab, date, name, link, notes, keywords),
        )
        self.conn.commit()

    def close(self):
        self.conn.close()
