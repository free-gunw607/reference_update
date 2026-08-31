# reference_update Bots

Unified Telegram channel crawler and Google Sheets updater.

## Sources
- **DOC_POOL** → `<데이터>소중한추억` tab
- **Papers** → `<데이터>Papers` tab
- **Company Report** → `<데이터>[주식]증권사 리포트` tab
- **Quick Report** → `<데이터>Quick Report` tab (NEW)
- **SMIC** → `SMIC 리포트` tab (web scraping)

## Quick Start
```bash
pip install -r requirements.txt
# Set env vars: DOCPOOL_SESSION_STRING, BOT_TOKEN, CHAT_ID, SMTP_*, EMAIL_*
python run_all.py --bots all --excel --search-update
```

## Individual Bot
```bash
python run_all.py --bots docpool
python run_all.py --bots smic
python run_all.py --search "삼성전자"
```

## Cron (GitHub Actions)
- 5x/day: docpool, papers, company_report, quick_report
- 1x/day: smic
