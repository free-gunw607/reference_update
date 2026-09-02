# STATUS.md

> Last updated: 2026-09-02

## Current State

### Sheet Status

| Source | Sheet Tab | Rows | Unique IDs | Max ID | Status |
|--------|-----------|------|------------|--------|--------|
| DOC_POOL | `<데이터>소중한추억` | 52,939 | 52,939 | 205,344 | ✅ Complete |
| Papers | `<데이터>Papers` | 4,542 | 4,542 | 4,789 | ✅ Complete |
| Company Report | `<데이터>[주식] 증권사 리포트` | 21,176 | 21,176 | 137,413 | ✅ Complete |
| Quick Report | `<데이터>Quick Report` | 4,723 | 4,723 | 62,813 | ✅ Complete |
| SMIC | `SMIC 리포트` | 1,532 | 1,532 | 1,532 | ✅ Complete |
| Search Engine | `Search Engine` | 83,333 | - | - | ✅ Complete |

### Vault Stats

- docpool: 19,008 items, latest 2026-09-01
- papers: 4,541 items, latest 2026-05-24
- company_report: 8,434 items, latest 2026-08-31
- quick_report: 3,745 items, latest 2026-08-31
- smic: 764 items, latest 2026-06-10

### CI/CD

- GitHub Actions workflow: `Reference Update Bots` (active, 6x/day)
- Schedule: UTC `0 4,6,9,11,22,23 * * *` = KST 07,08,13,15,18,20
- All 12 secrets configured (TELEGRAM_API_ID, TELEGRAM_API_HASH, DOCPOOL_SESSION_STRING, BOT_TOKEN, CHAT_ID, SMTP_USER, SMTP_PASSWORD, EMAIL_FROM, EMAIL_TO, GOOGLE_SHEET_ID, GOOGLE_CLIENT_SECRET_JSON, GOOGLE_REFRESH_TOKEN_JSON)
- `workflow` scope added to `gh` OAuth token (2026-09-02)

### Key Fixes Applied (2026-09-02)

1. **asyncio event loop conflict**: Added `disconnect_all()` to `shared/telegram_client.py` and `run_all.py` to prevent event loop errors on Python 3.12+
2. **Vault fallback**: All 4 bots now read max ID from sheet when vault DB is empty (CI has fresh workspace each run)
3. **Company Report fallback**: Reads report ID from URL column instead of title column
4. **Sheet dedup**: Cleaned up duplicate rows caused by initial `start_id=0` runs
5. **DOC_POOL restore**: Restored 52,939 rows from vault + backup sheet after accidental clear

### Remaining Issues

- Vault DB is not persisted between CI runs (bots read from sheet as fallback)
- DOC_POOL bot scans from `start_id` based on sheet max ID (not vault state)
- `GDRIVE_CREDS` and `GEMINI_API_KEY` secrets exist but are unused
