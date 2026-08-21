# Azure Cost Reporting & Automation

Reusable automation for exporting, processing, and reporting Microsoft Azure costs across multiple subscriptions.

The project supports two complementary reporting paths:

1. Azure Cost Management Usage exports for detailed cost and resource analysis.
2. Azure Billing Invoice data for accounting and financial reporting.

The repository is designed to remain environment-neutral. Subscription IDs, customer names, credentials, billing identifiers, storage account names, generated reports, and other environment-specific data are not stored in source control.

## Current Capabilities

### Cost Management Reporting

- Discovers enabled Azure subscriptions dynamically from Azure Resource Manager.
- Checks Cost Management access before attempting exports.
- Creates and reuses subscription-level Usage export definitions.
- Executes historical exports one calendar month at a time.
- Processes all eligible subscriptions for a month before continuing.
- Stores raw Cost Management export data in Azure Blob Storage.
- Uses export manifests as the primary completion signal.
- Supports resumable historical backfills.
- Generates monthly and yearly cost reports.
- Includes utilities for inspecting and auditing exported cost data.

### Invoice Reporting

- Discovers current subscriptions dynamically from Azure Resource Manager.
- Uses Azure Billing Property information to identify the billing relationship.
- Discovers additional historical or deleted billing subscriptions when Azure exposes them.
- Maintains a persistent subscription registry so subscriptions can continue to be tracked after they disappear from ARM.
- Queries Azure Billing invoices for each discovered subscription.
- Includes only paid invoices in financial totals.
- Assigns costs by invoice date rather than usage period.
- Uses the invoice subscription display name while retaining the stable subscription ID.
- Separates Azure services, Marketplace/Reservations, and other invoice types where applicable.
- Produces yearly reports automatically from the configured start year through the current year.
- Marks the current year as year-to-date.
- Produces a multi-year subscription summary.
- Records invoice permission failures separately instead of treating inaccessible subscriptions as zero cost.

## Reporting Architecture

The two reporting paths serve different purposes.

### Cost Management Usage Path

    Azure subscriptions
            |
            v
    Cost Management Usage exports
            |
            v
    Azure Blob Storage
            |
            v
    Monthly / yearly usage reports

This path is intended for resource-level cost analysis, operational reporting, and detailed Azure consumption review.

### Billing Invoice Path

    Azure Resource Manager
            |
            v
    Current subscriptions
            |
            +----------------------+
            |                      |
            v                      v
    Billing Property        Subscription registry
            |                      |
            v                      |
    Billing account               |
            |                      |
            v                      |
    Historical/deleted -----------+
    subscriptions
            |
            v
    Billing Invoice API
            |
            v
    Yearly invoice reports
            |
            v
    Multi-year financial summary

This path is intended for accounting and invoice-based financial reporting.

## Historical Cost Management Backfill

Historical Cost Management exports are handled by:

    scripts/export-history.sh

By default, the workflow begins in January 2024 and continues through the current month.

The workflow:

1. Verifies Azure authentication.
2. Discovers enabled subscriptions from Azure Resource Manager.
3. Checks Cost Management export access.
4. Excludes subscriptions where export access is unavailable.
5. Creates or reuses a Cost Management Usage export definition.
6. Executes one calendar month across all eligible subscriptions.
7. Monitors Azure Blob Storage for completed manifests.
8. Uses Cost Management run history for unresolved executions.
9. Continues to the next month after the current month is resolved.
10. Skips already completed exports when restarted.

Raw Cost Management CSV files remain in Azure Blob Storage unless explicitly downloaded for troubleshooting.

## Invoice Report Workflow

The complete invoice reporting workflow is:

    scripts/build-all-invoice-reports.sh

Run:

    ./scripts/build-all-invoice-reports.sh

The workflow automatically:

1. Updates the subscription registry.
2. Discovers current ARM subscriptions.
3. Discovers historical/deleted billing subscriptions where available.
4. Queries invoices for all known subscription IDs.
5. Generates yearly invoice reports from the start year through the current year.
6. Generates a multi-year summary.
7. Creates internal access-exception reports for subscriptions whose invoices could not be read.

The default start year is 2024.

It can be overridden for a run:

    START_YEAR=2025 ./scripts/build-all-invoice-reports.sh

## Generated Invoice Reports

Generated files are written under:

    output/invoices/

Typical output:

    Azure-Invoice-Report-2024.csv
    Azure-Invoice-Report-2025.csv
    Azure-Invoice-Report-2026-YTD.csv
    Azure-Invoice-Summary-2024-2026.csv

The exact current-year filename changes automatically with the calendar year.

The multi-year report groups financial data using the stable Azure subscription ID so subscription renames do not split the same subscription into separate accounting entities.

Generated reports are business deliverables and are intentionally excluded from Git.

## Access Exception Reports

The invoice workflow also creates files such as:

    Azure-Invoice-Access-Exceptions-2024.csv

These are internal audit files, not financial statements.

An access exception means the subscription was discovered but Azure did not allow the executing identity to retrieve its invoices.

An inaccessible subscription is never interpreted as having zero cost.

