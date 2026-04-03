#!/bin/bash
# bedrock-gw-quota-check.sh — Shell hook for Bedrock Gateway quota prompt
#
# Deployed to /etc/profile.d/bedrock-gw.sh (root:root 644).
# Also sourced from /etc/bash.bashrc for non-login interactive shells.
#
# Hybrid approach:
#   Primary: PROMPT_COMMAND (standard, low overhead)
#   Fallback: trap DEBUG watchdog (survives user PROMPT_COMMAND override)
#   Cost: one string comparison per command — negligible.
#
# All quota logic is server-side (Lambda /quota/status). Shell is thin client.

# --- PYTHONPATH for bedrock_gw Python client ---
if [[ ":$PYTHONPATH:" != *":/fsx/home/shared/bedrock-gateway:"* ]]; then
  export PYTHONPATH="/fsx/home/shared/bedrock-gateway${PYTHONPATH:+:$PYTHONPATH}"
fi

# --- Guard: re-register hooks if already loaded (survives .bashrc override) ---
if [[ -n "$_BEDROCK_GW_LOADED" ]]; then
  if [[ -n "$BASH_VERSION" ]] && [[ $- == *i* ]] && [[ -t 0 ]]; then
    [[ "$PROMPT_COMMAND" != *"_bedrock_gw_check"* ]] && \
      PROMPT_COMMAND="${PROMPT_COMMAND:+$PROMPT_COMMAND;}_bedrock_gw_check"
    if ! trap -p DEBUG 2>/dev/null | grep -q '_bedrock_gw_debug_trap'; then
      trap '_bedrock_gw_debug_trap' DEBUG 2>/dev/null
    fi
  fi
  return 0 2>/dev/null || true
fi
_BEDROCK_GW_LOADED=1

# --- Skip non-interactive ---
[[ $- == *i* ]] || return 0 2>/dev/null
[[ -t 0 ]] || return 0 2>/dev/null

_BEDROCK_GW_API_URL="https://5l764dh7y9.execute-api.us-west-2.amazonaws.com/v1"
_BEDROCK_GW_CACHE_DIR="${HOME}/.cache/bedrock-gw"
_BEDROCK_GW_COOLDOWN=60
_BEDROCK_GW_SUPPRESS_TTL=60
_BEDROCK_GW_ASK=""
_BEDROCK_GW_STATUS_JSON=""
_BEDROCK_GW_REQUESTED=""

