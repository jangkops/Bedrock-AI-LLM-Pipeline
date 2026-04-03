# Shell Hook 환경별 검증 보고서

## Date: 2026-03-27
## Test target: r7 (i-0c30cae12f60d69d1), user: cgjang
## Test state: 460K/500K (92%), should_prompt=true

---

## 1. 현재 수정안에 대한 판정

### 요구사항 1 (사용자 dotfile 비의존): 충족

현재 통제 지점:
- `/etc/profile.d/bedrock-gw.sh` — root 소유, 644, 시스템 파일
- `/etc/bash.bashrc` — root 소유, 644, 시스템 파일 (1줄 추가)

사용자 홈 파일 의존: 없음. 아래 모두 검증됨:
- 정상 .bashrc → 함수 로드됨
- 빈 .bashrc → 함수 로드됨
- .bashrc 삭제 → 함수 로드됨
- .bashrc에서 PROMPT_COMMAND 덮어쓰기 → 함수 로드됨 (PROMPT_COMMAND 등록은 별도 분석 필요)

### 요구사항 2 (VS Code Remote 실제 검증): 검증 불가

정확한 이유:
- cgjang의 `.vscode-server/cli/servers/` 에 `.staging` 디렉토리만 존재
- shell integration 파일 (`shellIntegration-bash.sh`) 없음
- VS Code server binary (`code-server`, `node`) 없음
- 즉, VS Code Remote가 r7에 완전히 설치되지 않은 상태

VS Code Remote terminal의 shell init 체인을 실증하려면:
1. 실제로 VS Code에서 r7에 Remote SSH 접속
2. integrated terminal을 열어서 `type _bedrock_gw_check` 및 `echo $PROMPT_COMMAND` 확인
3. 이 작업은 SSM으로 불가능 — VS Code client에서 직접 접속해야 함

### 한 줄 결론
요구사항 1은 충족. 요구사항 2는 VS Code server 미설치로 실증 불가 — 사용자가 직접 VS Code Remote 접속 후 확인 필요.

---

## 2. 구조 분석

### Hook 로딩 경로

```
시스템 파일 (root 소유, 사용자 수정 불가):
  /etc/profile.d/bedrock-gw.sh    ← hook 본체 (함수 정의 + PROMPT_COMMAND 등록)
  /etc/bash.bashrc                ← non-login shell용 source 1줄

로딩 체인:
  Login shell:     /etc/profile → /etc/profile.d/bedrock-gw.sh → 로드됨
  Non-login shell: /etc/bash.bashrc → /etc/profile.d/bedrock-gw.sh → 로드됨
  Non-interactive: /etc/bash.bashrc의 [ -z "$PS1" ] && return 에서 중단 → 로드 안 됨 (정상)
```

### 사용자 dotfile 의존도: 0

- `/fsx/home/<user>/.bashrc` — 읽지 않음, 수정하지 않음, 의존하지 않음
- `/fsx/home/<user>/.bash_profile` — 동일
- `/fsx/home/<user>/.profile` — 동일
- 사용자가 이 파일들을 삭제/변경/교체해도 hook 로딩에 영향 없음

### 중복 source 방지

hook 스크립트에 `_BEDROCK_GW_LOADED` guard:
- login shell에서 profile.d로 1번 로드
- bash.bashrc에서 다시 source 시도 → guard에서 return
- PROMPT_COMMAND 등록만 재확인 (이미 있으면 skip)

### Cache/Suppress 파일 위치

- `~/.cache/bedrock-gw/last-check` — cooldown (60초)
- `~/.cache/bedrock-gw/suppressed` — suppress (60초)
- 이 파일들은 사용자 홈에 있지만, 정책 강제 지점이 아님 (캐시일 뿐)
- 삭제해도 다음 체크에서 재생성됨

---

## 3. 환경별 검증 결과 표

