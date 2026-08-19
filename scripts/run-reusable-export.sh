#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

if [[ $# -ne 3 ]]; then
    echo "Usage: $0 SUBSCRIPTION_ID YEAR MONTH"
    exit 1
fi

SUBSCRIPTION_ID="$1"
YEAR="$2"
MONTH="$(normalize_month "$3")"

validate_subscription_id "$SUBSCRIPTION_ID"
validate_year "$YEAR"

TARGET_MONTH="${YEAR}-${MONTH}"
CURRENT_MONTH="$(date -u +%Y-%m)"

if [[ "$TARGET_MONTH" > "$CURRENT_MONTH" ]]; then
    die "Cannot export a future month: ${TARGET_MONTH}"
fi

START_DATE="${YEAR}-${MONTH}-01T00:00:00Z"

if [[ "$TARGET_MONTH" == "$CURRENT_MONTH" ]]; then
    END_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
else
    LAST_DAY="$(date -u -d "${YEAR}-${MONTH}-01 +1 month -1 day" +%Y-%m-%d)"
    END_DATE="${LAST_DAY}T23:59:59Z"
fi

EXPORT_NAME="${AZURE_COST_REUSABLE_EXPORT_NAME:-cost-usage-history}"
SCOPE="$(subscription_scope "$SUBSCRIPTION_ID")"

BODY="$(
    jq -n \
        --arg from "$START_DATE" \
        --arg to "$END_DATE" \
        '{
          timePeriod: {
            from: $from,
            to: $to
          }
        }'
)"

az rest \
    --method post \
    --url "https://management.azure.com${SCOPE}/providers/Microsoft.CostManagement/exports/${EXPORT_NAME}/run?api-version=${AZURE_COST_API_VERSION}" \
    --body "$BODY" \
    --output none
