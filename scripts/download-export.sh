#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

if [[ $# -ne 4 ]]; then
    echo "Usage: $0 SUBSCRIPTION_ID REPORT_KEY YEAR MONTH"
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

STORAGE_ACCOUNT_NAME="${STORAGE_RESOURCE_ID##*/}"

[[ -n "$STORAGE_ACCOUNT_NAME" ]] ||
    die "Unable to determine Storage Account name."

LOCAL_DIR="${REPO_ROOT}/downloads/${REPORT_KEY}/${YEAR}/${MONTH}"

mkdir -p "$LOCAL_DIR"

echo "Locating latest completed export run..."

RUN_HISTORY="$(
    az rest \
        --method get \
        --url "https://management.azure.com${SCOPE}/providers/Microsoft.CostManagement/exports/${EXPORT_NAME}/runHistory?api-version=${AZURE_COST_API_VERSION}" \
        --output json
)"

LATEST_RUN="$(
    jq -c '
        [
          .value[]
          | select(.properties.status == "Completed")
        ]
        | sort_by(.properties.processingEndTime)
        | last // empty
    ' <<<"$RUN_HISTORY"
)"

[[ -n "$LATEST_RUN" ]] ||
    die "No completed export run found."

MANIFEST_LOCATION="$(
    jq -r '.properties.manifestFile // empty' <<<"$LATEST_RUN"
)"

FILE_LOCATION="$(
    jq -r '.properties.fileName // empty' <<<"$LATEST_RUN"
)"

download_blob() {
    local blob_name="$1"
    local destination="$2"

    echo "Downloading: $(basename "$blob_name")"

    az storage blob download \
        --account-name "$STORAGE_ACCOUNT_NAME" \
        --container-name "$STORAGE_CONTAINER" \
        --name "$blob_name" \
        --file "$destination" \
        --auth-mode login \
        --overwrite true \
        --no-progress \
        --only-show-errors \
        --output none
}

if [[ -n "$MANIFEST_LOCATION" ]]; then

    echo "Manifest-based export detected."

    # Depending on API/export behavior, manifestFile may point either
    # directly to the JSON file or to the export run directory.
    if [[ "$MANIFEST_LOCATION" == *.json ]]; then
        MANIFEST_BLOB="$MANIFEST_LOCATION"
        RUN_PREFIX="$(dirname "$MANIFEST_LOCATION")"
    else
        RUN_PREFIX="${MANIFEST_LOCATION%/}"
        MANIFEST_BLOB="${RUN_PREFIX}/manifest.json"
    fi

    LOCAL_MANIFEST="${LOCAL_DIR}/manifest.json"

    echo "Run directory identified."

    download_blob \
        "$MANIFEST_BLOB" \
        "$LOCAL_MANIFEST"

    [[ -s "$LOCAL_MANIFEST" ]] ||
        die "Downloaded manifest is empty."

    mapfile -t DATA_BLOBS < <(
        jq -r '.blobs[]?.blobName // empty' "$LOCAL_MANIFEST"
    )

    # Fallback for unexpected manifest formats.
    if (( ${#DATA_BLOBS[@]} == 0 )); then

        echo "Manifest did not list partitions; searching run directory..."

        mapfile -t DATA_BLOBS < <(
            az storage blob list \
                --account-name "$STORAGE_ACCOUNT_NAME" \
                --container-name "$STORAGE_CONTAINER" \
                --prefix "${RUN_PREFIX}/" \
                --auth-mode login \
                --query "[?ends_with(name, '.csv')].name" \
                --output tsv
        )
    fi

    (( ${#DATA_BLOBS[@]} > 0 )) ||
        die "No CSV data partitions found."

    echo "Data partitions found: ${#DATA_BLOBS[@]}"

    for blob in "${DATA_BLOBS[@]}"; do

        filename="$(basename "$blob")"

        [[ -n "$filename" ]] ||
            die "Invalid blob name returned."

        download_blob \
            "$blob" \
            "${LOCAL_DIR}/${filename}"
    done

elif [[ -n "$FILE_LOCATION" ]]; then

    echo "Single-file export detected."

    filename="$(basename "$FILE_LOCATION")"

    download_blob \
        "$FILE_LOCATION" \
        "${LOCAL_DIR}/${filename}"

else

    die "Completed export did not provide a downloadable file location."

fi

echo
echo "Download completed successfully."
echo "Files stored in:"
echo "${LOCAL_DIR}"

echo
echo "Downloaded files:"
find "$LOCAL_DIR" -maxdepth 1 -type f -printf '  %f\n' | sort