Financial reports should therefore be considered complete only when any relevant invoice-access exceptions have been reviewed or resolved.

## Subscription Registry

The invoice workflow maintains:

    output/state/subscription-registry.json

The registry combines subscriptions currently visible through Azure Resource Manager with additional billing subscriptions discovered through Azure Billing.

Its purpose is to retain subscription IDs over time so a subscription already known to the automation remains available for reporting even if it is later deleted or removed from normal ARM enumeration.

The local registry is excluded from Git.

When Blob write access is available, the registry can also be persisted to Azure Blob Storage for unattended and durable automation.

## Authentication

For interactive development:

    az login

The scripts use the authenticated Azure identity and do not store Azure credentials in the repository.

For unattended Azure-hosted automation, Managed Identity should be used where practical.

## Azure Permissions

Required permissions depend on the reporting features being used.

### Subscription Discovery

The executing identity requires sufficient Azure Resource Manager access to enumerate the subscriptions being reported.

### Cost Management Exports

Typical requirements include:

- Cost Management export permissions at subscription scope.
- Permission to create and execute Cost Management exports.
- Appropriate Azure Blob Storage data permissions.

### Billing Invoice Reporting

The executing identity must have permission to view invoices for the subscriptions included in financial reporting.

If Azure returns `Forbidden`, the subscription is recorded as an access exception and its invoice amount is not included in the calculated financial total.

Billing access requirements vary by Azure billing agreement and account configuration.

### Blob Storage

For workflows that read and write reporting data or persist the subscription registry, the automation identity should have an appropriate Azure Storage data-plane role such as:

    Storage Blob Data Contributor

Storage account keys are not required when Microsoft Entra authentication is used.

## Local Configuration

Copy the example configuration:

    cp config/config.example.sh config/config.sh

Then edit:

    config/config.sh

The local configuration file is excluded from Git.

Environment-specific configuration must never be committed.

## Python Environment

Create a virtual environment:

    python3 -m venv .venv

Activate it:

    source .venv/bin/activate

Install dependencies:

    pip install -r requirements.txt

## Repository Structure

    azure-cost-reporting/
    ├── README.md
    ├── requirements.txt
    ├── config/
    │   └── config.example.sh
    ├── scripts/
    │   ├── common.sh
    │   ├── export-history.sh
    │   ├── export-subscription-month.sh
    │   ├── run-export.sh
    │   ├── check-export.sh
    │   ├── download-export.sh
    │   ├── inspect-export.py
    │   ├── audit-cost-structure.py
    │   ├── reporting_common.py
    │   ├── build-monthly-report.py
    │   ├── build-yearly-report.py
    │   ├── update-subscription-registry.py
    │   ├── build-invoice-report.py
    │   ├── build-invoice-summary.py
    │   └── build-all-invoice-reports.sh
    └── tests/

Runtime directories including the following are excluded from source control:

    .venv/
    downloads/
    logs/
    output/

## Cost Management Reporting

Cost Management reports are built from exported Usage data stored in Azure Blob Storage.

These reports are useful for detailed subscription and resource-level cost analysis but should not automatically be assumed to equal invoice accounting totals because Azure usage periods and invoice dates can differ.

## Invoice Reporting

Invoice reports use paid Azure Billing invoice records.

Financial totals are assigned to the year and month using the invoice date.

This reporting path is intended to reflect invoice/accounting activity rather than resource consumption timing.

For the current calendar year, only invoices available at the time the workflow runs are included. Therefore the current month may be incomplete until Azure issues the applicable invoices.

## Troubleshooting

Download a raw Cost Management export when required:

    scripts/download-export.sh

Inspect downloaded Cost Management CSV data:

    scripts/inspect-export.py

Audit exported cost structure:

    scripts/audit-cost-structure.py

Invoice API failures are written to the generated access-exception reports.

## Security

Git must not contain customer-specific Azure configuration or generated financial data.

Never commit:

- Subscription IDs
- Tenant IDs
- Billing account IDs
- Billing profile IDs
- Customer or organization names
- Storage account names
- Resource group names
- Email addresses
- Access tokens
- Client secrets
- Storage account keys
- SAS tokens
- Connection strings
- Raw Cost Management exports
- Generated financial reports
- Subscription registry data
- Local logs
- Local configuration files

Environment-specific non-secret configuration belongs in ignored local configuration.

Credentials and secrets should use Microsoft Entra authentication, Managed Identity, Azure Key Vault, or another appropriate secure mechanism.

## APIs

The automation currently uses:

    Azure Cost Management REST API: 2025-03-01
    Azure Billing REST API:         2024-04-01
    Azure Subscriptions REST API:   2022-12-01

## Project Status

Implemented and validated:

- Historical Cost Management backfill
- Subscription-level Usage exports
- Monthly cost reporting
- Yearly cost reporting
- Invoice-based financial reporting
- Current and historical subscription discovery
- Subscription registry
- Access-exception reporting
- Year-to-date invoice reporting
- Multi-year invoice summaries

Remaining operational work primarily consists of deployment-specific permissions, unattended scheduling, report delivery, and optional presentation enhancements such as Excel workbooks.