_bedrock_gw_check() {
  [[ -t 0 ]] || return 0
  [[ -t 1 ]] || return 0
  [[ $- == *i* ]] || return 0
  [[ -z "${CI:-}" ]] || return 0
  [[ -z "${NONINTERACTIVE:-}" ]] || return 0

  if [[ "$_BEDROCK_GW_ASK" == "1" ]]; then
    _BEDROCK_GW_ASK=""
    _bedrock_gw_ask_user
    return 0
  fi

  [[ -n "$_BEDROCK_GW_REQUESTED" ]] && return 0
  mkdir -p "$_BEDROCK_GW_CACHE_DIR" 2>/dev/null || return 0

  local cooldown_file="${_BEDROCK_GW_CACHE_DIR}/last-check"
  if [[ -f "$cooldown_file" ]]; then
    local check_age=$(( $(date +%s) - $(stat -c %Y "$cooldown_file" 2>/dev/null || echo 0) ))
    [[ $check_age -lt $_BEDROCK_GW_COOLDOWN ]] && return 0
  fi
  touch "$cooldown_file" 2>/dev/null

  local suppress_file="${_BEDROCK_GW_CACHE_DIR}/suppressed"
  if [[ -f "$suppress_file" ]]; then
    local suppress_age=$(( $(date +%s) - $(stat -c %Y "$suppress_file" 2>/dev/null || echo 0) ))
    [[ $suppress_age -lt $_BEDROCK_GW_SUPPRESS_TTL ]] && return 0
    rm -f "$suppress_file" 2>/dev/null
  fi

  local status_json
  status_json=$(python3 -c "
import sys,json,boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
import urllib.request
try:
    s=boto3.Session()
    c=s.get_credentials()
    if not c: sys.exit(0)
    f=c.get_frozen_credentials()
    u='${_BEDROCK_GW_API_URL}/quota/status'
    r=AWSRequest(method='GET',url=u,headers={'Content-Type':'application/json'})
    SigV4Auth(f,'execute-api','us-west-2').add_auth(r)
    h=urllib.request.Request(u,headers=dict(r.headers),method='GET')
    with urllib.request.urlopen(h,timeout=3) as resp:
        print(resp.read().decode())
except Exception:
    sys.exit(0)
" 2>/dev/null) || return 0

  [[ -z "$status_json" ]] && return 0

  local should_prompt has_pending message effective_limit usage_krw pending_id
  should_prompt=$(echo "$status_json" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('should_prompt_for_increase',''))" 2>/dev/null)
  has_pending=$(echo "$status_json" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('has_pending_approval',''))" 2>/dev/null)
  message=$(echo "$status_json" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('message',''))" 2>/dev/null)
  effective_limit=$(echo "$status_json" | python3 -c "import sys,json;d=json.load(sys.stdin);print(int(d.get('effective_limit_krw',0)))" 2>/dev/null)
  usage_krw=$(echo "$status_json" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('current_usage_krw',0))" 2>/dev/null)

  if [[ "$has_pending" == "True" ]]; then
    pending_id=$(echo "$status_json" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('pending_approval_id','') or '')" 2>/dev/null)
    echo "" >&2
    echo "  [Bedrock Gateway] $message" >&2
    [[ -n "$pending_id" ]] && echo "  승인 요청 ID: $pending_id" >&2
    echo "" >&2
    _BEDROCK_GW_REQUESTED=1
    return 0
  fi

  [[ "$should_prompt" != "True" ]] && return 0

  echo "" >&2
  echo "  ┌──────────────────────────────────────────────────┐" >&2
  echo "  │  Bedrock Gateway 한도 알림                        │" >&2
  printf "  │  현재 유효 한도: KRW %'d%*s│\n" "$effective_limit" $((24 - ${#effective_limit})) "" >&2
  printf "  │  현재 사용량:   KRW %s%*s│\n" "$usage_krw" $((25 - ${#usage_krw})) "" >&2
  echo "  └──────────────────────────────────────────────────┘" >&2
  echo "" >&2
  echo "  다음 Enter를 누르면 증액 요청 여부를 물어봅니다." >&2
  echo "" >&2

  _BEDROCK_GW_STATUS_JSON="$status_json"
  _BEDROCK_GW_ASK=1
  return 0
}

_bedrock_gw_ask_user() {
  local answer=""
  read -t 15 -p "  KRW 500,000 증액 요청을 관리자에게 보낼까요? [y/N] " answer
  echo "" >&2

  if [[ "$answer" != "y" && "$answer" != "Y" ]]; then
    echo "  증액 요청을 건너뛰었습니다. (60초 후 재질문)" >&2
    touch "${_BEDROCK_GW_CACHE_DIR}/suppressed" 2>/dev/null
    echo "" >&2
    _BEDROCK_GW_STATUS_JSON=""
    return 0
  fi

  echo "  한도 증액 요청을 전송합니다..." >&2
  local result
  result=$(python3 -c "
import sys,json,boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
import urllib.request
try:
    s=boto3.Session()
    f=s.get_credentials().get_frozen_credentials()
    u='${_BEDROCK_GW_API_URL}/approval/request'
    b=json.dumps({'reason':'한도 소진 임박으로 증액 요청','requested_increment_krw':500000})
    r=AWSRequest(method='POST',url=u,data=b,headers={'Content-Type':'application/json'})
    SigV4Auth(f,'execute-api','us-west-2').add_auth(r)
    h=urllib.request.Request(u,data=b.encode(),headers=dict(r.headers),method='POST')
    with urllib.request.urlopen(h,timeout=5) as resp:
        d=json.loads(resp.read().decode())
        if d.get('decision')=='ACCEPTED': print('OK:'+d.get('approval_id',''))
        else: print('DENY:'+d.get('denial_reason',''))
except urllib.error.HTTPError as e:
    body=e.read().decode()
    try:
        d=json.loads(body);print('ERR:'+d.get('denial_reason',d.get('error',str(e.code))))
    except: print('ERR:'+str(e.code))
except Exception as e:
    print('ERR:'+str(e))
" 2>/dev/null)

  if [[ "$result" == OK:* ]]; then
    local aid="${result#OK:}"
    echo "  한도 증액 요청이 접수되었습니다." >&2
    echo "  승인 요청 ID: $aid" >&2
    echo "  관리자 승인 후 자동으로 한도가 적용됩니다." >&2
    _BEDROCK_GW_REQUESTED=1
  elif [[ "$result" == DENY:*pending* ]]; then
    echo "  이미 증액 요청이 대기 중입니다." >&2
    _BEDROCK_GW_REQUESTED=1
  elif [[ "$result" == ERR:* ]]; then
    echo "  요청 전송 실패: ${result#ERR:}" >&2
  fi

  echo "" >&2
  _BEDROCK_GW_STATUS_JSON=""
  return 0
}

# --- trap DEBUG watchdog: fires when PROMPT_COMMAND no longer has our hook ---
_bedrock_gw_debug_trap() {
  [[ "$PROMPT_COMMAND" == *"_bedrock_gw_check"* ]] && return 0
  _bedrock_gw_check
}

# --- Hook registration ---
if [[ -n "$BASH_VERSION" ]]; then
  PROMPT_COMMAND="${PROMPT_COMMAND:+$PROMPT_COMMAND;}_bedrock_gw_check"
  trap '_bedrock_gw_debug_trap' DEBUG 2>/dev/null
elif [[ -n "$ZSH_VERSION" ]]; then
  autoload -Uz add-zsh-hook 2>/dev/null
  add-zsh-hook precmd _bedrock_gw_check 2>/dev/null
fi
