#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 SUBSCRIPTION_ID REPORT_KEY"
    exit 1
fi

SUBSCRIPTION_ID="$1"
REPORT_KEY="$2"

validate_subscription_id "$SUBSCRIPTION_ID"
validate_report_key "$REPORT_KEY"

EXPORT_NAME="${AZURE_COST_REUSABLE_EXPORT_NAME:-cost-usage-history}"
SCOPE="$(subscription_scope "$SUBSCRIPTION_ID")"

EXPORT_URL="https://management.azure.com${SCOPE}/providers/Microsoft.CostManagement/exports/${EXPORT_NAME}?api-version=${AZURE_COST_API_VERSION}"

# Do not recreate a definition that already exists.
if az rest \
    --method get \
    --url "$EXPORT_URL" \
    --output none \
    2>/dev/null; then

    echo "Reusable export already exists."
    exit 0
fi

# A Custom definition requires a valid time period.
# Execute requests override this period at runtime.
BASE_MONTH="$(date -u -d "$(date -u +%Y-%m-01) -1 month" +%Y-%m)"
BASE_START="${BASE_MONTH}-01T00:00:00Z"
BASE_LAST_DAY="$(date -u -d "${BASE_MONTH}-01 +1 month -1 day" +%Y-%m-%d)"
BASE_END="${BASE_LAST_DAY}T23:59:59Z"

ROOT_PATH="${EXPORT_ROOT_PATH}/${REPORT_KEY}"

BODY="$(
    jq -n \
        --arg storageId "$STORAGE_RESOURCE_ID" \
        --arg container "$STORAGE_CONTAINER" \
        --arg rootPath "$ROOT_PATH" \
        --arg from "$BASE_START" \
        --arg to "$BASE_END" \
        '{
          properties: {
            format: "Csv",
            partitionData: true,
            dataOverwriteBehavior: "OverwritePreviousReport",
            deliveryInfo: {
              destination: {
                type: "AzureBlob",
                resourceId: $storageId,
                container: $container,
                rootFolderPath: $rootPath
              }
            },
            definition: {
              type: "Usage",
              timeframe: "Custom",
              timePeriod: {
                from: $from,
                to: $to
              },
              dataSet: {
                granularity: "Daily"
              }
            },
            schedule: {
              status: "Inactive"
            }
          }
        }'
)"

az rest \
    --method put \
    --url "$EXPORT_URL" \
    --body "$BODY" \
    --output none

echo "Reusable export definition created."
