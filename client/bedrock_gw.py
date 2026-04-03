"""
bedrock_gw — Bedrock Gateway Python 클라이언트 (v2: short + long path)

사용법:
    from bedrock_gw import converse, get_client
    response = converse("us.anthropic.claude-haiku-4-5-20251001-v1:0", "안녕하세요")

    # boto3 호환:
    client = get_client()
    resp = client.converse(modelId='us.anthropic.claude-sonnet-4-6',
                           messages=[{'role':'user','content':[{'text':'hello'}]}])

경로 자동 선택:
  - Short path (Tier 1): API Gateway → Lambda → Bedrock Converse
    Haiku, Nova, Sonnet, 일반 호출 (< 15분)
  - Long path (Tier 3): 내부적으로 async job submit → poll → result fetch
    Opus 대형 컨텍스트, 장시간 호출. 사용자는 동기 호출처럼 사용.

한도 초과 시 자동으로 증액 요청 여부를 묻습니다.
"""
import json, sys, os, time, boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
import urllib.request

API = os.environ.get(
    "BEDROCK_GW_API",
    "https://5l764dh7y9.execute-api.us-west-2.amazonaws.com/v1",
)
_REGION = "us-west-2"
_SERVICE = "execute-api"

# ---------------------------------------------------------------------------
# Tier routing configuration
# ---------------------------------------------------------------------------
# Models that always use long path (Tier 3)
_LONGRUN_MODELS = {
    "us.anthropic.claude-opus-4-6-v1",
    "global.anthropic.claude-opus-4-6-v1",
    "us.anthropic.claude-opus-4-5-20251101-v1:0",
    "us.anthropic.claude-opus-4-20250514-v1:0",
    "us.anthropic.claude-opus-4-1-20250805-v1:0",
    "anthropic.claude-opus-4-6-v1",
}
# Input token threshold for auto-upgrade to long path
_LONGRUN_TOKEN_THRESHOLD = 100000
# Override: BEDROCK_GW_TIER=1 forces short, =3 forces long
_TIER_OVERRIDE = os.environ.get("BEDROCK_GW_TIER", "")


