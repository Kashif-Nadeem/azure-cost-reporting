#!/usr/bin/env bash
set -euo pipefail

: "${RESOURCE_GROUP:?Set RESOURCE_GROUP}"
: "${LOCATION:?Set LOCATION}"
: "${FUNCTION_APP_NAME:?Set FUNCTION_APP_NAME}"
: "${FUNCTION_PLAN_NAME:?Set FUNCTION_PLAN_NAME}"
: "${FUNCTION_STORAGE_ACCOUNT:?Set FUNCTION_STORAGE_ACCOUNT}"
: "${MANAGED_IDENTITY_NAME:?Set MANAGED_IDENTITY_NAME}"
: "${APPLICATION_INSIGHTS_NAME:?Set APPLICATION_INSIGHTS_NAME}"
: "${LOG_ANALYTICS_WORKSPACE_NAME:?Set LOG_ANALYTICS_WORKSPACE_NAME}"
: "${REPORT_STORAGE_ACCOUNT:?Set REPORT_STORAGE_ACCOUNT}"
: "${MANAGEMENT_GROUP_ID:?Set MANAGEMENT_GROUP_ID}"

REPORT_CONTAINER="${REPORT_CONTAINER:-azure-invoice-reports}"


az deployment group create \
  --resource-group "$RESOURCE_GROUP" \
  --template-file infra/main.bicep \
  --parameters \
    location="$LOCATION" \
    functionAppName="$FUNCTION_APP_NAME" \
    functionPlanName="$FUNCTION_PLAN_NAME" \
    functionStorageAccountName="$FUNCTION_STORAGE_ACCOUNT" \
    managedIdentityName="$MANAGED_IDENTITY_NAME" \
    applicationInsightsName="$APPLICATION_INSIGHTS_NAME" \
    logAnalyticsWorkspaceName="$LOG_ANALYTICS_WORKSPACE_NAME" \
    reportStorageAccountName="$REPORT_STORAGE_ACCOUNT" \
    reportContainerName="$REPORT_CONTAINER"


PRINCIPAL_ID="$(
  az identity show \
    --resource-group "$RESOURCE_GROUP" \
    --name "$MANAGED_IDENTITY_NAME" \
    --query principalId \
    -o tsv
)"


az deployment mg create \
  --management-group-id "$MANAGEMENT_GROUP_ID" \
  --location "$LOCATION" \
  --template-file infra/management-group-roles.bicep \
  --parameters principalId="$PRINCIPAL_ID"
