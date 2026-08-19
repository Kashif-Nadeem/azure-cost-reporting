#!/usr/bin/env bash
set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${TEST_DIR}/.." && pwd)"

# shellcheck source=../scripts/common.sh
source "${REPO_ROOT}/scripts/common.sh"

require_variable TEST_SUBSCRIPTION_ID

EXPORT_NAME="cost-usage-reusable-validation"
REPORT_KEY="reusable-validation"

SCOPE="/subscriptions/${TEST_SUBSCRIPTION_ID}"
EXPORT_URL="https://management.azure.com${SCOPE}/providers/Microsoft.CostManagement/exports/${EXPORT_NAME}?api-version=${AZURE_COST_API_VERSION}"
RUN_URL="https://management.azure.com${SCOPE}/providers/Microsoft.CostManagement/exports/${EXPORT_NAME}/run?api-version=${AZURE_COST_API_VERSION}"
HISTORY_URL="https://management.azure.com${SCOPE}/providers/Microsoft.CostManagement/exports/${EXPORT_NAME}/runHistory?api-version=${AZURE_COST_API_VERSION}"

# ------------------------------------------------------------
# Important test:
#
# The export definition itself is configured for February 2024,
# while the Execute request below explicitly requests January
# 2024.
#
# If Azure produces a January run, we have proven that one
# reusable definition can execute different monthly periods.
# ------------------------------------------------------------

DEFINITION_FROM="2024-02-01T00:00:00Z"
DEFINITION_TO="2024-02-29T23:59:59Z"

RUN_FROM="2024-01-01T00:00:00Z"
RUN_TO="2024-01-31T23:59:59Z"

ROOT_PATH="${EXPORT_ROOT_PATH}/${REPORT_KEY}"

echo "Creating reusable subscription export definition..."

ETAG=""

if EXISTING="$(
    az rest \
        --method get \
        --url "$EXPORT_URL" \
        --output json \
        2>/dev/null
)"; then
    ETAG="$(jq -r '.eTag // empty' <<<"$EXISTING")"
fi

BODY="$(
    jq -n \
        --arg storageId "$STORAGE_RESOURCE_ID" \
        --arg container "$STORAGE_CONTAINER" \
        --arg rootPath "$ROOT_PATH" \
        --arg from "$DEFINITION_FROM" \
        --arg to "$DEFINITION_TO" \
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
        }
        | if $etag != "" then . + {eTag: $etag} else . end
        '
)"

az rest \
    --method put \
    --url "$EXPORT_URL" \
    --body "$BODY" \
    --output none

echo "Reusable definition ready."
echo
echo "Definition month : 2024-02"
echo "Requested run    : 2024-01"
echo
echo "Executing January through request-body timePeriod..."

RUN_BODY="$(
    jq -n \
        --arg from "$RUN_FROM" \
        --arg to "$RUN_TO" \
        '{
          timePeriod: {
            from: $from,
            to: $to
          }
        }'
)"

az rest \
    --method post \
    --url "$RUN_URL" \
    --body "$RUN_BODY" \
    --output none

echo "Run submitted."
echo
echo "Waiting for January run..."

MAX_CHECKS=30
POLL_SECONDS=20

for (( CHECK=1; CHECK<=MAX_CHECKS; CHECK++ )); do

    HISTORY="$(
        az rest \
            --method get \
            --url "$HISTORY_URL" \
            --output json
    )"

    RUN="$(
        jq -c '
          [
            .value[]
            | select(
                (.properties.startDate // "")
                | startswith("2024-01-01")
              )
          ]
          | sort_by(.properties.submittedTime)
          | last // empty
        ' <<<"$HISTORY"
    )"

    if [[ -z "$RUN" ]]; then
        echo "[$CHECK/$MAX_CHECKS] Run not visible yet."
        sleep "$POLL_SECONDS"
        continue
    fi

    STATUS="$(jq -r '.properties.status // "Unknown"' <<<"$RUN")"

    echo "[$CHECK/$MAX_CHECKS] Status: $STATUS"

    case "$STATUS" in

        Completed)
            START_DATE="$(jq -r '.properties.startDate' <<<"$RUN")"
            END_DATE="$(jq -r '.properties.endDate' <<<"$RUN")"
            MANIFEST="$(jq -r '.properties.manifestFile // empty' <<<"$RUN")"

            echo
            echo "============================================"
            echo "REUSABLE EXPORT TEST PASSED"
            echo "============================================"
            echo "Definition period : 2024-02"
            echo "Executed period   : ${START_DATE} -> ${END_DATE}"
            echo "Manifest created  : $([[ -n "$MANIFEST" ]] && echo yes || echo no)"
            echo
            echo "One export definition can be reused for"
            echo "different monthly Execute requests."
            exit 0
            ;;

        Failed|Timeout|DataNotAvailable|NewDataNotAvailable)
            echo
            echo "Test run finished with status: $STATUS" >&2
            exit 1
            ;;

    esac

    sleep "$POLL_SECONDS"

done

echo "ERROR: Test did not complete within the polling window." >&2
exit 1
