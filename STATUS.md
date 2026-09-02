# reference_update - STATUS

> Last updated: 2026-09-01

## Overview

Telegram bots that crawl PDF reports from 5 sources and publish to Google Sheets + SQLite + Telegram notifications + Email.

## Source Status

| Source | Sheet Tab | Data Rows | Date Range | Status |
|--------|-----------|-----------|------------|--------|
| DOC_POOL | `<데이터>소중한추억` | 52,938 | 2025-03-24 ~ 2026-09-01 | ✅ Complete |
| Papers | `<데이터>Papers` | 9,082 | 2023-05-06 ~ 2026-05-24 | ✅ Complete |
| Company Report | `<데이터>[주식] 증권사 리포트` | 37,574 | 2025-10-31 ~ 2026-08-31 | ✅ Complete |
| Quick Report | `<데이터>Quick Report` | 4,657 | 2025-05-01 ~ 2026-09-01 | ✅ Complete |
| SMIC | `SMIC 리포트` | 1,532 | 2013-09-18 ~ 2026-06-10 | ✅ Complete |
| **Search Engine** | `Search Engine` | 83,332 | Cross-source | ✅ Complete |

## Architecture

```
reference_update/
├── bots/
│   ├── docpool.py          # DOC_POOL Telegram channel crawler
│   ├── papers.py           # Papers Telegram channel crawler
│   ├── company_report.py   # Company Report Telegram channel crawler
│   ├── quick_report.py     # Quick Report Telegram channel crawler
│   └── smic.py             # SMIC web scraper (snusmic.com)
├── shared/
│   ├── config.py           # YAML config loader
│   ├── vault.py            # SQLite (crawl_runs, bot_state, outbox, item tables)
│   ├── gsheets.py          # OAuth2 Google Sheets + Drive
│   ├── notify.py           # Email (Gmail SMTP) + Telegram notifications
│   ├── telegram_client.py  # Telethon client (Python 3.14 compatible)
│   └── search_engine.py    # Status panel + keyword search
├── run_all.py              # Unified CLI runner
├── config.yaml             # Bot + sheet + search configuration
├── .env                    # Credentials
└── .github/workflows/
    ├── update_bots.yml     # 5x/day cron
    └── smic.yml            # 1x/day cron
```

## Key Details

- **Owner**: 박건우 (Liam Park), Telegram ID: `8981319162`
- **Bot**: `@liam_everyfoward_bot`
- **Google Sheet**: `19Q3KNbFu0ftr2hAqEdNwhf_UQvYXiXa2Vvk8lv9S6JY`
- **Backup Sheet**: `1c-iCE2FTA6Kn9xBhwBHTXLfLQVPT4wCN2i6eJtDvCaU`
- **Virtual env**: `.venv/` (Python 3.14)
- **GitHub**: `https://github.com/free-gunw607/reference_update.git`

## Bots Configuration

| Bot | Channel | Cron Schedule |
|-----|---------|---------------|
| docpool | @DOC_POOL | 5x/day (09,12,15,18,21 KST) |
| papers | @Papers | 5x/day |
| company_report | @_accounting7 | 5x/day |
| quick_report | @quick_report | 5x/day |
| smic | snusmic.com | 1x/day (midnight KST) |

## Google Sheet Tabs

| Tab | Columns |
|-----|---------|
| `<데이터>소중한추억` | A=날짜, B=blank, C=파일명, D=텔레그램 링크, E=요약 |
| `<데이터>Papers` | A=날짜, B=blank, C=제목, D=텔레그램 링크 |
| `<데이터>[주식] 증권사 리포트` | A=날짜, B=태그, C=메시지, D=stockinfo7_url |
| `<데이터>Quick Report` | A=날짜, B=태그, C=제목, D=텔레그램 링크, E=요약 |
| `SMIC 리포트` | A=날짜, B="Equity Research", C=회사명, D=drive_link, E=비고 |
| `Search Engine` | H2=상태패널, A-G=통합검색 데이터 |

## Session Summary (2026-09-01)

### Completed Work
1. **DOC_POOL full backfill**: Scanned IDs 20,072→81,549 (16,240 PDFs) + IDs 155,561→155,800 (40 PDFs). Sheet rebuilt from backup + vault data, sorted by date, deduped to 52,938 rows.
2. **SMIC full crawl**: WP API scrape of 764 reports, uploaded to sheet (no Drive upload for speed).
3. **Search Engine upgrade**: Merged all 5 sources into 83,332 rows. Sheet resized to 90K rows. Status panel updated.
4. **Quick Report backfill**: Found 776 missing PDFs in 2025-05 range via `iter_messages` scan. Sheet now has 4,657 IDs matching channel exactly (0 missing).
5. **telegram_client.py fix**: Changed `client.connect()` to `client.start()` for Python 3.14 compatibility.
6. **Google Sheet backup**: Created `AGORA_Reference_BACKUP_20260831`.
7. **OAuth2 scope expansion**: Added Drive scope to Google API credentials.

### Files Created/Modified
- `backfill_docpool.py`, `backfill_docpool_gaps.py` - DOC_POOL backfill scripts
- `backfill_quick_report.py`, `backfill_quick_report_v2.py` - Quick Report backfill scripts
- `sort_docpool.py`, `rebuild_docpool.py` - Sheet maintenance scripts
- `refresh_search_engine.py` - Search Engine data refresh
- `run_smic.py` - SMIC fast runner (no Drive upload)
- `shared/telegram_client.py` - Fixed for Python 3.14
- `bots/smic.py` - Fixed scrape_smic_latest() to handle API errors
- `shared/search_engine.py` - Status panel + search functions
