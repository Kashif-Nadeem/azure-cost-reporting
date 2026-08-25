# Automated Monthly Azure Invoice Reporting

This directory contains the production automation component of the Azure Cost Reporting project.

The Azure Function:

1. discovers enabled Azure subscriptions,
2. retrieves paid invoices through the Azure Billing API,
3. generates a monthly summary CSV,
4. generates a detailed invoice CSV,
5. reconciles summary and detail totals,
6. archives the monthly reports in Azure Blob Storage,
7. retrieves SMTP credentials from Azure Key Vault,
8. emails the two CSV reports,
9. runs automatically every month.

---

# Architecture

```text
Azure Functions Flex Consumption
        |
        +-- Python 3.14
        |
        +-- User-assigned Managed Identity
        |
        +-- Azure Resource Manager
        |       |
        |       +-- Discover enabled subscriptions
        |
        +-- Azure Billing Invoice API
        |       |
        |       +-- Retrieve paid invoices
        |
        +-- Report generator
        |       |
        |       +-- Azure-Expenses-YYYY-MM.csv
        |       +-- Azure-Invoice-Detail-YYYY-MM.csv
        |       +-- manifest.json
        |
        +-- Azure Blob Storage
        |
        +-- Azure Key Vault
                |
                +-- smtp-username
                +-- smtp-from-address
                +-- smtp-app-password
                        |
                        +-- SMTP / STARTTLS
                                |
                                +-- Report recipients
```

---

# Monthly Output

Each successful reporting month creates:

```text
<report-container>/
    YYYY/MM/
        Azure-Expenses-YYYY-MM.csv
        Azure-Invoice-Detail-YYYY-MM.csv
        manifest.json
```

The email contains:

```text
Azure-Expenses-YYYY-MM.csv
Azure-Invoice-Detail-YYYY-MM.csv
```

The manifest remains in Azure Storage for validation and audit purposes.

---

# Function Files

```text
function_app/
├── README.md
├── function_app.py
├── reporting.py
├── requirements.txt
├── host.json
└── local.settings.example.json
```

The timer function is:

```text
monthly_invoice_report
```

---

# Infrastructure

Reusable infrastructure is located under:

```text
../infra/
```

Templates:

```text
main.bicep
key-vault.bicep
management-group-roles.bicep
main.bicepparam.example
deploy.example.sh
```

---

# Azure Resources

Typical deployment uses:

```text
Azure Resource Group
Azure Functions Flex Consumption plan
Azure Function App
Function runtime Storage Account
Report Storage Account
Blob report container
User-assigned Managed Identity
Application Insights
Log Analytics Workspace
Azure Key Vault
Azure RBAC
```

---

# Generic Deployment Variables

From the repository root:

```bash
export RESOURCE_GROUP="<resource-group>"
export LOCATION="<azure-region>"

export FUNCTION_APP_NAME="<function-app-name>"
export FUNCTION_PLAN_NAME="<function-plan-name>"
export FUNCTION_STORAGE_ACCOUNT="<function-storage-account>"

export MANAGED_IDENTITY_NAME="<managed-identity-name>"

export APPLICATION_INSIGHTS_NAME="<application-insights-name>"
export LOG_ANALYTICS_WORKSPACE_NAME="<log-analytics-workspace>"

export REPORT_STORAGE_ACCOUNT="<report-storage-account>"
export REPORT_CONTAINER="azure-invoice-reports"

export KEY_VAULT_NAME="<key-vault-name>"

export MANAGEMENT_GROUP_ID="<management-group-id>"

export REPORT_RECIPIENTS=""
export EMAIL_ENABLED="false"
export MONTHLY_REPORT_SCHEDULE="0 0 13 5 * *"
```

Never commit real environment values.

---

# Validate Infrastructure Templates

From the repository root:

```bash
az bicep build --file infra/main.bicep

az bicep build --file infra/key-vault.bicep

az bicep build \
  --file infra/management-group-roles.bicep
```

Remove generated JSON:

```bash
rm -f \
  infra/main.json \
  infra/key-vault.json \
  infra/management-group-roles.json
```

---

# Deploy Infrastructure

The generic deployment wrapper is:

```bash
./infra/deploy.example.sh
```

It deploys or configures the core infrastructure and RBAC assignments.

---

# Managed Identity

Get the principal ID:

