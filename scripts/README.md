# Cost Export & Historical Reporting

This directory contains the manual and historical reporting tools for Azure Cost Management and Azure Billing invoice data.

It is the first major component of the repository.

The scripts are useful for:

- historical Azure cost backfills
- Cost Management Usage exports
- monthly and yearly reporting
- invoice-based financial reporting
- invoice-detail exports
- subscription discovery and tracking
- access-exception auditing
- troubleshooting Azure cost data

---

## Reporting Paths

Two reporting paths are available.

### Cost Management Usage

```text
Azure subscriptions
        |
        v
Cost Management Usage exports
        |
        v
Azure Blob Storage
        |
        v
Monthly / yearly cost analysis
```

Use this path for:

- resource-level cost analysis
- usage analysis
- subscription-level consumption
- operational cost review

### Azure Billing Invoices

```text
Azure Resource Manager
        |
        v
Subscription discovery
        |
        v
Azure Billing Invoice API
        |
        v
Paid invoices
        |
        v
Accounting / financial reports
```

Use this path when the financial result needs to follow Azure invoice activity rather than resource consumption timing.

---

## Prerequisites

Required tools:

```bash
az version
python3 --version
git --version
```

Authenticate:

```bash
az login
```

Confirm the active Azure account:

```bash
az account show \
  --query "{Subscription:name,SubscriptionId:id,Tenant:tenantId}" \
  -o table
```

---

## Local Configuration

Create the working configuration:

```bash
cp config/config.example.sh config/config.sh
```

Edit it:

```bash
nano config/config.sh
```

Load it:

```bash
source config/config.sh
```

The real configuration file is intentionally excluded from Git.

Do not commit environment-specific values.

---

## Python Environment

From the repository root:

```bash
python3 -m venv .venv
```

Activate:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

# Cost Management Historical Export

The main historical backfill entry point is:

```text
scripts/export-history.sh
```

Run:

```bash
./scripts/export-history.sh
```

The workflow:

1. authenticates to Azure,
2. discovers enabled subscriptions,
3. checks Cost Management export access,
4. creates or reuses Usage export definitions,
5. executes one calendar month across eligible subscriptions,
6. waits for Azure export manifests,
7. records unavailable or unauthorized subscriptions,
8. advances to the next month,
9. resumes completed work after restart.

The workflow is designed for large multi-subscription environments and can be restarted without intentionally repeating already completed exports.

---

## Export a Single Subscription Month

Use:

```text
scripts/export-subscription-month.sh
```

Example:

```bash
./scripts/export-subscription-month.sh \
  "<subscription-id>" \
  "2026-07"
```

Use environment-specific IDs only in the shell or local configuration.

Do not store real IDs in Git.

---

## Inspect Cost Management Export Data

Download export data when required:

```bash
./scripts/download-export.sh
```

Inspect downloaded CSV files:

```bash
python scripts/inspect-export.py
```

Audit cost structure:

```bash
python scripts/audit-cost-structure.py
```

Downloaded Azure data normally belongs under:

```text
downloads/
```

and must remain excluded from Git.

---

# Monthly Cost Report

Monthly report generation is handled by:

```text
scripts/build-monthly-report.py
```

Run according to the script's configured input/output environment.

Example pattern:

```bash
python scripts/build-monthly-report.py
```

Generated business reports belong under:

```text
output/
```

and should remain outside source control.

---

# Yearly Cost Report

Yearly reporting is handled by:

```text
scripts/build-yearly-report.py
```

Run:

```bash
python scripts/build-yearly-report.py
```

The yearly report aggregates monthly Cost Management data for financial and operational analysis.

Cost Management yearly totals should not automatically be assumed to equal invoice totals.

---

# Invoice-Based Reporting

Invoice reporting is the accounting-oriented reporting path.

The main workflow is:

```text
scripts/build-all-invoice-reports.sh
```

Run:

```bash
./scripts/build-all-invoice-reports.sh
```

The workflow:

1. updates the subscription registry,
2. discovers current ARM subscriptions,
3. discovers additional billing subscriptions when Azure exposes them,
4. queries Azure Billing invoices,
5. keeps paid invoices for financial totals,
6. generates yearly invoice reports,
7. generates multi-year summaries,
8. records access exceptions separately.

---

## Override the Starting Year

The default reporting history begins in 2024.

Override it:

```bash
START_YEAR=2025 \
  ./scripts/build-all-invoice-reports.sh
```

---

## Subscription Registry

The registry is maintained by:

```text
scripts/update-subscription-registry.py
```

