#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

if [[ $# -ne 4 ]]; then
    echo "Usage: $0 SUBSCRIPTION_ID REPORT_KEY YEAR MONTH"
    echo
    echo "Example:"
    echo "  $0 <subscription-id> subscription-001 2024 01"
    exit 1
fi

SUBSCRIPTION_ID="$1"
REPORT_KEY="$2"
YEAR="$3"
MONTH="$(normalize_month "$4")"

validate_subscription_id "$SUBSCRIPTION_ID"
validate_report_key "$REPORT_KEY"
validate_year "$YEAR"

SCOPE="$(subscription_scope "$SUBSCRIPTION_ID")"
EXPORT_NAME="$(build_export_name "$YEAR" "$MONTH")"

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

ROOT_PATH="${EXPORT_ROOT_PATH}/${REPORT_KEY}/${YEAR}/${MONTH}"

EXPORT_URL="https://management.azure.com${SCOPE}/providers/Microsoft.CostManagement/exports/${EXPORT_NAME}?api-version=${AZURE_COST_API_VERSION}"

echo "Creating monthly Azure Cost Management export"
echo "Export name : ${EXPORT_NAME}"
echo "Report key  : ${REPORT_KEY}"
echo "Period      : ${YEAR}-${MONTH}"
echo "Data type   : Usage"

# If the export already exists, Azure requires its current eTag when
# updating it. This allows the script to be rerun safely.
ETAG=""

if EXISTING_EXPORT="$(az rest \
    --method get \
    --url "$EXPORT_URL" \
    --output json 2>/dev/null)"; then

    ETAG="$(jq -r '.eTag // empty' <<<"$EXISTING_EXPORT")"

    if [[ -n "$ETAG" ]]; then
        echo "Existing export found; updating definition."
    fi
fi

BODY="$(
    jq -n \
        --arg storageId "$STORAGE_RESOURCE_ID" \
        --arg container "$STORAGE_CONTAINER" \
        --arg rootPath "$ROOT_PATH" \
        --arg startDate "$START_DATE" \
        --arg endDate "$END_DATE" \
        --arg etag "$ETAG" \
        '
        {
          properties: {
            format: "Csv",
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
                from: $startDate,
                to: $endDate
              },
              dataSet: {
                granularity: "Daily"
              }
            },
            schedule: {
              status: "Inactive"
            }
          }
        }
        | if $etag != "" then . + {eTag: $etag} else . end
        '
)"

az rest \
    --method put \
    --url "$EXPORT_URL" \
    --body "$BODY" \
    --output none

echo "Export definition ready."
