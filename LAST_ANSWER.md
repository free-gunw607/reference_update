# LAST_ANSWER.md

> Last updated: 2026-09-08

## What was done

### Google OAuth Token Expiry Diagnosis + Service Account Migration Plan (2026-09-08)

#### 문제 발견
- 5개 봇 모두 `invalid_grant: Token has been expired or revoked` 에러로 실패
- CI가 "success"로 표시되지만 try/except가 에러를 삼킴 → 실제 실패 은폐

#### 원인 추적
1. 토큰 마지막 갱신: 2026-08-31 22:21 UTC
2. 마지막 성공: 2026-09-07 08:56 UTC (+6.44일)
3. 최초 실패: 2026-09-07 13:22 UTC (+6.63일)
4. Google OAuth Testing mode: refresh token 7일 후 만료 → 정확히 일치
5. Amazon 크롤러는 CI에 `client_secret.json` 없어서 크래시 → 충돌 아님 확인
6. gcloud CLI 설치 + 토큰 교환 테스트 완료

#### 확인
- Google Cloud Console에서 OAuth consent screen "Testing" 상태 확인됨
- "Publish app" 버튼 비활성화 (Branding 설정 미완료)
- 새 refresh token 발급 → 로컬 + GitHub Secret 업데이트 완료
- 시트 접근 테스트 통과 (200 OK)

#### Service Account Migration Plan
- **목표**: OAuth User → Service Account로 전환하여 토큰 만료 영구 해결
- **상세 계획**: STATUS.md 참조 (8단계)
- **핵심 변경 파일**: `shared/gsheets.py`, `shared/config.py`, `config.yaml`
- **자동화**: 매 10일 CI 체크 + 텔레그램 알림
- **봇 구조 개선**: 텔레그램 연결을 시트 연결보다 먼저 (시트 실패 시에도 알림 가능)

#### Wisdomhouse
- WH-REFUP-009 등록: Google OAuth Testing mode 7일 만료 → Service Account 전환
- CATALOG.md 업데이트 완료
