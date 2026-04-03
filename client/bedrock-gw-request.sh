#!/bin/bash
# bedrock-gw-request.sh — Bedrock Gateway 한도 증액 요청
#
# 사용법:
#   bash /fsx/shared/bedrock-gateway/bedrock-gw-request.sh [사유]
#
# BedrockUser-* 역할의 AWS 자격증명을 사용하여 Gateway API에
# SigV4 서명된 한도 증액 요청을 전송합니다.

set -euo pipefail

REASON="${1:-한도 소진으로 증액 요청}"

echo ""
echo "=========================================="
echo " Bedrock Gateway 한도 증액 요청"
echo "=========================================="
echo ""

# 자격증명 확인
IDENTITY=$(aws sts get-caller-identity --output json 2>&1) || {
    echo "오류: AWS 자격증명을 확인할 수 없습니다."
    exit 1
}
ARN=$(echo "$IDENTITY" | python3 -c "import sys,json; print(json.load(sys.stdin)['Arn'])" 2>/dev/null)
echo "현재 사용자: $ARN"
echo ""
echo "증액분: KRW 500,000"
echo "사유: $REASON"
echo ""
read -p "한도 증액을 요청하시겠습니까? (y/n): " CONFIRM

if [[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]]; then
    echo "요청이 취소되었습니다."
    exit 0
fi

echo ""
echo "요청 전송 중..."

python3 - "$REASON" << 'PYEOF'
import sys, json, boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
import requests as req

reason = sys.argv[1] if len(sys.argv) > 1 else "한도 소진으로 증액 요청"
url = "https://5l764dh7y9.execute-api.us-west-2.amazonaws.com/v1/approval/request"
body = json.dumps({"reason": reason, "requested_increment_krw": 500000})

session = boto3.Session()
creds = session.get_credentials().get_frozen_credentials()
request = AWSRequest(method="POST", url=url, data=body,
                     headers={"Content-Type": "application/json"})
SigV4Auth(creds, "execute-api", "us-west-2").add_auth(request)

resp = req.post(url, data=body, headers=dict(request.headers))
print()
try:
    data = resp.json()
    print(json.dumps(data, indent=2, ensure_ascii=False))
    decision = data.get("decision", "")
    if decision == "ACCEPTED":
        aid = data.get("approval_id", "")
        print(f"\n✓ 한도 증액 요청이 접수되었습니다.")
        print(f"  승인 요청 ID: {aid}")
        print(f"  관리자 승인 후 자동으로 한도가 적용됩니다.")
    elif decision == "DENY":
        print(f"\n✗ 요청 거부: {data.get('denial_reason', '')}")
    else:
        print(f"\nHTTP {resp.status_code}")
except Exception:
    print(resp.text)
PYEOF