It records subscription IDs known to the reporting process.

The purpose is to reduce dependence on subscription display names and retain known subscription identities over time.

The runtime registry normally belongs under:

```text
output/state/
```

and must not be committed.

---

## Generate an Invoice Report

Invoice report generation is handled by:

```text
scripts/build-invoice-report.py
```

The workflow retrieves invoice information and produces accounting-oriented financial reports.

Run as part of the complete invoice workflow unless troubleshooting or developing an individual stage.

---

## Export Invoice Detail

Detailed invoice export is handled by:

```text
scripts/export-invoice-details.py
```

This produces invoice-level evidence behind summarized financial reports.

Invoice detail can include:

```text
Subscription
Subscription ID
Invoice ID
Invoice Date
Billing Period
Invoice Type
Status
Currency
Total Amount
```

The exact fields depend on what Azure exposes for each billing relationship.

---

## Invoice Summary

Multi-year summaries are generated by:

```text
scripts/build-invoice-summary.py
```

The summary groups financial activity using stable subscription IDs so subscription renaming does not create a new accounting identity.

---

# Generated Invoice Files

Typical output:

```text
output/invoices/
    Azure-Invoice-Report-2024.csv
    Azure-Invoice-Report-2025.csv
    Azure-Invoice-Report-2026-YTD.csv
    Azure-Invoice-Summary-2024-2026.csv
```

Invoice-detail files can also be generated for individual years or year-to-date periods.

All generated financial reports must remain excluded from source control.

---

# Invoice Access Exceptions

Typical internal diagnostic file:

```text
Azure-Invoice-Access-Exceptions-YYYY.csv
```

An access exception means:

```text
Subscription was discovered
        |
        v
Invoice API was queried
        |
        v
Azure denied or could not provide invoice access
```

Do not interpret an inaccessible subscription as having zero cost.

Review access exceptions before declaring a historical financial report complete.

---

# Azure Permissions

Permissions vary depending on the reporting workflow.

Typical read permissions include:

```text
Billing Reader
Cost Management Reader
```

Storage workflows might require:

```text
Storage Blob Data Contributor
```

For production automation these roles can be inherited from a management-group scope where appropriate.

Always use the narrowest scope practical for the environment.

---

# Blob Storage

Historical Cost Management data can be retained in Azure Blob Storage.

Prefer Microsoft Entra authentication:

```bash
az storage blob list \
  --account-name "<storage-account>" \
  --container-name "<container>" \
  --auth-mode login \
  -o table
```

Storage account keys are not required when RBAC authentication is used.

---

# Troubleshooting Cost Management Exports

Check Azure authentication:

```bash
az account show -o table
```

List enabled subscriptions:

```bash
az account list \
  --all \
  --query "[?state=='Enabled'].{Name:name,Id:id}" \
  -o table
```

Inspect local logs:

```bash
find logs -maxdepth 2 -type f -print
```

Inspect downloaded data:

```bash
find downloads -maxdepth 4 -type f -print
```

These directories must remain ignored by Git.

---

# Troubleshooting Invoice Reporting

Common issues include:

```text
Forbidden
Unauthorized
Subscription not found
Historical subscription no longer exposed
Billing relationship no longer available
Invoice API returned no records
```

Do not automatically treat these conditions as zero financial activity.

Use access-exception reporting and historical documentation.

---

# Historical Subscription Limitation

Azure subscription names can change.

Subscription IDs are more stable and should be used as the reporting identity whenever possible.

However, deleted or expired historical subscriptions may disappear from:

```text
Azure Resource Manager
Azure CLI subscription enumeration
Current billing APIs
```

When Azure no longer exposes a historical subscription, the automation cannot guarantee recovery of its old invoice information.

Document known gaps.

---

# Security

Never commit:

```text
Raw Azure exports
Generated invoice reports
Subscription IDs
Tenant IDs
Billing account IDs
Customer names
Customer resource names
Email addresses
Access tokens
Storage keys
SAS tokens
Connection strings
Subscription registry data
config.sh
```

Runtime directories such as:

```text
downloads/
logs/
output/
.venv/
```

must remain ignored.

---

# Relationship to Monthly Automation

The scripts in this directory are primarily for:

```text
Historical reporting
Manual reporting
Backfills
Investigation
Financial reconciliation
Development
```

The unattended production monthly workflow is implemented under:

```text
function_app/
```

See:

[Automated Monthly Invoice Reporting](../function_app/README.md)

for Azure Functions, scheduling, Blob archiving, Key Vault, SMTP, and automatic monthly email delivery.
