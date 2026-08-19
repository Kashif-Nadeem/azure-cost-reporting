#!/usr/bin/env bash

# ============================================================
# Azure Cost Reporting - Common Functions
# ============================================================

COMMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${COMMON_DIR}/.." && pwd)"

CONFIG_FILE="${AZURE_COST_CONFIG:-${REPO_ROOT}/config/config.sh}"

if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "ERROR: Configuration file not found: $CONFIG_FILE" >&2
    echo "Copy config/config.example.sh to config/config.sh and configure it." >&2
    exit 1
fi

# shellcheck source=/dev/null
source "$CONFIG_FILE"

AZURE_COST_API_VERSION="${AZURE_COST_API_VERSION:-2025-03-01}"
EXPORT_ROOT_PATH="${EXPORT_ROOT_PATH:-azure-cost-history}"

die() {
    echo "ERROR: $*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 ||
        die "Required command not found: $1"
}

require_variable() {
    local name="$1"

    [[ -n "${!name:-}" ]] ||
        die "Required configuration variable is not set: $name"
}

validate_subscription_id() {
    local value="$1"

    [[ "$value" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]] ||
        die "Invalid Azure subscription ID."
}

validate_report_key() {
    local value="$1"

    [[ "$value" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]] ||
        die "Report key may contain only letters, numbers, dots, underscores and hyphens."
}

normalize_month() {
    local month="$1"

    [[ "$month" =~ ^[0-9]{1,2}$ ]] ||
        die "Month must be between 1 and 12."

    month=$((10#$month))

    (( month >= 1 && month <= 12 )) ||
        die "Month must be between 1 and 12."

    printf "%02d" "$month"
}

validate_year() {
    local year="$1"

    [[ "$year" =~ ^[0-9]{4}$ ]] ||
        die "Year must be a four-digit number."
}

build_export_name() {
    local year="$1"
    local month="$2"

    # Export resources exist inside each subscription scope, so the
    # subscription name or customer name does not need to appear here.
    printf "cost-usage-%s-%s" "$year" "$month"
}

subscription_scope() {
    printf "/subscriptions/%s" "$1"
}

require_command az
require_command jq

require_variable STORAGE_RESOURCE_ID
require_variable STORAGE_CONTAINER
