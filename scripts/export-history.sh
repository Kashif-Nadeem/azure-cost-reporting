#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# Azure Cost Reporting - Historical Backfill
# ============================================================
#
# One-time historical Cost Management backfill.
#
# Workflow:
#   1. Discover enabled subscriptions directly from Azure Resource Manager.
#   2. Exclude subscriptions where Cost Management exports are unavailable.
#   3. Create one reusable export definition per eligible subscription.
#   4. Process one month across all eligible subscriptions.
#   5. Detect completion primarily from Blob Storage manifests.
#   6. Query Cost Management run history only for unresolved exports.
#   7. Continue month-by-month through the current month.
#
# Raw cost data remains in Azure Blob Storage. Nothing is downloaded locally.
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

require_command az
require_command jq
require_command sha256sum
require_command date

START_YEAR="${AZURE_COST_START_YEAR:-2024}"
EXPORT_NAME="${AZURE_COST_REUSABLE_EXPORT_NAME:-cost-usage-history}"

# Submission and polling controls.
# Override locally with environment variables when required.
SUBMIT_DELAY_SECONDS="${AZURE_COST_SUBMIT_DELAY_SECONDS:-1}"
STORAGE_POLL_SECONDS="${AZURE_COST_STORAGE_POLL_SECONDS:-15}"
STATUS_POLL_EVERY="${AZURE_COST_STATUS_POLL_EVERY:-4}"
MONTH_TIMEOUT_SECONDS="${AZURE_COST_MONTH_TIMEOUT_SECONDS:-900}"

validate_year "$START_YEAR"

CURRENT_PERIOD="$(date -u +%Y-%m)"
CURRENT_YEAR="${CURRENT_PERIOD%-*}"

