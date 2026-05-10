# Run State Logs (No GSheet state tabs)

이 저장소는 더 이상 Google Sheet에 `_state_*` 탭을 만들지 않습니다.

대신 각 실행마다 봇 상태를 `run_state/*.json`으로 남기고, GitHub Actions artifact(`run-state-logs`)로 업로드합니다.

## 어디서 확인하나
1. GitHub Actions -> `DocPool Update Bot` workflow 실행 선택
2. 실행 상세 하단 `Artifacts`에서 `run-state-logs` 다운로드
3. JSON 파일 확인

## 파일 종류
- `docpool_state_YYYYmmdd_HHMMSS.json`
- `companyreport_state_YYYYmmdd_HHMMSS.json`
- `papers_state_YYYYmmdd_HHMMSS.json`

## 주요 필드
- `sheet_last_id`: 실행 시작 시 GSheet 본문(D열 링크 등)에서 읽은 마지막 기준 ID
- `latest_msg_id`: 텔레그램 채널 최신 메시지 ID(해당 봇에서 지원 시)
- `start_id`: 이번 실행의 실제 스캔 시작 기준 ID
- `new_rows`: 이번 실행에서 신규로 적재한 행 수
- `max_seen_id`: 이번 실행에서 처리한 최대 ID
- `mode`: docpool의 경우 `gsheet`/`local`
- `backfill_from`, `backfill_to`: docpool 백필 실행 범위

## 장애 분석 예시
- `new_rows=0`인데 실제로 채널에 올라온 경우
  - `sheet_last_id`, `latest_msg_id`, `start_id` 간격 확인
  - `start_id`가 과도하게 크면 입력 파라미터(`DOCPOOL_FORCE_START_ID`) 확인
- 갑자기 대량 적재된 경우
  - 이전 실행 JSON과 `start_id`/`max_seen_id` 비교
  - workflow_dispatch 백필 입력값 사용 여부 확인

## 보관 정책
- artifact 보관 기간: 90일 (`docpool_routine.yml` 설정)
