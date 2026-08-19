#!/usr/bin/env bash
set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${TEST_DIR}/.." && pwd)"

# shellcheck source=../scripts/common.sh
source "${REPO_ROOT}/scripts/common.sh"

require_variable TEST_SUBSCRIPTION_ID
require_variable TEST_REPORT_KEY
require_variable TEST_YEAR
require_variable TEST_MONTH

echo "Running subscription-level historical export test"
echo "Test period: ${TEST_YEAR}-$(normalize_month "$TEST_MONTH")"

"${REPO_ROOT}/scripts/export-subscription-month.sh" \
    "$TEST_SUBSCRIPTION_ID" \
    "$TEST_REPORT_KEY" \
    "$TEST_YEAR" \
    "$TEST_MONTH"

"${REPO_ROOT}/scripts/run-export.sh" \
    "$TEST_SUBSCRIPTION_ID" \
    "$TEST_YEAR" \
    "$TEST_MONTH"

echo
echo "Export submitted."
echo "Use check-export.sh to monitor completion."
