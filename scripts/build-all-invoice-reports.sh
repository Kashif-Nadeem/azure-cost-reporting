#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ -f ".venv/bin/activate" ]]; then
    source .venv/bin/activate
fi

source config/config.sh

START_YEAR="${START_YEAR:-2024}"
CURRENT_YEAR="$(date +%Y)"

echo "========================================"
echo "Updating subscription registry"
echo "========================================"

python scripts/update-subscription-registry.py

echo
echo "========================================"
echo "Building invoice reports"
echo "========================================"

for ((year=START_YEAR; year<=CURRENT_YEAR; year++)); do
    python scripts/build-invoice-report.py "$year"
done

echo
echo "========================================"
echo "Building multi-year summary"
echo "========================================"

python scripts/build-invoice-summary.py \
    "$START_YEAR" \
    "$CURRENT_YEAR"

echo
echo "========================================"
echo "Completed"
echo "========================================"

ls -lh output/invoices/