| # | 환경 | login/non-login | interactive | init 로드 | 함수 정의 | PROMPT_COMMAND | 실제 prompt | user dotfile 의존 | 판정 |
|---|------|-----------------|-------------|-----------|-----------|----------------|-------------|-------------------|------|
| 1 | SSH bash login | login | ✅ | profile.d | ✅ | ✅ | ✅ 실증 | 없음 | PASS |
| 2 | SSH bash non-login interactive | non-login | ✅ | bash.bashrc→profile.d | ✅ | ✅ | ✅ 실증 (screen 경유) | 없음 | PASS |
| 3 | SSH bash non-interactive | non-login | ❌ | bash.bashrc 중단 | ❌ | ❌ | ❌ (정상) | 없음 | PASS |
| 4 | tmux new-session | login | ✅ | profile.d | ✅ | ✅ | ✅ 실증 | 없음 | PASS |
| 5 | tmux attach | (기존 세션) | ✅ | 이미 로드됨 | ✅ | ✅ | ✅ (cooldown 내 skip) | 없음 | PASS |
| 6 | tmux new-pane | login | ✅ | profile.d | ✅ | ✅ | ✅ (cooldown 내 skip) | 없음 | PASS |
| 7 | screen new | non-login | ✅ | bash.bashrc→profile.d | ✅ | ✅ | ✅ 실증 | 없음 | PASS |
| 8 | screen attach | (기존 세션) | ✅ | 이미 로드됨 | ✅ | ✅ | ✅ (cooldown 내 skip) | 없음 | PASS |
| 9 | VS Code Remote terminal | non-login (예상) | ✅ (예상) | bash.bashrc→profile.d (예상) | 미검증 | 미검증 | 미검증 | 없음 | 보류 |
| 10 | VS Code new terminal | non-login (예상) | ✅ (예상) | 동일 (예상) | 미검증 | 미검증 | 미검증 | 없음 | 보류 |
| 11 | VS Code split terminal | non-login (예상) | ✅ (예상) | 동일 (예상) | 미검증 | 미검증 | 미검증 | 없음 | 보류 |
| 12 | tmux inside vscode | login | ✅ (예상) | profile.d (예상) | 미검증 | 미검증 | 미검증 | 없음 | 보류 |
| 13 | screen inside vscode | non-login | ✅ (예상) | bash.bashrc (예상) | 미검증 | 미검증 | 미검증 | 없음 | 보류 |
| 14 | bash -lc (non-interactive) | login | ❌ | profile.d | ✅ (함수만) | 설정됨 | ❌ (정상) | 없음 | PASS |
| 15 | ssh remote-command | non-login | ❌ | 없음 | ❌ | ❌ | ❌ (정상) | 없음 | PASS |
| 16 | script execution | non-login | ❌ | 없음 | ❌ | ❌ | ❌ (정상) | 없음 | PASS |
| 17 | .bashrc 빈 상태 | (위 환경별) | (동일) | bash.bashrc→profile.d | ✅ | ✅ | ✅ | 없음 | PASS |
| 18 | .bashrc 삭제 상태 | (위 환경별) | (동일) | bash.bashrc→profile.d | ✅ | ✅ | ✅ | 없음 | PASS |

---

## 4. 문제점

### 4.1 VS Code Remote — 실증 불가
- 원인: cgjang의 .vscode-server가 staging 상태, server binary 미설치
- 영향: VS Code Remote terminal에서의 동작을 SSM으로 검증할 수 없음
- 해결: 사용자가 VS Code에서 r7에 Remote SSH 접속 후 terminal에서 직접 확인

### 4.2 VS Code Remote — 구조적 예상
VS Code Remote SSH terminal은 기본적으로:
- `bash` (사용자 default shell)을 non-login interactive shell로 실행
- `/etc/bash.bashrc` → source됨
- 따라서 `/etc/bash.bashrc`에 추가한 hook source 라인이 동작할 것으로 예상
- 단, VS Code의 shell integration이 PROMPT_COMMAND를 덮어쓸 가능성 있음

### 4.3 zsh — 미대응
- r7에 zsh 미설치 (`which zsh` → 결과 없음, `dpkg -l zsh` → 결과 없음)
- cgjang default shell: `/bin/bash`
- 현재 zsh 사용자 없음 → zsh 대응 불필요 (향후 필요 시 `/etc/zsh/zshrc`에 동일 패턴 적용)

### 4.4 사용자 PROMPT_COMMAND 덮어쓰기
- 사용자가 .bashrc에서 `PROMPT_COMMAND=my_func`으로 완전 덮어쓰면 hook이 제거됨
- 단, 현재 hook은 `/etc/bash.bashrc`에서 먼저 로드되고, 사용자 .bashrc가 나중에 실행됨
- login shell: profile.d → .bashrc 순서이므로 .bashrc가 덮어쓸 수 있음
- 이건 사용자 재량 영역이므로 정책 위반이 아님 — 사용자가 의도적으로 PROMPT_COMMAND를 덮어쓰면 hook이 비활성화됨
- 이를 방지하려면 PROMPT_COMMAND append 방식이 아닌 다른 메커니즘 필요 (trap DEBUG 등) — 현재는 과도한 복잡성

