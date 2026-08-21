#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote, urlencode


ARM_BASE = "https://management.azure.com"
BILLING_API_VERSION = "2024-04-01"
SUBSCRIPTIONS_API_VERSION = "2022-12-01"

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_FILE = REPO_ROOT / "output" / "state" / "subscription-registry.json"

MONTH_NAMES = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)

INVOICE_TYPE_LABELS = {
    "AzureServices": "Azure services",
    "AzureMarketplace": "Azure Marketplace and Reservations",
    "AzureSupport": "Azure Support Plan",
}


def az_get(url: str) -> dict:
    result = subprocess.run(
        [
            "az",
            "rest",
            "--method",
            "get",
            "--url",
            url,
            "--output",
            "json",
            "--only-show-errors",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(message or "Azure REST request failed")

    return json.loads(result.stdout)


def paged_get(url: str):
    seen = set()

    while url:
        if url in seen:
            raise RuntimeError("Repeated Azure nextLink detected")

        seen.add(url)

        payload = az_get(url)

        for item in payload.get("value", []):
            yield item

        url = payload.get("nextLink")


def discover_subscriptions() -> list[dict]:
    url = (
        f"{ARM_BASE}/subscriptions"
        f"?api-version={SUBSCRIPTIONS_API_VERSION}"
    )

    subscriptions = {}

    for item in paged_get(url):
        subscription_id = item.get("subscriptionId")

        if not subscription_id:
            continue

        subscriptions[subscription_id.lower()] = {
            "subscription_id": subscription_id.lower(),
            "current_name": (
                item.get("displayName")
                or subscription_id
            ),
            "state": item.get("state", ""),
        }

    # Merge the persistent registry so subscriptions previously
    # discovered by Billing remain reportable after deletion.
    if REGISTRY_FILE.exists():
        try:
            with REGISTRY_FILE.open(encoding="utf-8") as handle:
                registry = json.load(handle)

            for subscription_id, record in (
                registry.get("subscriptions", {}).items()
            ):
                sid = subscription_id.lower()

                if sid in subscriptions:
                    continue

                subscriptions[sid] = {
                    "subscription_id": sid,
                    "current_name": (
                        record.get("currentName")
                        or record.get("billingName")
                        or sid
                    ),
                    "state": (
                        record.get("armState")
                        or record.get("billingStatus")
                        or "Historical"
                    ),
                }

        except Exception as exc:
            print(
                f"WARNING: subscription registry "
                f"could not be loaded: {exc}"
            )

    return sorted(
        subscriptions.values(),
        key=lambda item: item["current_name"].casefold(),
    )


def invoice_window(year: int) -> tuple[str, str]:
    today = date.today()

    if year > today.year:
        raise RuntimeError("Cannot report a future year")

    # Invoice API date parameters relate to billing period,
    # not invoice date. Look back six months so January
    # invoices covering prior-year usage are included.
    start_date = f"{year - 1}-07-01"

    if year == today.year:
        end_date = today.isoformat()
    else:
        end_date = f"{year}-12-31"

    return start_date, end_date


def subscription_invoice_url(
    subscription_id: str,
    year: int,
) -> str:

    start_date, end_date = invoice_window(year)

    sid = quote(subscription_id, safe="-")

    params = urlencode(
        {
            "api-version": BILLING_API_VERSION,
            "periodStartDate": start_date,
            "periodEndDate": end_date,
            "top": 50,
        }
    )

    return (
        f"{ARM_BASE}/providers/Microsoft.Billing/"
        f"billingAccounts/default/"
        f"billingSubscriptions/{sid}/invoices"
        f"?{params}"
    )


def invoice_amount(properties: dict) -> tuple[Decimal, str]:
    amount = properties.get("totalAmount")

    if not amount or amount.get("value") is None:
        amount = properties.get("billedAmount")

    if not amount or amount.get("value") is None:
        raise RuntimeError(
            "Invoice does not contain totalAmount or billedAmount"
        )

    return (
        Decimal(str(amount["value"])),
        amount.get("currency") or "",
    )


def invoice_type_label(value: str) -> str:
    return INVOICE_TYPE_LABELS.get(
        value,
        value or "Other",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build Azure financial reports from paid "
            "subscription invoices."
        )
    )

    parser.add_argument("year", type=int)

    args = parser.parse_args()
    year = args.year

    today = date.today()

    through_month = (
        today.month
        if year == today.year
        else 12
    )

    print("Discovering current and historical subscriptions...")

    subscriptions = discover_subscriptions()

    print(
        f"Subscriptions discovered: {len(subscriptions)}"
    )

    # Key:
    # historical invoice name,
    # subscription ID,
    # invoice type,
    # currency
    totals = defaultdict(
        lambda: [Decimal("0") for _ in range(12)]
    )

    invoice_counts = defaultdict(int)

    seen_invoices = set()

    included = 0
    duplicates = 0
    unavailable = []

    for index, subscription in enumerate(
        subscriptions,
        start=1,
    ):
        sid = subscription["subscription_id"]
        current_name = subscription["current_name"]

        print(
            f"  [{index}/{len(subscriptions)}] "
            f"{current_name} ... ",
            end="",
            flush=True,
        )

        try:
            invoices = list(
                paged_get(
                    subscription_invoice_url(
                        sid,
                        year,
                    )
                )
            )
        except Exception as exc:
            unavailable.append(
                (
                    current_name,
                    sid,
                    str(exc),
                )
            )

            print("invoice API unavailable")
            continue

        matched = 0

        for invoice in invoices:
            properties = invoice.get("properties", {})

            if properties.get("status") != "Paid":
                continue

            invoice_date = (
                properties.get("invoiceDate")
                or ""
            )

            # Financial report year is determined by
            # invoice date, not usage/billing period.
            if not invoice_date.startswith(f"{year:04d}-"):
                continue

            try:
                month = int(invoice_date[5:7])
            except (ValueError, IndexError):
                continue

            invoice_id = (
                invoice.get("name")
                or invoice.get("id")
                or (
                    f"{sid}:{invoice_date}:"
                    f"{properties.get('invoiceType', '')}"
                )
            )

            dedupe_key = (sid, invoice_id)

            if dedupe_key in seen_invoices:
                duplicates += 1
                continue

            seen_invoices.add(dedupe_key)

            try:
                amount, currency = invoice_amount(
                    properties
                )
            except RuntimeError:
                continue

            # IMPORTANT:
            # Use the name that existed on the invoice,
            # not today's ARM subscription display name.
            invoice_name = (
                properties.get("subscriptionDisplayName")
                or current_name
            )

            invoice_type = invoice_type_label(
                properties.get("invoiceType", "")
            )

            key = (
                invoice_name,
                sid,
                invoice_type,
                currency,
            )

            totals[key][month - 1] += amount
            invoice_counts[key] += 1

            included += 1
            matched += 1

        print(f"{matched} paid invoice(s)")

    output_dir = (
        REPO_ROOT
        / "output"
        / "invoices"
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    if year == today.year and through_month < 12:
        filename = (
            f"Azure-Invoice-Report-{year}-YTD.csv"
        )
    else:
        filename = (
            f"Azure-Invoice-Report-{year}.csv"
        )

    output_file = output_dir / filename

    overall_months = defaultdict(
        lambda: [Decimal("0") for _ in range(12)]
    )

    overall_year = defaultdict(
        lambda: Decimal("0")
    )

    overall_invoice_count = defaultdict(int)

    ordered_keys = sorted(
        totals,
        key=lambda key: (
            key[0].casefold(),
            key[2].casefold(),
            key[3],
        ),
    )

    with output_file.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as handle:

        writer = csv.writer(handle)

        writer.writerow(
            [
                "Subscription",
                "Subscription ID",
                "Type",
                "Currency",
                *MONTH_NAMES,
                "Year Total",
                "Invoice Count",
            ]
        )

        for key in ordered_keys:
            (
                invoice_name,
                sid,
                invoice_type,
                currency,
            ) = key

            monthly = totals[key]

            year_total = sum(
                monthly,
                Decimal("0"),
            )

            month_columns = []

            for month_number, value in enumerate(
                monthly,
                start=1,
            ):
                if month_number > through_month:
                    month_columns.append("")
                else:
                    month_columns.append(
                        f"{value:.2f}"
                    )

                overall_months[
                    currency
                ][month_number - 1] += value

            overall_year[currency] += year_total

            overall_invoice_count[
                currency
            ] += invoice_counts[key]

            writer.writerow(
                [
                    invoice_name,
                    sid,
                    invoice_type,
                    currency,
                    *month_columns,
                    f"{year_total:.2f}",
                    invoice_counts[key],
                ]
            )

        writer.writerow([])

        for currency in sorted(overall_year):
            month_columns = []

            for month_number, value in enumerate(
                overall_months[currency],
                start=1,
            ):
                if month_number > through_month:
                    month_columns.append("")
                else:
                    month_columns.append(
                        f"{value:.2f}"
                    )

            writer.writerow(
                [
                    "TOTAL",
                    "",
                    "",
                    currency,
                    *month_columns,
                    f"{overall_year[currency]:.2f}",
                    overall_invoice_count[currency],
                ]
            )

    exceptions_file = (
        output_dir
        / f"Azure-Invoice-Access-Exceptions-{year}.csv"
    )

    with exceptions_file.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        writer = csv.writer(handle)

        writer.writerow(
            [
                "Year",
                "Subscription",
                "Subscription ID",
                "Status",
                "Error",
            ]
        )

        for name, subscription_id, message in unavailable:
            status = (
                "Invoice access denied"
                if "Forbidden" in message
                else "Invoice API unavailable"
            )

            writer.writerow(
                [
                    year,
                    name,
                    subscription_id,
                    status,
                    message.splitlines()[0][:500],
                ]
            )

    print()
    print("Invoice report created")
    print("----------------------")
    print(f"File                  : {output_file}")
    print(f"Report year           : {year}")
    print(f"Through month         : {through_month}")
    print(f"Subscriptions queried : {len(subscriptions)}")
    print(f"Paid invoices included: {included}")
    print(f"Duplicates ignored    : {duplicates}")
    print(f"Invoice API unavailable: {len(unavailable)}")

    for currency in sorted(overall_year):
        print(
            f"Total {currency:<12}: "
            f"{overall_year[currency]:.2f}"
        )

    if unavailable:
        print()
        print("Invoice API unavailable for")
        print("---------------------------")

        for name, _, message in unavailable:
            first_line = message.splitlines()[0]
            print(
                f"{name}: {first_line[:160]}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