if (( 10#$START_YEAR > 10#$CURRENT_YEAR )); then
    die "Start year cannot be later than the current year."
fi


# ------------------------------------------------------------
# Generate a stable anonymous report/storage key.
# ------------------------------------------------------------

report_key() {
    local subscription_id="$1"
    local digest

    digest="$(
        printf '%s' "$subscription_id" |
            sha256sum |
            awk '{print $1}'
    )"

    printf 'sub-%s' "${digest:0:12}"
}


# ------------------------------------------------------------
# Retry transient Azure errors.
#
# Authorization and subscription-not-found errors are permanent
# for the current run and are therefore not retried.
# ------------------------------------------------------------

retry_command() {
    local attempt=1
    local max_attempts=5
    local delay=5
    local output
    local rc

    while true; do

        set +e
        output="$("$@" 2>&1)"
        rc=$?
        set -e

        if [[ -n "$output" ]]; then
            if (( rc == 0 )); then
                printf '%s\n' "$output"
            else
                printf '%s\n' "$output" >&2
            fi
        fi

        if (( rc == 0 )); then
            return 0
        fi

        if grep -qiE \
            'AuthorizationFailed|Forbidden|SubscriptionNotFound|InvalidAuthenticationTokenTenant' \
            <<<"$output"; then

            return 2
        fi

        if (( attempt >= max_attempts )); then
            return 1
        fi

        echo "Transient request failure. Retrying in ${delay}s..." >&2

        sleep "$delay"

        attempt=$((attempt + 1))
        delay=$((delay * 2))

    done
}


# ------------------------------------------------------------
# Determine the export end date.
#
# Historical months use their final calendar day.
# The current month ends at today's UTC date.
# ------------------------------------------------------------

month_end_date() {
    local year="$1"
    local month="$2"
    local period="${year}-${month}"

    if [[ "$period" == "$CURRENT_PERIOD" ]]; then
        date -u +%Y-%m-%d
    else
        date -u \
            -d "${year}-${month}-01 +1 month -1 day" \
            +%Y-%m-%d
    fi
}


# ------------------------------------------------------------
# Query status of a specific monthly execution.
# ------------------------------------------------------------

run_status() {
    local subscription_id="$1"
    local year="$2"
    local month="$3"
    local scope
    local history

    scope="$(subscription_scope "$subscription_id")"

    if ! history="$(
        az rest \
            --method get \
            --url "https://management.azure.com${scope}/providers/Microsoft.CostManagement/exports/${EXPORT_NAME}/runHistory?api-version=${AZURE_COST_API_VERSION}" \
            --output json \
            2>/dev/null
    )"; then

        printf 'Unknown'
        return
    fi

    jq -r \
        --arg start "${year}-${month}-01" \
        '
        [
          .value[]
          | select(
              (.properties.startDate // "")
              | startswith($start)
            )
        ]
        | sort_by(
            .properties.processingStartTime
            // .properties.submittedTime
            // ""
          )
        | last
        | .properties.status // "NotFound"
        ' <<<"$history"
}


# ------------------------------------------------------------
# Return anonymous report keys that already have a completed
# manifest for the specified date range.
# ------------------------------------------------------------

load_completed_report_keys() {
    local date_range="$1"

    az storage blob list \
        --account-name "$STORAGE_ACCOUNT_NAME" \
        --container-name "$STORAGE_CONTAINER" \
        --prefix "${EXPORT_ROOT_PATH}/" \
        --auth-mode login \
        --query "[?contains(name, '/${EXPORT_NAME}/${date_range}/') && ends_with(name, '/manifest.json')].name" \
        --output tsv \
        2>/dev/null |
    while IFS= read -r blob_name; do

        [[ -n "$blob_name" ]] || continue

        local relative
        local key

        relative="${blob_name#${EXPORT_ROOT_PATH}/}"
        key="${relative%%/*}"

        [[ -n "$key" ]] && printf '%s\n' "$key"

    done
}


# ------------------------------------------------------------
# Authentication
# ------------------------------------------------------------

echo "Checking Azure authentication..."

if ! az account show --output none 2>/dev/null; then
    die "Azure CLI is not authenticated. Run 'az login'."
fi


# ------------------------------------------------------------
# Discover subscriptions directly from ARM.
# ------------------------------------------------------------

mapfile -t SUBSCRIPTIONS < <(
    az rest \
        --method get \
        --url "https://management.azure.com/subscriptions?api-version=2022-12-01" \
        --query "value[?state=='Enabled'].subscriptionId" \
        --output tsv
)

DISCOVERED_COUNT="${#SUBSCRIPTIONS[@]}"

(( DISCOVERED_COUNT > 0 )) ||
    die "No enabled Azure subscriptions were found."


# ------------------------------------------------------------
# Validate Cost Management read access.
# ------------------------------------------------------------

echo
echo "Checking Cost Management export access..."

declare -a READ_ELIGIBLE_SUBSCRIPTIONS=()

UNAUTHORIZED_COUNT=0
UNAVAILABLE_COUNT=0
CHECK_INDEX=0

for SUBSCRIPTION_ID in "${SUBSCRIPTIONS[@]}"; do

    CHECK_INDEX=$((CHECK_INDEX + 1))
    REPORT_KEY="$(report_key "$SUBSCRIPTION_ID")"
    ERROR_FILE="$(mktemp)"

    printf '  [%d/%d] %s ... ' \
        "$CHECK_INDEX" \
        "$DISCOVERED_COUNT" \
        "$REPORT_KEY"

    if az rest \
        --method get \
        --url "https://management.azure.com/subscriptions/${SUBSCRIPTION_ID}/providers/Microsoft.CostManagement/exports?api-version=${AZURE_COST_API_VERSION}" \
        --output none \
        2>"$ERROR_FILE"; then

        echo "eligible"
        READ_ELIGIBLE_SUBSCRIPTIONS+=("$SUBSCRIPTION_ID")

    elif grep -qiE \
        'AuthorizationFailed|Forbidden|does not have authorization' \
        "$ERROR_FILE"; then

        echo "unauthorized - skipping"
        UNAUTHORIZED_COUNT=$((UNAUTHORIZED_COUNT + 1))

    elif grep -qiE \
        'SubscriptionNotFound|could not be found' \
        "$ERROR_FILE"; then

        echo "unavailable - skipping"
        UNAVAILABLE_COUNT=$((UNAVAILABLE_COUNT + 1))

    else

        echo "ERROR"
        cat "$ERROR_FILE" >&2
        rm -f "$ERROR_FILE"

        die "Unexpected error while checking Cost Management access."

    fi

    rm -f "$ERROR_FILE"

done

SUBSCRIPTIONS=("${READ_ELIGIBLE_SUBSCRIPTIONS[@]}")
unset READ_ELIGIBLE_SUBSCRIPTIONS

READ_ELIGIBLE_COUNT="${#SUBSCRIPTIONS[@]}"

(( READ_ELIGIBLE_COUNT > 0 )) ||
    die "No subscriptions with Cost Management export access were found."


echo
echo "Subscription access summary"
echo "---------------------------"
echo "Discovered     : ${DISCOVERED_COUNT}"
echo "Read eligible  : ${READ_ELIGIBLE_COUNT}"
echo "Unauthorized   : ${UNAUTHORIZED_COUNT}"
echo "Unavailable    : ${UNAVAILABLE_COUNT}"


# ------------------------------------------------------------
# Create/reuse one export definition per eligible subscription.
#
# A subscription can have read access but still lack write
# permission. Such subscriptions are skipped here.
# ------------------------------------------------------------

echo
echo "Preparing reusable export definitions..."

declare -a READY_SUBSCRIPTIONS=()

WRITE_UNAUTHORIZED_COUNT=0
PREPARE_FAILED_COUNT=0
PREPARE_INDEX=0

for SUBSCRIPTION_ID in "${SUBSCRIPTIONS[@]}"; do

    PREPARE_INDEX=$((PREPARE_INDEX + 1))
    REPORT_KEY="$(report_key "$SUBSCRIPTION_ID")"

    printf '  [%d/%d] %s ... ' \
        "$PREPARE_INDEX" \
        "$READ_ELIGIBLE_COUNT" \
        "$REPORT_KEY"

    set +e

    PREPARE_OUTPUT="$(
        retry_command \
            "${SCRIPT_DIR}/create-reusable-export.sh" \
            "$SUBSCRIPTION_ID" \
            "$REPORT_KEY" \
            2>&1
    )"

    PREPARE_RC=$?

    set -e

    case "$PREPARE_RC" in

        0)
            echo "ready"
            READY_SUBSCRIPTIONS+=("$SUBSCRIPTION_ID")
            ;;

        2)
            echo "unauthorized/unavailable - skipping"
            WRITE_UNAUTHORIZED_COUNT=$((WRITE_UNAUTHORIZED_COUNT + 1))
            ;;

        *)
            echo "failed - skipping"

            [[ -n "$PREPARE_OUTPUT" ]] &&
                printf '%s\n' "$PREPARE_OUTPUT" >&2

            PREPARE_FAILED_COUNT=$((PREPARE_FAILED_COUNT + 1))
            ;;

    esac

    sleep "$SUBMIT_DELAY_SECONDS"

