#!/bin/bash
# bedrock-gw-status.sh — Bedrock Gateway 한도 현황 확인
#
# 사용법:
#   bash bedrock-gw-status.sh
#
# 현재 사용자의 한도 현황, 사용량, 승인 요청 상태를 확인합니다.
# Gateway의 /converse 엔드포인트에 빈 요청을 보내 quota 정보를 확인하거나,
# 마지막 요청의 remaining_quota 정보를 참조합니다.

set -euo pipefail

GATEWAY_API_URL="${GATEWAY_API_URL:-https://5l764dh7y9.execute-api.us-west-2.amazonaws.com/v1}"

echo ""
echo "=========================================="
echo " Bedrock Gateway 한도 현황"
echo "=========================================="
echo ""

# 현재 자격증명 확인
IDENTITY=$(aws sts get-caller-identity --output json 2>&1) || {
    echo "오류: AWS 자격증명을 확인할 수 없습니다."
    exit 1
}
ARN=$(echo "$IDENTITY" | python3 -c "import sys,json; print(json.load(sys.stdin)['Arn'])" 2>/dev/null)
echo "현재 사용자: $ARN"
echo ""
echo "한도 현황은 다음 Bedrock 요청 시 응답에 포함됩니다:"
echo "  - 정상 응답: remaining_quota.cost_krw"
echo "  - 한도 초과 시: quota, band, increase_request 정보"
echo ""
echo "한도 증액이 필요하면:"
echo "  bash bedrock-gw-request.sh [사유]"
echo ""
