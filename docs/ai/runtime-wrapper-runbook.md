# Runtime Wrapper (bedrock_gw.py) 운영 Runbook

## 배포 위치
- `/fsx/home/shared/bedrock-gateway/bedrock_gw.py`
- PYTHONPATH: `/etc/profile.d/bedrock-gw.sh`에서 자동 설정

## 사용법
```python
from bedrock_gw import converse
r = converse("us.anthropic.claude-haiku-4-5-20251001-v1:0", "안녕하세요")
```

## 429 (quota exceeded) 시 동작
- 대화형: `[Bedrock Gateway] 한도 소진` 메시지 + y/n 프롬프트 → y 시 approval request 생성
- 비대화형: 메시지 + `request_increase()` 사용 안내 출력

## 명시적 증액 요청
```python
from bedrock_gw import request_increase
request_increase("사유")
```

## Shell Hook과의 차이

| 항목 | Shell Hook | Runtime Wrapper |
|------|-----------|-----------------|
| trigger | Enter (PROMPT_COMMAND) | converse() 호출 시 429 |
| 경로 | /quota/status → 알림 | /converse → 429 → 안내 |
| 선제적 | 예 (90% 임박 시) | 아니오 (초과 후) |
| 비대화형 | 스킵 | 안내 메시지 출력 |

## 의존성
- boto3, botocore (conda 환경에서 제공)
- urllib.request (stdlib — requests 불필요)
- SigV4 서명 (BedrockUser-{username} assume-role)

## near-limit 경고
- remaining < 50K KRW 시 stderr로 잔여 한도 경고 출력