done

SUBSCRIPTIONS=("${READY_SUBSCRIPTIONS[@]}")
unset READY_SUBSCRIPTIONS

SUBSCRIPTION_COUNT="${#SUBSCRIPTIONS[@]}"

(( SUBSCRIPTION_COUNT > 0 )) ||
    die "No subscriptions have usable Cost Management export definitions."


echo
echo "Reusable export preparation summary"
echo "-----------------------------------"
echo "Ready          : ${SUBSCRIPTION_COUNT}"
echo "Write denied   : ${WRITE_UNAUTHORIZED_COUNT}"
echo "Prepare failed : ${PREPARE_FAILED_COUNT}"


# ------------------------------------------------------------
# Calculate month count.
# ------------------------------------------------------------

STORAGE_ACCOUNT_NAME="${STORAGE_RESOURCE_ID##*/}"

PERIOD="${START_YEAR}-01"
TOTAL_MONTHS=0
TMP_PERIOD="$PERIOD"

while [[ "$TMP_PERIOD" < "$CURRENT_PERIOD" || "$TMP_PERIOD" == "$CURRENT_PERIOD" ]]; do

    TOTAL_MONTHS=$((TOTAL_MONTHS + 1))

    TMP_YEAR="${TMP_PERIOD%-*}"
    TMP_MONTH="${TMP_PERIOD#*-}"

    TMP_PERIOD="$(
        date -u \
            -d "${TMP_YEAR}-${TMP_MONTH}-01 +1 month" \
            +%Y-%m
    )"

done


# ------------------------------------------------------------
# Historical month-by-month backfill.
# ------------------------------------------------------------

MONTH_INDEX=0
BACKFILL_FAILED_COUNT=0