```bash
MI_PRINCIPAL_ID="$(
  az identity show \
    --resource-group "$RESOURCE_GROUP" \
    --name "$MANAGED_IDENTITY_NAME" \
    --query principalId \
    -o tsv
)"
```

Get the client ID:

```bash
MI_CLIENT_ID="$(
  az identity show \
    --resource-group "$RESOURCE_GROUP" \
    --name "$MANAGED_IDENTITY_NAME" \
    --query clientId \
    -o tsv
)"
```

---

# Reporting RBAC

Typical production permissions:

## Management Group

```text
Billing Reader
Cost Management Reader
```

These permissions can inherit to subscriptions beneath the management group.

## Function Runtime Storage

```text
Storage Blob Data Owner
Storage Blob Data Contributor
Storage Queue Data Contributor
Storage Table Data Contributor
```

## Report Blob Container

```text
Storage Blob Data Contributor
```

## Key Vault

```text
Key Vault Secrets User
```

## Application Insights

```text
Monitoring Metrics Publisher
```

Use the narrowest practical RBAC scope.

---

# Flex Consumption Runtime

The Function runtime is configured using:

```text
properties.functionAppConfig.runtime
```

Verify:

```bash
az functionapp show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$FUNCTION_APP_NAME" \
  --query "properties.functionAppConfig.runtime" \
  -o json
```

Expected:

```json
{
  "name": "python",
  "version": "3.14"
}
```

For deployed Flex Consumption Functions, do not configure:

```text
FUNCTIONS_WORKER_RUNTIME
```

as a Function App setting.

It can still exist in local Functions development settings.

---

# Identity-Based AzureWebJobsStorage

Configure host storage using Managed Identity:

```bash
az functionapp config appsettings set \
  --resource-group "$RESOURCE_GROUP" \
  --name "$FUNCTION_APP_NAME" \
  --settings \
    "AzureWebJobsStorage__accountName=$FUNCTION_STORAGE_ACCOUNT" \
    "AzureWebJobsStorage__credential=managedidentity" \
    "AzureWebJobsStorage__clientId=$MI_CLIENT_ID" \
  --output none
```

Remove an old connection-string-based setting if present:

```bash
az functionapp config appsettings delete \
  --resource-group "$RESOURCE_GROUP" \
  --name "$FUNCTION_APP_NAME" \
  --setting-names AzureWebJobsStorage \
  --output none
```

---

# Deploy Key Vault

Key Vault is defined by:

```text
infra/key-vault.bicep
```

Example deployment:

```bash
az deployment group create \
  --resource-group "$RESOURCE_GROUP" \
  --name "deploy-cost-reporting-key-vault" \
  --template-file infra/key-vault.bicep \
  --parameters \
    keyVaultName="$KEY_VAULT_NAME" \
    managedIdentityPrincipalId="$MI_PRINCIPAL_ID"
```

---

# Key Vault Secrets

The Function expects:

```text
smtp-username
smtp-from-address
smtp-app-password
```

The SMTP password should normally be a Google App Password rather than the normal Google account password.

Typical SMTP endpoint:

```text
smtp.gmail.com
Port 587
STARTTLS
```

---

# Temporarily Grant Secret Management Access

Get the Key Vault ID:

```bash
KV_ID="$(
  az keyvault show \
    --resource-group "$RESOURCE_GROUP" \
    --name "$KEY_VAULT_NAME" \
    --query id \
    -o tsv
)"
```

Get the current user's object ID:

```bash
ME_OBJECT_ID="$(
  az ad signed-in-user show \
    --query id \
    -o tsv
)"
```

Grant temporary secret management:

```bash
az role assignment create \
  --assignee-object-id "$ME_OBJECT_ID" \
  --assignee-principal-type User \
  --role "Key Vault Secrets Officer" \
  --scope "$KV_ID"
```

---

# Enter SMTP Credentials Securely

Read values interactively:

```bash
read -rp "SMTP username: " SMTP_USERNAME

read -rp "SMTP From address: " SMTP_FROM_ADDRESS

read -rsp "SMTP App Password: " SMTP_APP_PASSWORD
echo
```

Store them:

```bash
az keyvault secret set \
  --vault-name "$KEY_VAULT_NAME" \
  --name "smtp-username" \
  --value "$SMTP_USERNAME" \
  --output none

az keyvault secret set \
  --vault-name "$KEY_VAULT_NAME" \
  --name "smtp-from-address" \
  --value "$SMTP_FROM_ADDRESS" \
  --output none

az keyvault secret set \
  --vault-name "$KEY_VAULT_NAME" \
  --name "smtp-app-password" \
  --value "$SMTP_APP_PASSWORD" \
  --output none
```

Clear local variables immediately:

```bash
unset SMTP_USERNAME
unset SMTP_FROM_ADDRESS
unset SMTP_APP_PASSWORD
```

Verify only the secret names:

```bash
az keyvault secret list \
  --vault-name "$KEY_VAULT_NAME" \
  --query "[].{
      Name:name,
      Enabled:attributes.enabled
  }" \
  -o table
```

Never print secret values during verification.

---

# Remove Temporary Key Vault Access

After the secrets are created:

```bash
az role assignment delete \
  --assignee-object-id "$ME_OBJECT_ID" \
  --role "Key Vault Secrets Officer" \
  --scope "$KV_ID"
```

The Function Managed Identity should retain:

```text
Key Vault Secrets User
```

---

# Verify Managed Identity Key Vault Access

```bash
az role assignment list \
  --assignee-object-id "$MI_PRINCIPAL_ID" \
  --scope "$KV_ID" \
  --query "[].{
      Role:roleDefinitionName,
      Scope:scope
  }" \
  -o table
```

Expected:

```text
Key Vault Secrets User
```

---

# Function Reporting Settings

Get the Key Vault URL:

```bash
KEY_VAULT_URL="$(
  az keyvault show \
    --resource-group "$RESOURCE_GROUP" \
    --name "$KEY_VAULT_NAME" \
    --query properties.vaultUri \
    -o tsv
)"
```

Configure the Function:

```bash
az functionapp config appsettings set \
  --resource-group "$RESOURCE_GROUP" \
  --name "$FUNCTION_APP_NAME" \
  --settings \
    "AZURE_CLIENT_ID=$MI_CLIENT_ID" \
    "REPORT_STORAGE_ACCOUNT=$REPORT_STORAGE_ACCOUNT" \
    "REPORT_CONTAINER=$REPORT_CONTAINER" \
    "KEY_VAULT_URL=$KEY_VAULT_URL" \
    "SMTP_HOST=smtp.gmail.com" \
    "SMTP_PORT=587" \
    "SMTP_USERNAME_SECRET_NAME=smtp-username" \
    "SMTP_FROM_ADDRESS_SECRET_NAME=smtp-from-address" \
    "SMTP_PASSWORD_SECRET_NAME=smtp-app-password" \
    "REPORT_SUBJECT_PREFIX=Azure Invoice Expense Report" \
    "BILLING_API_VERSION=2024-04-01" \
    "SUBSCRIPTIONS_API_VERSION=2022-12-01" \
  --output none
```

No SMTP credential value appears in Function App settings.

---

# Set the Report Recipient

Enter the recipient interactively:

```bash
read -rp "Report recipient: " REPORT_RECIPIENT
```

Configure:

```bash
az functionapp config appsettings set \
  --resource-group "$RESOURCE_GROUP" \
  --name "$FUNCTION_APP_NAME" \
  --settings \
    "REPORT_RECIPIENTS=$REPORT_RECIPIENT" \
  --output none
```

Clear:

```bash
unset REPORT_RECIPIENT
```

Changing `REPORT_RECIPIENTS` does not require a Function code deployment.

Multiple recipients can be comma-separated.

---

# Python Dependencies

Production dependencies are defined in:

```text
function_app/requirements.txt
```

The application uses Azure SDK packages for:

```text
Azure Functions
Managed Identity authentication
Blob Storage
Key Vault Secrets
```

SMTP itself uses Python's standard library.

---

# Validate the Function

From the repository root:

```bash
python -m py_compile \
  function_app/function_app.py \
  function_app/reporting.py
```

No output normally means compilation succeeded.

---

# Package the Function

```bash
cd function_app

rm -f /tmp/azure-cost-reporting-function.zip

zip -j /tmp/azure-cost-reporting-function.zip \
  function_app.py \
  reporting.py \
  host.json \
  requirements.txt

cd ..
```

Verify the ZIP:

```bash
unzip -l /tmp/azure-cost-reporting-function.zip
```

The root must contain:

```text
function_app.py
reporting.py
host.json
requirements.txt
```