---

## 5. 최종 권장안

### 통제 지점
1. `/etc/profile.d/bedrock-gw.sh` — hook 본체 (login shell용)
2. `/etc/bash.bashrc` 끝 1줄 — non-login interactive shell용 source

### 이 위치가 맞는 이유
- 둘 다 root 소유 시스템 파일
- 사용자 수정 불가
- 사용자 dotfile 변경/삭제에 영향 없음
- bash의 모든 interactive shell 경로를 커버 (login + non-login)
- non-interactive shell에서는 bash.bashrc의 `[ -z "$PS1" ] && return`에서 중단되어 오염 없음

### 건드리면 안 되는 파일
- `/fsx/home/<user>/.bashrc`
- `/fsx/home/<user>/.bash_profile`
- `/fsx/home/<user>/.profile`
- `/fsx/home/<user>/.zshrc`

---

## 6. 필요한 추가 작업

1. VS Code Remote 실제 검증 — 사용자가 직접 수행
2. zsh — 현재 불필요 (미설치). 향후 zsh 도입 시 `/etc/zsh/zshrc`에 동일 패턴 추가
3. PROMPT_COMMAND 덮어쓰기 방어 — 현재 불필요 (사용자 재량 영역)

---

## 7. 배포 가능 여부

조건부 가능.
- SSH login shell: 배포 완료, 검증 완료
- tmux: 배포 완료, 검증 완료
- screen: 배포 완료, 검증 완료
- VS Code Remote: 배포 완료, 실증 미완료 (사용자 확인 필요)
- zsh: 해당 없음 (미설치)

---

## 8. 남는 리스크

1. VS Code Remote terminal에서 shell integration이 PROMPT_COMMAND를 덮어쓸 가능성 — 실증 필요
2. 사용자가 .bashrc에서 PROMPT_COMMAND를 완전 덮어쓰면 hook 비활성화 — 사용자 재량이므로 수용
3. 동시 다수 terminal에서 /approval/request 중복 호출 가능성 — 서버 측 pending lock으로 방어됨


---

## 방어 검토 체크리스트

- [x] 사용자 /fsx/home/<user>/.bashrc 비의존 구조인지 확인함 — /etc/bash.bashrc + /etc/profile.d/ 사용, 사용자 파일 미접촉
- [x] 사용자 .bashrc 변경/삭제 시에도 유지되는지 확인함 — 빈 .bashrc, 삭제된 .bashrc 모두 함수 로드 확인
- [ ] VS Code Remote / .vscode-server 실제 검증함 — 검증 불가 (server 미설치 상태). 사용자 직접 확인 필요
- [ ] VS Code new terminal / split / reconnect 검증함 — 동일 사유로 미검증
- [x] tmux 검증함 — new-session에서 함수 로드 + 알림 표시 + y/N 프롬프트 확인
- [x] screen 검증함 — bash.bashrc fix 후 함수 로드 + 알림 표시 확인
- [ ] zsh 검증함 — zsh 미설치, 해당 없음
- [x] non-interactive 오염 여부 검증함 — bash non-interactive에서 함수 미로드 확인
- [x] stdout/stderr 오염 여부 검증함 — 모든 출력 >&2, non-interactive에서 무출력
- [x] prompt 중복 여부 검증함 — cooldown 60초 + suppress 60초 + _BEDROCK_GW_LOADED guard
- [x] 운영 통제 지점을 사용자 홈 밖으로 유지함 — /etc/profile.d/ + /etc/bash.bashrc
- [x] "예상"과 "실증 완료"를 구분해서 씀 — VS Code 항목은 모두 "미검증" 또는 "예상"으로 표기
- [x] 최종 권장안을 하나로 수렴해서 제시함

---

## VS Code Remote 검증 방법 (사용자용)

r7에 VS Code Remote SSH로 접속 후 integrated terminal에서:

```bash
# 1. 함수 로드 확인
type _bedrock_gw_check

# 2. PROMPT_COMMAND 확인
echo $PROMPT_COMMAND

# 3. 실제 prompt 발생 확인 (사용량 460K/500K 상태에서)
# Enter를 치면 알림 박스가 떠야 함
```

위 3개가 모두 정상이면 VS Code Remote도 PASS.