while [[ "$PERIOD" < "$CURRENT_PERIOD" || "$PERIOD" == "$CURRENT_PERIOD" ]]; do

    MONTH_INDEX=$((MONTH_INDEX + 1))

    YEAR="${PERIOD%-*}"
    MONTH="${PERIOD#*-}"

    # Azure Cost Management stores monthly exports under a folder
    # representing the full calendar month, even when the current
    # month's execution ends at the current date.
    STORAGE_MONTH_END="$(
        date -u             -d "${YEAR}-${MONTH}-01 +1 month -1 day"             +%Y-%m-%d
    )"

    START_COMPACT="${YEAR}${MONTH}01"
    END_COMPACT="${STORAGE_MONTH_END//-/}"

    DATE_RANGE="${START_COMPACT}-${END_COMPACT}"

    echo
    echo "============================================================"
    echo "Month ${MONTH_INDEX}/${TOTAL_MONTHS}: ${PERIOD}"
    echo "============================================================"


    # --------------------------------------------------------
    # Detect data already present in Blob Storage.
    # --------------------------------------------------------

    declare -A COMPLETE_KEYS=()

    while IFS= read -r KEY; do
        [[ -n "$KEY" ]] && COMPLETE_KEYS["$KEY"]=1
    done < <(
        load_completed_report_keys "$DATE_RANGE"
    )


    declare -a PENDING_IDS=()
    declare -a PENDING_KEYS=()

    EXISTING_COUNT=0
    SUBMITTED_COUNT=0
    SUBMIT_FAILED_COUNT=0
    INDEX=0


    # --------------------------------------------------------
    # Submit this month for subscriptions without a manifest.
    # --------------------------------------------------------

    for SUBSCRIPTION_ID in "${SUBSCRIPTIONS[@]}"; do

        INDEX=$((INDEX + 1))
        REPORT_KEY="$(report_key "$SUBSCRIPTION_ID")"

        if [[ -n "${COMPLETE_KEYS[$REPORT_KEY]:-}" ]]; then
            EXISTING_COUNT=$((EXISTING_COUNT + 1))
            continue
        fi

        printf '  [%d/%d] %s ... ' \
            "$INDEX" \
            "$SUBSCRIPTION_COUNT" \
            "$REPORT_KEY"

        set +e

        RUN_OUTPUT="$(
            retry_command \
                "${SCRIPT_DIR}/run-reusable-export.sh" \
                "$SUBSCRIPTION_ID" \
                "$YEAR" \
                "$MONTH" \
                2>&1
        )"

        RUN_RC=$?

        set -e

        case "$RUN_RC" in

            0)
                echo "submitted"

                PENDING_IDS+=("$SUBSCRIPTION_ID")
                PENDING_KEYS+=("$REPORT_KEY")

                SUBMITTED_COUNT=$((SUBMITTED_COUNT + 1))
                ;;

            2)
                echo "unavailable - skipped"
                SUBMIT_FAILED_COUNT=$((SUBMIT_FAILED_COUNT + 1))
                ;;

            *)
                echo "submission failed"

                [[ -n "$RUN_OUTPUT" ]] &&
                    printf '%s\n' "$RUN_OUTPUT" >&2

                SUBMIT_FAILED_COUNT=$((SUBMIT_FAILED_COUNT + 1))
                ;;

        esac

        sleep "$SUBMIT_DELAY_SECONDS"

    done


    echo
    echo "Month submission summary"
    echo "  Existing manifests : ${EXISTING_COUNT}"
    echo "  Submitted          : ${SUBMITTED_COUNT}"
    echo "  Submission failures: ${SUBMIT_FAILED_COUNT}"

    BACKFILL_FAILED_COUNT=$((BACKFILL_FAILED_COUNT + SUBMIT_FAILED_COUNT))


    # --------------------------------------------------------
    # Wait for Blob manifests.
    #
    # Blob Storage is polled frequently. Cost Management run
    # history is queried only periodically for unresolved jobs.
    # --------------------------------------------------------

    if (( ${#PENDING_IDS[@]} > 0 )); then

        START_EPOCH="$(date +%s)"
        POLL_COUNT=0
        NO_DATA_COUNT=0
        COMPLETED_COUNT=0

        while (( ${#PENDING_IDS[@]} > 0 )); do

            POLL_COUNT=$((POLL_COUNT + 1))

            sleep "$STORAGE_POLL_SECONDS"

            declare -A CURRENT_COMPLETE_KEYS=()

            while IFS= read -r KEY; do
                [[ -n "$KEY" ]] && CURRENT_COMPLETE_KEYS["$KEY"]=1
            done < <(
                load_completed_report_keys "$DATE_RANGE"
            )

            declare -a NEXT_IDS=()
            declare -a NEXT_KEYS=()

            for (( i=0; i<${#PENDING_IDS[@]}; i++ )); do

                SUBSCRIPTION_ID="${PENDING_IDS[$i]}"
                REPORT_KEY="${PENDING_KEYS[$i]}"

                if [[ -n "${CURRENT_COMPLETE_KEYS[$REPORT_KEY]:-}" ]]; then

                    COMPLETED_COUNT=$((COMPLETED_COUNT + 1))
                    continue

                fi

                NEXT_IDS+=("$SUBSCRIPTION_ID")
                NEXT_KEYS+=("$REPORT_KEY")

            done

            PENDING_IDS=("${NEXT_IDS[@]}")
            PENDING_KEYS=("${NEXT_KEYS[@]}")

            ELAPSED=$(($(date +%s) - START_EPOCH))

            echo "  Storage poll ${POLL_COUNT}: completed=${COMPLETED_COUNT}/${SUBMITTED_COUNT}, pending=${#PENDING_IDS[@]}, elapsed=${ELAPSED}s"

            (( ${#PENDING_IDS[@]} == 0 )) && break


            # ------------------------------------------------
            # Periodically inspect unresolved Cost Management
            # executions for no-data or failed runs.
            # ------------------------------------------------

            if (( POLL_COUNT % STATUS_POLL_EVERY == 0 )); then

                NEXT_IDS=()
                NEXT_KEYS=()

                for (( i=0; i<${#PENDING_IDS[@]}; i++ )); do

                    SUBSCRIPTION_ID="${PENDING_IDS[$i]}"
                    REPORT_KEY="${PENDING_KEYS[$i]}"

                    STATUS="$(
                        run_status \
                            "$SUBSCRIPTION_ID" \
                            "$YEAR" \
                            "$MONTH"
                    )"

                    case "$STATUS" in

                        Completed)
                            # Keep pending until its Blob manifest
                            # becomes visible.
                            NEXT_IDS+=("$SUBSCRIPTION_ID")
                            NEXT_KEYS+=("$REPORT_KEY")
                            ;;

                        DataNotAvailable|NewDataNotAvailable)
                            NO_DATA_COUNT=$((NO_DATA_COUNT + 1))
                            ;;

                        Failed|Timeout)
                            echo "  ${REPORT_KEY}: ${STATUS}" >&2

                            BACKFILL_FAILED_COUNT=$((BACKFILL_FAILED_COUNT + 1))
                            ;;

                        *)
                            NEXT_IDS+=("$SUBSCRIPTION_ID")
                            NEXT_KEYS+=("$REPORT_KEY")
                            ;;

                    esac

                done

                PENDING_IDS=("${NEXT_IDS[@]}")
                PENDING_KEYS=("${NEXT_KEYS[@]}")

                echo "  Cost status check: pending=${#PENDING_IDS[@]}, no-data=${NO_DATA_COUNT}"

            fi


            (( ${#PENDING_IDS[@]} == 0 )) && break


            # ------------------------------------------------
            # Stop waiting forever. The script is resume-safe;
            # existing manifests will be skipped on the next run.
            # ------------------------------------------------

            if (( ELAPSED >= MONTH_TIMEOUT_SECONDS )); then

                echo "  WARNING: ${#PENDING_IDS[@]} export(s) still unresolved after ${MONTH_TIMEOUT_SECONDS}s." >&2

                BACKFILL_FAILED_COUNT=$((BACKFILL_FAILED_COUNT + ${#PENDING_IDS[@]}))

                break

            fi

        done


        echo "Month ${PERIOD} result: manifests=${COMPLETED_COUNT}, no-data=${NO_DATA_COUNT}, unresolved=${#PENDING_IDS[@]}"

    else

        echo "Month ${PERIOD} already complete or no submissions were required."

    fi


    PERIOD="$(
        date -u \
            -d "${YEAR}-${MONTH}-01 +1 month" \
            +%Y-%m
    )"

done


# ------------------------------------------------------------
# Final summary
# ------------------------------------------------------------

echo
echo "============================================================"
echo "Historical backfill finished."
echo "============================================================"
echo "Subscriptions processed : ${SUBSCRIPTION_COUNT}"
echo "Unauthorized (read)      : ${UNAUTHORIZED_COUNT}"
echo "Unavailable              : ${UNAVAILABLE_COUNT}"
echo "Write denied             : ${WRITE_UNAUTHORIZED_COUNT}"
echo "Prepare failures         : ${PREPARE_FAILED_COUNT}"
echo "Backfill failures        : ${BACKFILL_FAILED_COUNT}"
echo
echo "Raw Cost Management data remains in Azure Blob Storage."
echo "No raw CSV files were downloaded locally."

if (( PREPARE_FAILED_COUNT > 0 || BACKFILL_FAILED_COUNT > 0 )); then
    exit 1
fi
