# STATUS.md

> Last updated: 2026-09-08

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

### Critical Incident: Google OAuth Token Expiry (2026-09-07~08)

- **증상**: 5개 봇 모두 `invalid_grant: Token has been expired or revoked` 에러로 완전 중단
- **최초 실패**: 2026-09-07 13:22 UTC (KST 22:22)
- **마지막 성공**: 2026-09-07 08:56 UTC (KST 17:56)
- **원인**: Google Cloud 프로젝트 `smic-486312`의 OAuth consent screen이 "Testing" 모드 → refresh token이 7일 후 자동 만료됨
- **근거**: 토큰 마지막 갱신 Aug 31 22:21 UTC → +6.6일 = Sep 7 13:22 UTC (정확히 만료)
- **영향**: 시트 업로드, 텔레그램 알림, 이메일 알림 전부 중단 (3일간)
- **즉시 조치**: 새 refresh token 발급 → 로컬 + CI 업데이트 (2026-09-08)
- **근본 해결**: Service Account로 전환 (아래 계획 참조)
- **WH 등록**: WH-REFUP-009

### Service Account Migration Plan (2026-09-08)

OAuth User → Service Account로 전환하여 토큰 만료 문제 영구 해결.

| 단계 | 작업 | 파일 | 상태 |
|------|------|------|------|
| 1 | Service Account 생성 + JSON 키 다운로드 | `~/.config/gsheet-sync/service_account.json` | 예정 |
| 2 | Google Sheet에 Service Account 권한 부여 (편집자) | Google Sheet 공유 설정 | 예정 |
| 3 | `shared/gsheets.py` Service Account 인증으로 변경 | `shared/gsheets.py` | 예정 |
| 4 | `shared/config.py`에 `service_account` 필드 추가 | `shared/config.py` | 예정 |
| 5 | `config.yaml`에 `service_account` 경로 추가 | `config.yaml` | 예정 |
| 6 | 매 10일 자동 체크 스크립트 생성 | `scripts/check_service_account.py` | 예정 |
| 7 | 매 10일 CI workflow 생성 | `.github/workflows/service_account_check.yml` | 예정 |
| 8 | 봇 구조 개선 (텔레그램 연결을 시트 연결보다 먼저) | `bots/*.py`, `run_all.py` | 예정 |

**기대 효과**: 토큰 만료 없음 (90일 자동 갱신), 로컬/CI 독립 인증, 자동 알림

### Remaining Issues

- Service Account 전환 미완료 (위 계획 참조)
- 봇 구조 개선 미완료 (텔레그램 연결이 시트 연결보다 늦음 → 시트 실패 시 알림 불가)
- 토큰 만료 알림 없음 (매 10일 자동 체크로 해결 예정)
- Vault DB is not persisted between CI runs (bots read from sheet as fallback)
- DOC_POOL bot scans from `start_id` based on sheet max ID (not vault state)
- `GDRIVE_CREDS` and `GEMINI_API_KEY` secrets exist but are unused

### Wisdomhouse Promotion

- Episode: `EP-REFUP-20260902-01`
- Knowledge IDs: `WH-REFUP-001` through `WH-REFUP-008`
- Canonical document: [`by-repo/reference_update.md`](../../../agent-system/A2-workspace-memory/Wisdomhouse/by-repo/reference_update.md)
- Promoted: 2026-09-02
