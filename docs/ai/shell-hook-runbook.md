# Shell Hook 운영 Runbook

## 배포 위치
- `/etc/profile.d/bedrock-gw.sh` (root:root 644) — login shell 자동 로드
- `/etc/bash.bashrc`에 source 라인 — non-login interactive shell (screen, VS Code)

## 동작 범위

| 환경 | 로드 경로 | 동작 확인 |
|------|-----------|-----------|
| SSH login | /etc/profile.d/ | PASS |
| tmux | /etc/profile.d/ (login) 또는 /etc/bash.bashrc (non-login) | PASS |
| screen | /etc/bash.bashrc | PASS |
| VS Code Remote terminal | /etc/bash.bashrc → __vsc_original_prompt_command 체이닝 | PASS |
| VS Code split terminal | 동일 | PASS |
| cron / non-interactive | 스킵 (`[[ $- == *i* ]]` 체크) | 정상 |

## Hybrid Hook 구조
- Primary: PROMPT_COMMAND에 `_bedrock_gw_check` 등록
- Fallback: trap DEBUG watchdog — 사용자가 PROMPT_COMMAND를 덮어써도 복구

## Cooldown 파일
- `~/.cache/bedrock-gw/last-check` — 60초 cooldown (API 호출 간격)
- `~/.cache/bedrock-gw/suppressed` — 60초 suppress (사용자가 N 선택 후)

## 상태별 동작

| 상태 | 동작 |
|------|------|
| usage < 90% | 조용히 통과 |
| usage >= 90%, no pending | 알림 박스 + y/N 프롬프트 |
| pending approval 존재 | "승인 대기 중" 메시지 1회 표시 |
| hard cap 도달 | "추가 증액 불가" 메시지 |
| _BEDROCK_GW_REQUESTED=1 | 세션 내 재질문 중단 |

## Troubleshooting
- 알림 안 뜸: `rm -rf ~/.cache/bedrock-gw` 후 Enter
- hook 미로드: `type _bedrock_gw_check` 확인, 없으면 `source /etc/profile.d/bedrock-gw.sh`
- boto3 없음: conda 미활성 → `bash -l` 로 login shell 전환
- PROMPT_COMMAND 확인: `declare -p PROMPT_COMMAND`

## 세션 연속성

| 경로 | trigger | 사용자 입력 | approval 생성 위치 | 작업 연속성 |
|------|---------|------------|-------------------|------------|
| Shell hook | Enter (PROMPT_COMMAND) | y/N | API Gateway /approval/request | 동일 세션에서 계속 |
| Runtime wrapper | converse() 호출 시 429 | y/n (대화형) 또는 안내 (비대화형) | API Gateway /approval/request | 동일 Python 세션에서 계속 |
