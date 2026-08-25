# Azure Cost Reporting & Automation

Reusable Azure reporting automation for multi-subscription environments.

This repository contains two related but separate workflows:

1. **Cost Export & Historical Reporting**
   Scripts for Azure Cost Management exports, historical backfills, invoice retrieval, yearly reporting, subscription tracking, and financial analysis.

2. **Automated Monthly Invoice Reporting**
   An Azure Functions solution that generates the previous month's invoice report, archives it in Azure Blob Storage, and emails the report automatically.

The repository is intentionally environment-neutral. Customer-specific subscription IDs, tenant IDs, email addresses, Azure resource names, generated reports, and credentials must not be committed.

---

## Project Components

### Part 1 - Cost Export & Historical Reporting

Located under:

```text
scripts/
```

This component supports:

- Azure Cost Management Usage exports
- historical monthly backfills
- dynamic subscription discovery
- monthly and yearly cost reports
- Azure Billing invoice reporting
- invoice-detail exports
- subscription registry maintenance
- invoice access-exception reporting
- year-to-date reporting
- multi-year financial summaries

Detailed instructions:

[Cost Export & Historical Reporting Guide](scripts/README.md)

---

### Part 2 - Automated Monthly Invoice Reporting

Located under:

```text
function_app/
```

This component provides the production automation.

It uses:

- Azure Functions Flex Consumption
- Python 3.14
- user-assigned Managed Identity
- Azure Billing Invoice API
- Azure Blob Storage
- Azure Key Vault
- SMTP with STARTTLS
- timer-triggered monthly execution

Each successful month generates:

```text
YYYY/MM/
    Azure-Expenses-YYYY-MM.csv
    Azure-Invoice-Detail-YYYY-MM.csv
    manifest.json
```

The two CSV reports are emailed to the configured recipients.

Detailed instructions:

[Automated Monthly Invoice Reporting Guide](function_app/README.md)

---

## Infrastructure as Code

Reusable Azure infrastructure is stored under:

```text
infra/
```

Current templates include:

```text
infra/
├── main.bicep
├── key-vault.bicep
├── management-group-roles.bicep
├── main.bicepparam.example
└── deploy.example.sh
```

The infrastructure covers:

- Azure Functions Flex Consumption
- Function runtime storage
- report Blob container
- user-assigned Managed Identity
- Application Insights
- Log Analytics
- Azure Key Vault
- Azure Storage RBAC
- Key Vault RBAC
- management-group reporting RBAC

The production deployment procedure is documented in:

[function_app/README.md](function_app/README.md)

---

## Reporting Data Sources

The project uses two Azure reporting sources because they serve different purposes.

### Cost Management Usage

Used for:

- resource-level analysis
- Azure consumption review
- subscription cost analysis
- operational reporting

Usage data should not automatically be treated as an accounting invoice total.

### Azure Billing Invoices

Used for:

- accounting-oriented reporting
- paid invoice totals
- invoice-date reporting
- Marketplace and reservation invoice activity
- monthly financial reporting

The automated monthly workflow uses Azure Billing invoice data.

---

## Repository Structure

```text
azure-cost-reporting/
├── README.md
├── requirements.txt
│
├── config/
│   └── config.example.sh
│
├── scripts/
│   ├── README.md
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
│   ├── export-invoice-details.py
│   ├── build-invoice-summary.py
│   └── build-all-invoice-reports.sh
│
├── function_app/
│   ├── README.md
│   ├── function_app.py
│   ├── reporting.py
│   ├── requirements.txt
│   ├── host.json
│   └── local.settings.example.json
│
├── infra/
│   ├── main.bicep
│   ├── key-vault.bicep
│   ├── management-group-roles.bicep
│   ├── main.bicepparam.example
│   └── deploy.example.sh
│
└── tests/
```

Runtime data is excluded from source control:

```text
.venv/
downloads/
logs/
output/
```

---

## Authentication

Interactive scripts normally use the authenticated Azure CLI identity:

```bash
az login
```

Production Azure Functions use:

```text
DefaultAzureCredential
+
User-assigned Managed Identity
```

No Azure client secret is required by the Function.

---

## APIs

Current API versions include:

```text
Azure Cost Management REST API: 2025-03-01
Azure Billing REST API:         2024-04-01
Azure Subscriptions REST API:   2022-12-01
```

Stable GA API versions should be preferred unless a required capability exists only in preview.

---

## Security

Never commit:

```text
Subscription IDs
Tenant IDs
Management Group IDs
Billing account IDs
Billing profile IDs

Customer names
Customer email addresses

Azure access tokens
Client secrets
Storage account keys
SAS tokens
Connection strings

SMTP usernames
SMTP passwords
Google App Passwords

Generated financial reports
Raw Cost Management exports
Subscription registry data
Logs

local.settings.json
config.sh
.env
Private keys
Private certificates
```

Use:

```text
Managed Identity
Microsoft Entra ID
Azure RBAC
Azure Key Vault
Ignored local configuration
```

where practical.

---

## Historical Reporting Limitation

Historical invoice results depend on information that Azure still exposes through current billing and subscription APIs.

Subscriptions deleted or expired in the past might no longer be queryable.

Known historical gaps should be documented rather than automatically interpreted as zero cost.

---

## Documentation

For manual exports, historical backfills, invoice scripts, and report-generation commands:

[Read scripts/README.md](scripts/README.md)

For Azure Function deployment, Key Vault, SMTP, Storage, scheduling, manual invocation, and monthly operations:

[Read function_app/README.md](function_app/README.md)

---

## Project Status

Implemented and validated:

- Historical Cost Management backfill
- Subscription-level Usage exports
- Monthly Cost Management reporting
- Yearly Cost Management reporting
- Invoice-based reporting
- Invoice-detail reporting
- Subscription discovery
- Subscription registry
- Access-exception reporting
- Year-to-date reporting
- Multi-year invoice summaries
- Azure Functions Flex Consumption
- Python 3.14 Function runtime
- User-assigned Managed Identity
- Azure Storage monthly archive
- Azure Key Vault
- SMTP / STARTTLS email delivery
- Monthly scheduled reporting
- Manual historical-month execution
- Bicep infrastructure deployment
- Management-group reporting RBAC

---

## License

Choose an appropriate open-source license before redistributing the project as an open-source package.
