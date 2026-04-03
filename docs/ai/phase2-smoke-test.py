#!/usr/bin/env python3
"""
Phase 2 Smoke Test — Bedrock Access Control Gateway (dev)

Purpose: SigV4-signed POST to dev API Gateway as BedrockUser-cgjang.
         Verifies C5 (ALLOW + estimated_cost_krw in response).
         No awscurl dependency — uses botocore SigV4Auth directly.

Prerequisites:
  - Running as BedrockUser-cgjang (via assume-role or [default] profile on FSx)
  - Python 3.8+ with boto3/botocore installed
  - Network access to API Gateway endpoint

Usage (FSx, default profile):
    python3 phase2-smoke-test.py

Usage (explicit profile):
    AWS_PROFILE=bedrock-user-cgjang python3 phase2-smoke-test.py

Output:
  - Prints caller identity, HTTP status, response body
  - Saves response JSON to ./phase2-smoke-response.json
  - Exit 0 on ALLOW, exit 1 on any failure
"""

import json
import sys
import os
from datetime import datetime

# --- Configuration ---
API_GATEWAY_INVOKE_URL = "https://5l764dh7y9.execute-api.us-west-2.amazonaws.com/v1"
ENDPOINT = f"{API_GATEWAY_INVOKE_URL}/converse"
REGION = "us-west-2"
SERVICE = "execute-api"

REQUEST_BODY = {
    "modelId": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "messages": [
        {"role": "user", "content": [{"text": "Say hello in one word."}]}
    ],
}

OUTPUT_FILE = os.environ.get(
    "SMOKE_TEST_OUTPUT", "./phase2-smoke-response.json"
)

# --- Step 0: Verify caller identity ---
print("=" * 60)
print("Phase 2 Smoke Test — Bedrock Access Control Gateway (dev)")
print("=" * 60)
print()

import boto3

session = boto3.Session()
sts = session.client("sts", region_name=REGION)

print("[Step 0] Verifying caller identity...")
try:
    identity = sts.get_caller_identity()
    arn = identity["Arn"]
    account = identity["Account"]
    print(f"  Account: {account}")
    print(f"  Arn:     {arn}")
    print(f"  UserId:  {identity['UserId']}")
except Exception as e:
    print(f"  FATAL: Cannot determine caller identity: {e}")
    print("  Ensure you are running as BedrockUser-cgjang.")
    sys.exit(1)

if "BedrockUser-cgjang" not in arn:
    print(f"  WARNING: Caller is NOT BedrockUser-cgjang.")
    print(f"  API Gateway AWS_IAM auth requires BedrockUser-cgjang credentials.")
    print(f"  Proceeding anyway — expect 403 if wrong identity.")
print()

# --- Step 1: SigV4-signed POST ---
print("[Step 1] Sending SigV4-signed POST to gateway...")
print(f"  Endpoint: {ENDPOINT}")
print(f"  Model:    {REQUEST_BODY['modelId']}")
print()

from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
import urllib.request
import urllib.error

credentials = session.get_credentials().get_frozen_credentials()

body_bytes = json.dumps(REQUEST_BODY).encode("utf-8")

aws_request = AWSRequest(
    method="POST",
    url=ENDPOINT,
    data=body_bytes,
    headers={
        "Content-Type": "application/json",
        "Host": "5l764dh7y9.execute-api.us-west-2.amazonaws.com",
    },
)
SigV4Auth(credentials, SERVICE, REGION).add_auth(aws_request)

# Build urllib request with signed headers
req = urllib.request.Request(
    ENDPOINT,
    data=body_bytes,
    method="POST",
)
for key, value in aws_request.headers.items():
    req.add_header(key, value)

try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        status_code = resp.status
        response_body = resp.read().decode("utf-8")
except urllib.error.HTTPError as e:
    status_code = e.code
    response_body = e.read().decode("utf-8")
except Exception as e:
    print(f"  FATAL: Request failed: {e}")
    sys.exit(1)

print(f"  HTTP Status: {status_code}")
print()

# --- Step 2: Parse and validate response ---
print("[Step 2] Response body:")
try:
    response_json = json.loads(response_body)
    print(json.dumps(response_json, indent=2, ensure_ascii=False))
except json.JSONDecodeError:
    print(f"  (raw, not JSON): {response_body[:500]}")
    response_json = None
print()

# --- Step 3: Save evidence ---
evidence = {
    "timestamp": datetime.utcnow().isoformat() + "Z",
    "caller_identity": {
        "Account": account,
        "Arn": arn,
        "UserId": identity["UserId"],
    },
    "request": {
        "endpoint": ENDPOINT,
        "body": REQUEST_BODY,
    },
    "response": {
        "http_status": status_code,
        "body": response_json if response_json else response_body,
    },
}

with open(OUTPUT_FILE, "w") as f:
    json.dump(evidence, f, indent=2, ensure_ascii=False, default=str)
print(f"[Step 3] Evidence saved to: {OUTPUT_FILE}")
print()

# --- Step 4: Verdict ---
print("[Step 4] Verdict:")
if status_code == 200 and response_json:
    decision = response_json.get("decision", "")
    cost_krw = response_json.get("estimated_cost_krw")
    remaining = response_json.get("remaining_quota", {}).get("cost_krw")
    usage = response_json.get("usage", {})

    checks = {
        "decision == ALLOW": decision == "ALLOW",
        "estimated_cost_krw present and > 0": cost_krw is not None and cost_krw > 0,
        "remaining_quota.cost_krw present": remaining is not None,
        "usage.inputTokens > 0": usage.get("inputTokens", 0) > 0,
        "usage.outputTokens > 0": usage.get("outputTokens", 0) > 0,
    }

    all_pass = True
    for check_name, passed in checks.items():
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        print(f"  [{status}] {check_name}")

    print()
    if all_pass:
        print("  >>> C5 PASSED: Smoke test successful.")
        print("  >>> Proceed to C6-C9 admin-side verification.")
        sys.exit(0)
    else:
        print("  >>> C5 FAILED: One or more checks did not pass.")
        print("  >>> Review response body and Lambda logs.")
        sys.exit(1)

elif status_code == 429 and response_json:
    print(f"  QUOTA EXCEEDED: {response_json.get('denial_reason', 'unknown')}")
    print(f"  Quota info: {json.dumps(response_json.get('quota', {}), indent=2)}")
    print("  >>> C5 FAILED: Quota exceeded. Check principal_policy seed data.")
    sys.exit(1)

elif status_code == 403:
    print("  HTTP 403 Forbidden — SigV4 auth failure.")
    print("  Check: caller identity is BedrockUser-cgjang with execute-api:Invoke permission.")
    sys.exit(1)

else:
    print(f"  Unexpected HTTP {status_code}.")
    if response_json:
        denial = response_json.get("denial_reason", "")
        if denial:
            print(f"  Denial reason: {denial}")
    print("  >>> C5 FAILED: Unexpected response. Check Lambda logs.")
    sys.exit(1)
