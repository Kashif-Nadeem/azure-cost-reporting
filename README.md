# Azure Cost Reporting & Automation

Reusable automation for exporting, processing, and reporting historical and recurring Microsoft Azure costs across multiple subscriptions.

The project uses the Azure Cost Management REST API and Azure Blob Storage to build a centralized cost-reporting workflow without embedding subscription IDs, customer names, credentials, storage keys, or other environment-specific information in source control.

## Current Capabilities

- Discovers enabled Azure subscriptions dynamically from Azure Resource Manager
- Filters subscriptions where Cost Management export access is unavailable
- Uses reusable subscription-level Cost Management export definitions
- Executes historical Usage exports one calendar month at a time
- Processes subscriptions month-first for complete monthly datasets
- Stores raw Cost Management CSV data directly in Azure Blob Storage
- Uses Blob manifests as the primary completion signal
- Supports resumable historical backfills
- Handles inaccessible subscriptions without stopping the entire workflow
- Includes optional troubleshooting utilities for downloading and inspecting exports
- Uses Microsoft Entra authentication instead of embedding storage account keys

## Historical Backfill

The historical workflow is implemented in:

    scripts/export-history.sh

By default, the historical backfill begins in January 2024 and continues through the current month.

The workflow:

1. Verifies Azure authentication.
2. Discovers enabled subscriptions directly from Azure Resource Manager.
3. Checks Cost Management export access.
4. Excludes subscriptions where the executing identity is unauthorized.
5. Creates or reuses one Cost Management export definition per eligible subscription.
6. Executes one month across all eligible subscriptions.
7. Monitors Azure Blob Storage for completed export manifests.
8. Uses Cost Management run history only for unresolved executions.
9. Continues to the next month after the current month is resolved.
10. Skips completed data when the workflow is restarted.

Raw Cost Management CSV files remain in Azure Blob Storage unless the download utility is explicitly used.

## Authentication

For interactive development and administration, authenticate with Azure CLI:

    az login

The scripts use the authenticated Azure identity and do not require credentials to be stored in the repository.

For future unattended Azure-hosted automation, Managed Identity should be used where practical.

## Azure Permissions

The executing identity requires access to the Azure subscriptions being reported.

Typical permissions include:

- Cost Management Contributor, or equivalent Cost Management export permissions
- Reader access required to discover subscription metadata
- Appropriate Azure Blob Storage data access for report processing and troubleshooting
- Permission to create and execute Cost Management exports

Subscriptions where Cost Management access is unavailable are skipped and should not be interpreted as having zero cost.

## Local Configuration

Copy the example configuration:

    cp config/config.example.sh config/config.sh

Edit the local file with the required environment-specific settings.

The following file is intentionally excluded from Git:

    config/config.sh

Environment-specific configuration must never be committed to source control.

## Repository Structure

    azure-cost-reporting/
    ├── README.md
    ├── requirements.txt
    ├── config/
    │   └── config.example.sh
    ├── scripts/
    │   ├── common.sh
    │   ├── create-reusable-export.sh
    │   ├── run-reusable-export.sh
    │   ├── export-history.sh
    │   ├── export-subscription-month.sh
    │   ├── run-export.sh
    │   ├── check-export.sh
    │   ├── download-export.sh
    │   └── inspect-export.py
    └── tests/
        ├── test-subscription-export.sh
        └── test-reusable-export.sh

Local runtime directories such as the following are intentionally excluded from Git:

    downloads/
    logs/
    output/

## Raw Data Architecture

Azure Blob Storage acts as the source-of-truth location for raw Cost Management exports.

The historical exporter does not download raw data locally.

A typical flow is:

    Azure subscriptions
            |
            v
    Cost Management Usage exports
            |
            v
    Azure Blob Storage
            |
            v
    Python reporting workflow
            |
            +--> Monthly reports
            +--> Yearly reports
            +--> Year-to-date reports
            +--> Multi-year summaries

Raw Azure Cost Management exports remain unchanged so reports can be regenerated later without repeating the historical Cost Management backfill.

## Reporting Roadmap

The reporting phase will read Cost Management exports directly from Azure Blob Storage and create polished local deliverables.

Planned reports include:

- Monthly subscription cost reports
- Yearly subscription cost reports
- Year-to-date reports
- Multi-year executive summaries
- CSV deliverables
- Excel workbooks
- Automated monthly email delivery

Generated reports may contain actual subscription names because they are business deliverables, but the output directory is excluded from source control.

## Troubleshooting

A raw monthly export can be downloaded explicitly when troubleshooting is required:

    scripts/download-export.sh

Downloaded files are stored under the Git-ignored downloads directory.

CSV exports can be inspected with:

    scripts/inspect-export.py

These utilities are not used by the normal historical backfill.

## Security

The repository is designed so Git contains no customer-specific Azure configuration.

Never commit:

- Subscription IDs
- Tenant IDs
- Billing account or billing profile IDs
- Customer or organization names
- Storage account names
- Resource group names
- Email addresses
- Access tokens
- Client secrets
- Storage account keys
- SAS tokens
- Connection strings
- Raw cost exports
- Generated customer reports
- Local logs
- Local configuration files

Environment-specific non-secret configuration belongs in ignored local configuration files.

Credentials and other true secrets should use secure authentication mechanisms or an appropriate secret store such as Azure Key Vault.

## API

The automation currently uses the Azure Cost Management REST API version:

    2025-03-01

Historical exports use subscription-level Usage data and custom monthly time periods.

## Project Status

Historical export and backfill automation is implemented and validated.

Report generation, yearly aggregation, and automated monthly email delivery are the next development phases.
