#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=common.sh
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

SCOPE="$(subscription_scope "$SUBSCRIPTION_ID")"
EXPORT_NAME="$(build_export_name "$YEAR" "$MONTH")"

az rest \
    --method get \
    --url "https://management.azure.com${SCOPE}/providers/Microsoft.CostManagement/exports/${EXPORT_NAME}/runHistory?api-version=${AZURE_COST_API_VERSION}" \
    --query "value[].{
        Status:properties.status,
        StartTime:properties.processingStartTime,
        EndTime:properties.processingEndTime,
        FileName:properties.fileName
    }" \
    --output table