def _estimate_input_tokens(messages, system=None):
    """Rough estimate of input tokens from message content length."""
    total_chars = 0
    if system:
        for s in (system if isinstance(system, list) else [system]):
            if isinstance(s, dict):
                total_chars += len(s.get("text", ""))
            elif isinstance(s, str):
                total_chars += len(s)
    for msg in (messages or []):
        for c in (msg.get("content") or []):
            if isinstance(c, dict):
                total_chars += len(c.get("text", ""))
    # Rough: 1 token ≈ 4 chars for English, ~2 chars for Korean
    return max(total_chars // 3, 1)


def _select_tier(model_id, messages=None, system=None):
    """Determine which tier to use for this call."""
    if _TIER_OVERRIDE == "1":
        return 1
    if _TIER_OVERRIDE == "3":
        return 3
    if model_id in _LONGRUN_MODELS:
        return 3
    if messages:
        est = _estimate_input_tokens(messages, system)
        if est > _LONGRUN_TOKEN_THRESHOLD:
            return 3
    return 1


def _sigv4_request(method, path, body_dict=None, timeout=30):
    """Send a SigV4-signed request to the gateway API."""
    url = API + path
    body = json.dumps(body_dict) if body_dict else None
    session = boto3.Session()
    creds = session.get_credentials().get_frozen_credentials()
    headers = {"Content-Type": "application/json"}
    req = AWSRequest(method=method, url=url, data=body, headers=headers)
    SigV4Auth(creds, _SERVICE, _REGION).add_auth(req)
    http_req = urllib.request.Request(
        url, data=body.encode() if body else None,
        headers=dict(req.headers), method=method,
    )
    try:
        with urllib.request.urlopen(http_req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body_bytes = e.read()
        try:
            return e.code, json.loads(body_bytes.decode())
        except Exception:
            return e.code, {"error": body_bytes.decode()}


def _sigv4_post(path, body_dict, timeout=30):
    return _sigv4_request("POST", path, body_dict, timeout=timeout)


def _is_interactive():
    return hasattr(sys.stdin, "isatty") and sys.stdin.isatty()


def _handle_quota_exceeded(data):
    inc = data.get("increase_request", {})
    msg = data.get("message", "")
    print("\n[Bedrock Gateway] " + msg)

    if not inc.get("can_request"):
        if inc.get("has_pending"):
            print("  -> 증액 요청이 이미 접수되어 관리자 승인 대기 중입니다.")
        else:
            print("  -> 월간 최대 한도에 도달하여 추가 증액이 불가합니다.")
        return None

    if not _is_interactive():
        print("  -> 비대화형 환경입니다. 증액 요청을 하려면:")
        print("     from bedrock_gw import request_increase")
        print("     request_increase('사유')")
        return None

    print("  현재 한도: KRW %s" % "{:,}".format(inc.get("new_limit_if_approved_krw", 0) - 500000))
    print("  증액분: KRW 500,000")
    print("  승인 시 새 한도: KRW %s" % "{:,}".format(inc.get("new_limit_if_approved_krw", 0)))
    try:
        answer = input("  한도 증액을 요청하시겠습니까? (y/n): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n  요청이 취소되었습니다.")
        return None

    if answer != "y":
        print("  요청이 취소되었습니다.")
        return None

    return request_increase("한도 소진으로 증액 요청")


def request_increase(reason="한도 소진으로 증액 요청"):
    """명시적으로 한도 증액을 요청합니다."""
    code, data = _sigv4_post("/approval/request", {
        "reason": reason,
        "requested_increment_krw": 500000,
    })
    if code == 201 and data.get("decision") == "ACCEPTED":
        aid = data.get("approval_id", "")
        print("\n  [OK] 한도 증액 요청이 접수되었습니다.")
        print("  승인 요청 ID: %s" % aid)
        print("  관리자 승인 후 자동으로 한도가 적용됩니다.")
        return data
    else:
        reason_msg = data.get("denial_reason", str(data))
        print("\n  [FAIL] 요청 실패: %s" % reason_msg)
        return data


# ---------------------------------------------------------------------------
# Short path (Tier 1): existing gateway inline converse
# ---------------------------------------------------------------------------

def _short_path_converse(body):
    """Tier 1: API Gateway → Lambda → Bedrock Converse → DynamoDB."""
    code, data = _sigv4_post("/converse", body, timeout=960)

    if code == 200:
        remaining = data.get("remaining_quota", {}).get("cost_krw", float("inf"))
        if _is_interactive():
            effective_limit = remaining + data.get("estimated_cost_krw", 0)
            if effective_limit > 0:
                remaining_pct = remaining / effective_limit
                if remaining_pct <= 0.10:
                    print("\n  [Bedrock Gateway] 잔여 한도 10% 이하 — KRW {:,.0f}".format(remaining),
                          file=sys.stderr)
                elif remaining_pct <= 0.30:
                    print("\n  [Bedrock Gateway] 잔여 한도 30% 이하 — KRW {:,.0f}".format(remaining),
                          file=sys.stderr)
        return data
    elif code == 429:
        result = _handle_quota_exceeded(data)
        if result and result.get("decision") == "ACCEPTED" and _is_interactive():
            print("  승인 요청이 접수되었습니다. 관리자 승인 후 재시도하세요.")
        return data
    else:
        print("[Bedrock Gateway] HTTP %d: %s" % (code, data.get("denial_reason", "")))
        return data


# ---------------------------------------------------------------------------
# Long path (Tier 3): authorize → direct ConverseStream → settle
# ---------------------------------------------------------------------------

def _long_path_converse(model_id, body):
    """Hidden async path: submit to /converse-jobs, poll until complete, return result.

    사용자는 이 함수가 async인지 모른다. 동기 호출처럼 block하고 결과를 반환한다.
    내부적으로: POST /converse-jobs → poll GET /converse-jobs/{jobId} → fetch result from S3.
    """
    import uuid as _uuid

    request_id = f"gw-auto-{_uuid.uuid4().hex[:12]}"

    # Step 1: Submit job
    submit_body = dict(body)
    code, submit_data = _sigv4_post("/converse-jobs", submit_body, timeout=30)

    if code == 429:
        result = _handle_quota_exceeded(submit_data)
        if result and result.get("decision") == "ACCEPTED" and _is_interactive():
            print("  승인 요청이 접수되었습니다. 관리자 승인 후 재시도하세요.")
        return submit_data
    if code not in (200, 201, 202) or submit_data.get("decision") not in ("ACCEPTED",):
        reason = submit_data.get("denial_reason", submit_data.get("error", f"HTTP {code}"))
        print(f"[Bedrock Gateway] Job submission failed: {reason}")
        return submit_data

    job_id = submit_data.get("job_id", "")
    if not job_id:
        return {"decision": "DENY", "denial_reason": "no job_id returned from submission"}

    if _is_interactive():
        print(f"  [Bedrock Gateway] 장시간 모델 호출 중... (job: {job_id[:16]})", file=sys.stderr)

    # Step 2: Poll until complete (max 1 hour)
    poll_interval = 5
    max_wait = 3600
    elapsed = 0
    final_status = None
    job_data = {}

    while elapsed < max_wait:
        time.sleep(poll_interval)
        elapsed += poll_interval

        poll_code, job_data = _sigv4_request("GET", f"/converse-jobs/{job_id}", timeout=10)
        if poll_code != 200:
            continue

        status = job_data.get("status", "")
        if status in ("SUCCEEDED", "FAILED", "TIMED_OUT", "CANCELED"):
            final_status = status
            break

        # Progressive polling: increase interval after 60s
        if elapsed > 60 and poll_interval < 15:
            poll_interval = 15
        if elapsed > 300 and poll_interval < 30:
            poll_interval = 30

        if _is_interactive() and elapsed % 30 == 0:
            print(f"  [Bedrock Gateway] 처리 중... ({elapsed}초 경과, 상태: {status})", file=sys.stderr)

    if final_status != "SUCCEEDED":
        error_msg = job_data.get("error_message", f"Job ended with status: {final_status or 'TIMEOUT'}")
        return {
            "decision": "DENY",
            "denial_reason": error_msg,
            "job_id": job_id,
            "status": final_status or "POLL_TIMEOUT",
        }

    # Step 3: Fetch result from S3
    result_ref = job_data.get("result_ref", "")
    settled_cost = job_data.get("settled_cost_krw", 0)
    input_tokens = job_data.get("input_tokens", 0)
    output_tokens = job_data.get("output_tokens", 0)

    output_data = {}
    if result_ref.startswith("s3://"):
        try:
            parts = result_ref.replace("s3://", "").split("/", 1)
            bucket = parts[0]
            key = parts[1]
            s3 = boto3.client("s3", region_name=_REGION)
            s3_resp = s3.get_object(Bucket=bucket, Key=key)
            output_data = json.loads(s3_resp["Body"].read().decode())
        except Exception as e:
            print(f"  [Bedrock Gateway] WARNING: Result fetch failed: {e}", file=sys.stderr)

    if _is_interactive():
        print(f"  [Bedrock Gateway] 완료 — 비용: KRW {settled_cost:,.1f}, "
              f"토큰: {input_tokens}/{output_tokens}, 소요: {elapsed}초", file=sys.stderr)

    # Return in same format as short path
    return {
        "decision": "ALLOW",
        "output": output_data.get("output", {}),
        "usage": output_data.get("usage", {"inputTokens": input_tokens, "outputTokens": output_tokens}),
        "stopReason": output_data.get("stopReason", "end_turn"),
        "estimated_cost_krw": settled_cost,
        "remaining_quota": {"cost_krw": 0},
        "request_id": job_id,
        "source_path": "gateway-async-hidden",
    }


# ---------------------------------------------------------------------------
# Public API: converse()
# ---------------------------------------------------------------------------

def converse(model_id, text, **kwargs):
    """Gateway를 통해 Bedrock Converse API를 호출합니다.

    자동으로 short path (Tier 1) 또는 long path (Tier 3)를 선택합니다.
    - Tier 1: Haiku, Nova, Sonnet 등 일반 호출
    - Tier 3: Opus, 대형 컨텍스트 등 장시간 호출

    Args:
        model_id: 모델 ID
        text: 사용자 메시지 텍스트
        **kwargs: messages, system, inferenceConfig 등

    Returns:
        Gateway 응답 dict
    """
    body = {"modelId": model_id}
    if "messages" in kwargs:
        body["messages"] = kwargs["messages"]
    else:
        body["messages"] = [{"role": "user", "content": [{"text": text}]}]
    if "system" in kwargs:
        body["system"] = kwargs["system"]
    if "inferenceConfig" in kwargs:
        body["inferenceConfig"] = kwargs["inferenceConfig"]
    if "toolConfig" in kwargs:
        body["toolConfig"] = kwargs["toolConfig"]

    tier = _select_tier(model_id, body.get("messages"), body.get("system"))

    if tier == 3:
        return _long_path_converse(model_id, body)
    else:
        return _short_path_converse(body)


# ---------------------------------------------------------------------------
# boto3-compatible wrapper
# ---------------------------------------------------------------------------

class _GatewayClient:
    """boto3 bedrock-runtime client 호환 wrapper.

    client.converse() 호출을 게이트웨이로 라우팅합니다.
    Tier 자동 선택: Opus → long path, 나머지 → short path.
    """

    def converse(self, **kwargs):
        model_id = kwargs.get("modelId", "")
        messages = kwargs.get("messages", [])

        body = {"modelId": model_id, "messages": messages}
        if "system" in kwargs:
            body["system"] = kwargs["system"]
        if "inferenceConfig" in kwargs:
            body["inferenceConfig"] = kwargs["inferenceConfig"]
        if "toolConfig" in kwargs:
            body["toolConfig"] = kwargs["toolConfig"]

        tier = _select_tier(model_id, messages, kwargs.get("system"))

        if tier == 3:
            data = _long_path_converse(model_id, body)
        else:
            code, data = _sigv4_post("/converse", body)
            if code != 200 or data.get("decision") != "ALLOW":
                if code == 429:
                    if _is_interactive():
                        _handle_quota_exceeded(data)
                    raise Exception("QuotaExceeded: %s" % data.get("message", "quota exceeded"))
                reason = data.get("denial_reason", data.get("error", "HTTP %d" % code))
                raise Exception("BedrockGatewayError: %s" % reason)

        if data.get("decision") == "ALLOW":
            return {
                "output": data.get("output", {}),
                "usage": data.get("usage", {}),
                "stopReason": data.get("stopReason", "end_turn"),
                "ResponseMetadata": {"HTTPStatusCode": 200},
                "estimated_cost_krw": data.get("estimated_cost_krw"),
                "remaining_quota": data.get("remaining_quota"),
                "source_path": data.get("source_path", "gateway-inline"),
            }
        elif data.get("decision") == "DENY" or "denial_reason" in data:
            reason = data.get("denial_reason", data.get("message", "denied"))
            raise Exception("BedrockGatewayError: %s" % reason)
        else:
            return data


def get_client():
    """boto3.client('bedrock-runtime') 대체 클라이언트를 반환합니다."""
    return _GatewayClient()
