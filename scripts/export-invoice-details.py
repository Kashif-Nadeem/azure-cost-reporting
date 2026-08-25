#!/usr/bin/env python3

import csv
import json
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode


BASE = "https://management.azure.com"
API_VERSION = "2024-04-01"

START_DATE = "07-01-2023"
END_DATE = datetime.now(timezone.utc).strftime("%m-%d-%Y")

OUTDIR = Path("output/invoices")
OUTDIR.mkdir(parents=True, exist_ok=True)

YEARS = {
    "2024": "Azure-Invoice-Detail-2024.csv",
    "2025": "Azure-Invoice-Detail-2025.csv",
    "2026": "Azure-Invoice-Detail-2026-YTD.csv",
}


def run_json(args):
    p = subprocess.run(
        args,
        capture_output=True,
        text=True,
    )

    if p.returncode != 0:
        return None, (p.stderr or p.stdout).strip()

    try:
        return json.loads(p.stdout), None
    except Exception as exc:
        return None, str(exc)


def get_url(url):
    return run_json([
        "az", "rest",
        "--method", "get",
        "--url", url,
        "-o", "json",
        "--only-show-errors",
    ])


def paged(url):
    rows = []

    while url:
        data, error = get_url(url)

        if error:
            return rows, error

        rows.extend(data.get("value", []))
        url = data.get("nextLink")

    return rows, None


def money(obj):
    if not isinstance(obj, dict):
        return None, ""

    value = obj.get("value")
    currency = obj.get("currency") or ""

    if value is None:
        return None, currency

    return Decimal(str(value)), currency


def date_only(value):
    if not value:
        return ""

    return str(value)[:10]


def invoice_type_name(value):
    return {
        "AzureServices": "Azure services",
        "AzureMarketplace":
            "Azure Marketplace and Reservations",
        "AzureSupport": "Azure Support Plan",
    }.get(value, value or "")


# ----------------------------------------------------------
# Current accessible subscriptions
# ----------------------------------------------------------

subs, error = run_json([
    "az", "account", "list",
    "--all",
    "--query",
    "[?state=='Enabled'].{Name:name,Id:id}",
    "-o", "json",
])

if error:
    raise SystemExit(error)

print(f"Enabled subscriptions : {len(subs)}")
print(f"Query period          : {START_DATE} -> {END_DATE}")
print()


records = defaultdict(list)
exceptions = []


for index, sub in enumerate(subs, 1):

    sid = sub["Id"]
    current_name = sub["Name"]

    params = urlencode({
        "api-version": API_VERSION,
        "periodStartDate": START_DATE,
        "periodEndDate": END_DATE,
        "top": 50,
    })

    url = (
        f"{BASE}/providers/Microsoft.Billing/"
        f"billingAccounts/default/"
        f"billingSubscriptions/{sid}/invoices?"
        f"{params}"
    )

    invoices, error = paged(url)

    if error:
        exceptions.append(
            (current_name, sid, error.splitlines()[0])
        )

        print(
            f"[{index:02}/{len(subs)}] "
            f"{current_name:<30} ERROR"
        )
        continue

    matched = 0

    for invoice in invoices:

        p = invoice.get("properties", {})

        if p.get("status") != "Paid":
            continue

        invoice_date = date_only(
            p.get("invoiceDate")
        )

        if len(invoice_date) < 4:
            continue

        year = invoice_date[:4]

        if year not in YEARS:
            continue

        # Original invoice amount:
        # prefer totalAmount when present,
        # otherwise use billedAmount.
        total_value, total_currency = money(
            p.get("totalAmount")
        )

        amount_source = "totalAmount"

        if total_value is None:
            total_value, total_currency = money(
                p.get("billedAmount")
            )
            amount_source = "billedAmount"

        if total_value is None:
            continue

        due_value, due_currency = money(
            p.get("amountDue")
        )

        billed_value, billed_currency = money(
            p.get("billedAmount")
        )

        sub_name = (
            p.get("subscriptionDisplayName")
            or current_name
        )

        sub_id = (
            p.get("subscriptionId")
            or sid
        )

        period_start = date_only(
            p.get("invoicePeriodStartDate")
        )

        period_end = date_only(
            p.get("invoicePeriodEndDate")
        )

        billing_period = ""

        if period_start or period_end:
            billing_period = (
                f"{period_start} to {period_end}"
            )

        records[year].append({
            "Invoice ID":
                invoice.get("name") or "",
            "Subscription":
                sub_name,
            "Subscription ID":
                sub_id,
            "Invoice Date":
                invoice_date,
            "Billing Period":
                billing_period,
            "Billing Period Start":
                period_start,
            "Billing Period End":
                period_end,
            "Amount Due Currency":
                due_currency,
            "Amount Due":
                (
                    f"{due_value:.2f}"
                    if due_value is not None
                    else ""
                ),
            "Billed Amount Currency":
                billed_currency,
            "Billed Amount":
                (
                    f"{billed_value:.2f}"
                    if billed_value is not None
                    else ""
                ),
            "Total Amount Currency":
                total_currency,
            "Total Amount":
                f"{total_value:.2f}",
            "Amount Source":
                amount_source,
            "Type":
                invoice_type_name(
                    p.get("invoiceType")
                ),
            "Status":
                p.get("status") or "",
            "Due Date":
                date_only(p.get("dueDate")),
        })

        matched += 1

    print(
        f"[{index:02}/{len(subs)}] "
        f"{current_name:<30} "
        f"{matched} paid invoice(s)"
    )


fields = [
    "Invoice ID",
    "Subscription",
    "Subscription ID",
    "Invoice Date",
    "Billing Period",
    "Billing Period Start",
    "Billing Period End",
    "Amount Due Currency",
    "Amount Due",
    "Billed Amount Currency",
    "Billed Amount",
    "Total Amount Currency",
    "Total Amount",
    "Amount Source",
    "Type",
    "Status",
    "Due Date",
]


print()
print("=" * 76)
print("INVOICE DETAIL RESULTS")
print("=" * 76)


period_count = 0
period_total = Decimal("0")


for year, filename in YEARS.items():

    rows = sorted(
        records[year],
        key=lambda r: (
            r["Invoice Date"],
            r["Subscription"],
            r["Invoice ID"],
        ),
    )

    path = OUTDIR / filename

    with path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:

        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
        )

        writer.writeheader()
        writer.writerows(rows)

    total = sum(
        (
            Decimal(r["Total Amount"])
            for r in rows
        ),
        Decimal("0"),
    )

    period_count += len(rows)
    period_total += total

    label = (
        f"{year} YTD"
        if year == "2026"
        else year
    )

    print(
        f"{label:<10} "
        f"invoices={len(rows):>4}  "
        f"total=${total:,.2f}"
    )

    print(f"           {path}")


print()
print(
    f"Period     invoices={period_count:>4}  "
    f"total=${period_total:,.2f}"
)

print()
print(
    f"Access exceptions: {len(exceptions)}"
)

for name, sid, error in exceptions:
    print(
        f"  {name} | {sid} | {error}"
    )