---

# Deploy Function Code

Use remote Python build:

```bash
az functionapp deployment source config-zip \
  --resource-group "$RESOURCE_GROUP" \
  --name "$FUNCTION_APP_NAME" \
  --src /tmp/azure-cost-reporting-function.zip \
  --build-remote true
```

Verify Function discovery:

```bash
az functionapp function list \
  --resource-group "$RESOURCE_GROUP" \
  --name "$FUNCTION_APP_NAME" \
  --query "[].{
      Name:name,
      Language:language
  }" \
  -o table
```

Expected:

```text
monthly_invoice_report
```

---

# Reporting Period

By default, the Function calculates the previous calendar month.

For example:

```text
Run date: 5 September
Report:   August
```

A manual override is available for controlled testing and historical reruns:

```text
REPORT_MONTH_OVERRIDE=YYYY-MM
```

---

# Manual Historical Test

Set a test month:

```bash
az functionapp config appsettings set \
  --resource-group "$RESOURCE_GROUP" \
  --name "$FUNCTION_APP_NAME" \
  --settings \
    "REPORT_MONTH_OVERRIDE=2026-07" \
    "EMAIL_ENABLED=false" \
  --output none
```

---

# Manually Invoke the Timer Function

Get the Function hostname:

```bash
HOST_NAME="$(
  az functionapp show \
    --resource-group "$RESOURCE_GROUP" \
    --name "$FUNCTION_APP_NAME" \
    --query properties.defaultHostName \
    -o tsv
)"
```

Get the master key:

```bash
MASTER_KEY="$(
  az functionapp keys list \
    --resource-group "$RESOURCE_GROUP" \
    --name "$FUNCTION_APP_NAME" \
    --query masterKey \
    -o tsv
)"
```

Invoke:

```bash
HTTP_CODE="$(
  curl -sS \
    -o /tmp/monthly-report-response.txt \
    -w "%{http_code}" \
    -X POST \
    "https://${HOST_NAME}/admin/functions/monthly_invoice_report" \
    -H "x-functions-key: ${MASTER_KEY}" \
    -H "Content-Type: application/json" \
    -d '{}'
)"

unset MASTER_KEY

echo "HTTP status: $HTTP_CODE"
```

A successfully accepted invocation normally returns:

```text
202
```

---

# Verify Monthly Blob Output

Example:

```bash
az storage blob list \
  --account-name "$REPORT_STORAGE_ACCOUNT" \
  --container-name "$REPORT_CONTAINER" \
  --prefix "2026/07/" \
  --auth-mode login \
  --query "[].{
      Name:name,
      Size:properties.contentLength,
      Modified:properties.lastModified
  }" \
  -o table
```

Expected:

```text
2026/07/Azure-Expenses-2026-07.csv
2026/07/Azure-Invoice-Detail-2026-07.csv
2026/07/manifest.json
```

---

# Manifest

The manifest contains operational validation data such as:

```text
report_month
report_start
report_end
generated_utc
subscriptions_queried
invoice_count
total_amount
currency
reconciliation_difference
summary_blob
detail_blob
```

The reconciliation should be:

```text
0.00
```

A non-zero reconciliation difference should be investigated before treating the report as valid.

---

# Enable Email Delivery

After report generation is validated:

```bash
az functionapp config appsettings set \
  --resource-group "$RESOURCE_GROUP" \
  --name "$FUNCTION_APP_NAME" \
  --settings \
    "EMAIL_ENABLED=true" \
  --output none
```

The email contains the two CSV reports.

---

# Production Monthly Schedule

Recommended schedule:

```text
0 0 13 5 * *
```

Meaning:

```text
13:00 UTC
on the 5th day of each month
```

Configure:

```bash
az functionapp config appsettings set \
  --resource-group "$RESOURCE_GROUP" \
  --name "$FUNCTION_APP_NAME" \
  --settings \
    "MONTHLY_REPORT_SCHEDULE=0 0 13 5 * *" \
    "EMAIL_ENABLED=true" \
  --output none
```

The scheduled execution automatically reports the previous calendar month.

Examples:

```text
5 September -> August report
5 October   -> September report
5 November  -> October report
```

---

# Remove the Test Override

Production should not retain `REPORT_MONTH_OVERRIDE`.

Remove it:

```bash
az functionapp config appsettings delete \
  --resource-group "$RESOURCE_GROUP" \
  --name "$FUNCTION_APP_NAME" \
  --setting-names REPORT_MONTH_OVERRIDE \
  --output none
```

---

# Verify Production Settings

```bash
az functionapp config appsettings list \
  --resource-group "$RESOURCE_GROUP" \
  --name "$FUNCTION_APP_NAME" \
  --query "[?name=='MONTHLY_REPORT_SCHEDULE' || name=='EMAIL_ENABLED' || name=='REPORT_MONTH_OVERRIDE'].{
      Name:name,
      Value:value
  }" \
  -o table
```

Expected:

```text
EMAIL_ENABLED            true
MONTHLY_REPORT_SCHEDULE  0 0 13 5 * *
```

`REPORT_MONTH_OVERRIDE` should not appear.

---

# Changing the Client Recipient

Change only the setting:

```bash
read -rp "New report recipient: " REPORT_RECIPIENT
```

Then:

```bash
az functionapp config appsettings set \
  --resource-group "$RESOURCE_GROUP" \
  --name "$FUNCTION_APP_NAME" \
  --settings \
    "REPORT_RECIPIENTS=$REPORT_RECIPIENT" \
  --output none

unset REPORT_RECIPIENT
```

No code change or redeployment is required.

---

# Rotating the Google App Password

Temporarily grant an authorized operator:

```text
Key Vault Secrets Officer
```

Update:

```text
smtp-app-password
```

Then remove the temporary operator role again.

The Function will retrieve the latest secret value on a future execution.

---

# Important Function Settings

```text
AZURE_CLIENT_ID

AzureWebJobsStorage__accountName
AzureWebJobsStorage__credential
AzureWebJobsStorage__clientId

REPORT_STORAGE_ACCOUNT
REPORT_CONTAINER
REPORT_RECIPIENTS
REPORT_SUBJECT_PREFIX

EMAIL_ENABLED
MONTHLY_REPORT_SCHEDULE

KEY_VAULT_URL

SMTP_HOST
SMTP_PORT
SMTP_USERNAME_SECRET_NAME
SMTP_FROM_ADDRESS_SECRET_NAME
SMTP_PASSWORD_SECRET_NAME

BILLING_API_VERSION
SUBSCRIPTIONS_API_VERSION
```

Manual/testing only:

```text
REPORT_MONTH_OVERRIDE
```

---

# Security Design

The Function does not store:

```text
Azure passwords
Azure client secrets
Storage account keys
SMTP passwords
Google App Passwords
```

Azure authentication uses Managed Identity.

SMTP credentials are stored in Key Vault.

The SMTP password is retrieved only at runtime.

---

# Troubleshooting

## Function Missing

```bash
az functionapp function list \
  --resource-group "$RESOURCE_GROUP" \
  --name "$FUNCTION_APP_NAME" \
  -o table
```

## Runtime

```bash
az functionapp show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$FUNCTION_APP_NAME" \
  --query properties.functionAppConfig.runtime \
  -o json
```

## Key Vault

```bash
az role assignment list \
  --assignee-object-id "$MI_PRINCIPAL_ID" \
  --scope "$KV_ID" \
  -o table
```

## Report Storage

```bash
az storage blob list \
  --account-name "$REPORT_STORAGE_ACCOUNT" \
  --container-name "$REPORT_CONTAINER" \
  --auth-mode login \
  -o table
```

## SMTP

Verify:

```text
KEY_VAULT_URL
SMTP_HOST
SMTP_PORT
SMTP secret names
Google App Password
SMTP From address
REPORT_RECIPIENTS
EMAIL_ENABLED
```

Use Function/Application Insights logs for runtime failures.

---

# Production Operation

Normal monthly operation is:

```text
Timer trigger
    |
    v
Previous calendar month
    |
    v
Discover enabled subscriptions
    |
    v
Retrieve paid invoices
    |
    v
Generate summary + detail
    |
    v
Reconcile totals
    |
    v
Archive CSVs + manifest in Blob Storage
    |
    v
Retrieve SMTP secrets from Key Vault
    |
    v
Email both CSV files
```

No manual intervention should normally be required.

---

# Related Documentation

For historical Cost Management exports, invoice scripts, backfills, and manual reporting:

[Cost Export & Historical Reporting](../scripts/README.md)

For the complete project overview:

[Project README](../README.md)
