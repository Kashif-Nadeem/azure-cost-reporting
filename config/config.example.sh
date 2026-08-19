#!/usr/bin/env bash

# ============================================================
# Azure Cost Reporting - Local Configuration Example
# ============================================================
#
# Copy this file to:
#
#   config/config.sh
#
# config/config.sh is excluded from Git and should contain
# environment-specific values.
# ============================================================

# Azure Resource Manager ID of the Storage Account used for exports.
STORAGE_RESOURCE_ID=""

# Destination Blob container.
STORAGE_CONTAINER=""

# Generic path within the Blob container.
EXPORT_ROOT_PATH="azure-cost-history"

# Optional local regression-test configuration.
TEST_SUBSCRIPTION_ID=""
TEST_REPORT_KEY="validation-subscription"
TEST_YEAR=""
TEST_MONTH=""
