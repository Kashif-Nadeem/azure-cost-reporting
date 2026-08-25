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
: "${KEY_VAULT_NAME:?Set KEY_VAULT_NAME}"
: "${MANAGEMENT_GROUP_ID:?Set MANAGEMENT_GROUP_ID}"

REPORT_CONTAINER="${REPORT_CONTAINER:-azure-invoice-reports}"
REPORT_RECIPIENTS="${REPORT_RECIPIENTS:-}"
EMAIL_ENABLED="${EMAIL_ENABLED:-false}"
MONTHLY_REPORT_SCHEDULE="${MONTHLY_REPORT_SCHEDULE:-0 0 13 5 * *}"

echo "Deploying core reporting infrastructure..."

az deployment group create \
  --resource-group "$RESOURCE_GROUP" \
  --name "deploy-cost-reporting-core" \
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
    reportContainerName="$REPORT_CONTAINER" \
    keyVaultName="$KEY_VAULT_NAME" \
    reportRecipients="$REPORT_RECIPIENTS" \
    emailEnabled="$EMAIL_ENABLED" \
    monthlyReportSchedule="$MONTHLY_REPORT_SCHEDULE" \
  --output table

MI_PRINCIPAL_ID="$(
  az identity show \
    --resource-group "$RESOURCE_GROUP" \
    --name "$MANAGED_IDENTITY_NAME" \
    --query principalId \
    --output tsv
)"

echo "Deploying Key Vault..."

az deployment group create \
  --resource-group "$RESOURCE_GROUP" \
  --name "deploy-cost-reporting-key-vault" \
  --template-file infra/key-vault.bicep \
  --parameters \
    location="$LOCATION" \
    keyVaultName="$KEY_VAULT_NAME" \
    managedIdentityPrincipalId="$MI_PRINCIPAL_ID" \
  --output table

echo "Deploying management-group reporting roles..."

az deployment mg create \
  --management-group-id "$MANAGEMENT_GROUP_ID" \
  --location "$LOCATION" \
  --name "deploy-cost-reporting-roles" \
  --template-file infra/management-group-roles.bicep \
  --parameters \
    managedIdentityPrincipalId="$MI_PRINCIPAL_ID" \
  --output table

echo "Infrastructure deployment complete."
