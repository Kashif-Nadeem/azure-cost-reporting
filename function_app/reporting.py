import csv
import io
import json
import logging
import os
import smtplib
import ssl
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from email.message import EmailMessage
from urllib.parse import urlencode

import requests
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from azure.storage.blob import BlobServiceClient, ContentSettings


ARM_SCOPE = "https://management.azure.com/.default"
DEFAULT_BILLING_API_VERSION = "2024-04-01"
DEFAULT_SUBSCRIPTIONS_API_VERSION = "2022-12-01"

MONEY = Decimal("0.01")

_credential = None
_secret_client = None


def _env(name, default=None, required=False):
    value = os.getenv(name, default)

    if required and not value:
        raise RuntimeError(
            f"Required application setting is missing: {name}"
        )

    return value


def _credential_client():
    global _credential

    if _credential is None:
        client_id = os.getenv("AZURE_CLIENT_ID")

        _credential = DefaultAzureCredential(
            managed_identity_client_id=client_id or None
        )

    return _credential


def _secret_client_instance():
    global _secret_client

    if _secret_client is None:
        vault_url = _env("KEY_VAULT_URL", required=True)

        _secret_client = SecretClient(
            vault_url=vault_url,
            credential=_credential_client(),
        )

    return _secret_client


def _secret(name):
    secret = _secret_client_instance().get_secret(name)

    if secret.value is None:
        raise RuntimeError(
            f"Key Vault secret has no value: {name}"
        )

    return secret.value


def _token(scope):
    return _credential_client().get_token(scope).token


def _headers(scope):
    return {
        "Authorization": f"Bearer {_token(scope)}",
        "Accept": "application/json",
    }


def _request_json(url, method="GET", payload=None, scope=ARM_SCOPE):
    last_error = None

    for attempt in range(1, 6):
        response = requests.request(
            method,
            url,
            headers={
                **_headers(scope),
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=90,
        )

        if response.status_code < 400:
            if not response.content:
                return {}

            return response.json()

        if response.status_code == 429 or response.status_code >= 500:
            retry_after = response.headers.get("Retry-After")

            try:
                delay = int(retry_after)
            except (TypeError, ValueError):
                delay = min(2 ** attempt, 30)

            last_error = (
                f"HTTP {response.status_code}: "
                f"{response.text[:1000]}"
            )

            time.sleep(delay)
            continue

        raise RuntimeError(
            f"HTTP {response.status_code} calling {url}: "
            f"{response.text[:2000]}"
        )

    raise RuntimeError(
        f"Request failed after retries: {last_error}"
    )


def _paged(url):
    while url:
        data = _request_json(url)

        for item in data.get("value", []):
            yield item

        url = data.get("nextLink")


def _month_shift(first_day, offset):
    month_index = (
        first_day.year * 12
        + first_day.month
        - 1
        + offset
    )

    year = month_index // 12
    month = month_index % 12 + 1

    return date(year, month, 1)


def _report_period():
    override = os.getenv("REPORT_MONTH_OVERRIDE", "").strip()

    if override:
        try:
            year, month = map(int, override.split("-"))
            start = date(year, month, 1)
        except Exception as exc:
            raise RuntimeError(
                "REPORT_MONTH_OVERRIDE must use YYYY-MM format."
            ) from exc
    else:
        today = datetime.now(timezone.utc).date()
        start = _month_shift(today.replace(day=1), -1)

    next_month = _month_shift(start, 1)
    end = next_month - timedelta(days=1)

    return start, end


def _list_enabled_subscriptions():
    api_version = _env(
        "SUBSCRIPTIONS_API_VERSION",
        DEFAULT_SUBSCRIPTIONS_API_VERSION,
    )

    url = (
        "https://management.azure.com/subscriptions?"
        f"api-version={api_version}"
    )

    subscriptions = []

    for item in _paged(url):
        if str(item.get("state", "")).lower() != "enabled":
            continue

        subscription_id = item.get("subscriptionId")
        display_name = item.get("displayName") or ""

        if not subscription_id:
            continue

        subscriptions.append(
            {
                "id": subscription_id,
                "name": display_name,
            }
        )

    return subscriptions


def _amount(obj):
    if not isinstance(obj, dict):
        return None, ""

    value = obj.get("value")
    currency = obj.get("currency") or ""

    if value is None:
        return None, currency

    return Decimal(str(value)), currency


def _date_only(value):
    if not value:
        return ""

    return str(value)[:10]


def _invoice_type(value):
    mapping = {
        "AzureServices": "Azure services",
        "AzureMarketplace":
            "Azure Marketplace and Reservations",
        "AzureSupport": "Azure Support Plan",
    }

    return mapping.get(value, value or "")


def _invoice_query(subscription_id, report_start, report_end):
    api_version = _env(
        "BILLING_API_VERSION",
        DEFAULT_BILLING_API_VERSION,
    )

    # Use a look-back window because invoice date and billing
    # period are not always identical.
    query_start = _month_shift(report_start, -6)

    params = urlencode(
        {
            "api-version": api_version,
            "periodStartDate":
                query_start.strftime("%m-%d-%Y"),
            "periodEndDate":
                report_end.strftime("%m-%d-%Y"),
            "top": 50,
        }
    )

    return (
        "https://management.azure.com/"
        "providers/Microsoft.Billing/"
        "billingAccounts/default/"
        f"billingSubscriptions/{subscription_id}/"
        f"invoices?{params}"
    )


def _collect_invoices(subscriptions, report_start, report_end):
    report_month = report_start.strftime("%Y-%m")

    records = []
    errors = []
    seen = set()

    for index, subscription in enumerate(subscriptions, 1):
        sid = subscription["id"]
        current_name = subscription["name"]

        logging.info(
            "Querying subscription %s of %s.",
            index,
            len(subscriptions),
        )

        try:
            url = _invoice_query(
                sid,
                report_start,
                report_end,
            )

            invoices = list(_paged(url))

        except Exception as exc:
            errors.append(
                {
                    "subscription_id": sid,
                    "error": str(exc),
                }
            )
            continue

        for invoice in invoices:
            properties = invoice.get("properties", {})

            if str(
                properties.get("status", "")
            ).lower() != "paid":
                continue

            invoice_date = _date_only(
                properties.get("invoiceDate")
            )

            if not invoice_date.startswith(report_month):
                continue

            invoice_id = invoice.get("name") or ""

            unique_key = (sid, invoice_id)

            if unique_key in seen:
                continue

            seen.add(unique_key)

            total_value, total_currency = _amount(
                properties.get("totalAmount")
            )

            amount_source = "totalAmount"

            if total_value is None:
                total_value, total_currency = _amount(
                    properties.get("billedAmount")
                )
                amount_source = "billedAmount"

            if total_value is None:
                raise RuntimeError(
                    f"Invoice {invoice_id} has no usable amount."
                )

            due_value, due_currency = _amount(
                properties.get("amountDue")
            )

            billed_value, billed_currency = _amount(
                properties.get("billedAmount")
            )

            period_start = _date_only(
                properties.get("invoicePeriodStartDate")
            )

            period_end = _date_only(
                properties.get("invoicePeriodEndDate")
            )

            billing_period = ""

            if period_start or period_end:
                billing_period = (
                    f"{period_start} to {period_end}"
                )

            records.append(
                {
                    "Invoice ID": invoice_id,
                    "Subscription":
                        properties.get(
                            "subscriptionDisplayName"
                        )
                        or current_name,
                    "Subscription ID":
                        properties.get("subscriptionId")
                        or sid,
                    "Invoice Date": invoice_date,
                    "Billing Period": billing_period,
                    "Billing Period Start": period_start,
                    "Billing Period End": period_end,
                    "Amount Due Currency": due_currency,
                    "Amount Due": due_value,
                    "Billed Amount Currency":
                        billed_currency,
                    "Billed Amount": billed_value,
                    "Total Amount Currency":
                        total_currency,
                    "Total Amount": total_value,
                    "Amount Source": amount_source,
                    "Type": _invoice_type(
                        properties.get("invoiceType")
                    ),
                    "Status":
                        properties.get("status") or "",
                    "Due Date":
                        _date_only(properties.get("dueDate")),
                }
            )

    if errors:
        raise RuntimeError(
            "Invoice retrieval failed for one or more "
            "subscriptions. Report will not be sent. "
            + json.dumps(errors)
        )

    records.sort(
        key=lambda row: (
            row["Invoice Date"],
            row["Subscription"],
            row["Invoice ID"],
        )
    )

    return records


def _money_text(value):
    if value is None:
        return ""

    return str(
        Decimal(value).quantize(
            MONEY,
            rounding=ROUND_HALF_UP,
        )
    )


def _detail_csv(records):
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

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=fields,
        lineterminator="\n",
    )

    writer.writeheader()

    for record in records:
        row = dict(record)

        row["Amount Due"] = _money_text(
            row["Amount Due"]
        )
        row["Billed Amount"] = _money_text(
            row["Billed Amount"]
        )
        row["Total Amount"] = _money_text(
            row["Total Amount"]
        )

        writer.writerow(row)

    return output.getvalue().encode("utf-8")


def _summary_rows(records):
    grouped = defaultdict(
        lambda: {
            "total": Decimal("0"),
            "count": 0,
        }
    )

    for record in records:
        key = (
            record["Subscription"],
            record["Subscription ID"],
            record["Type"],
            record["Total Amount Currency"],
        )

        grouped[key]["total"] += record["Total Amount"]
        grouped[key]["count"] += 1

    rows = []

    for key, values in grouped.items():
        name, sid, invoice_type, currency = key

        rows.append(
            {
                "Subscription": name,
                "Subscription ID": sid,
                "Type": invoice_type,
                "Currency": currency,
                "Invoice Total":
                    values["total"].quantize(MONEY),
                "Invoice Count": values["count"],
            }
        )

    rows.sort(
        key=lambda row: (
            row["Subscription"],
            row["Type"],
        )
    )

    return rows


def _summary_csv(rows):
    fields = [
        "Subscription",
        "Subscription ID",
        "Type",
        "Currency",
        "Invoice Total",
        "Invoice Count",
    ]

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=fields,
        lineterminator="\n",
    )

    writer.writeheader()

    for row in rows:
        writer.writerow(
            {
                **row,
                "Invoice Total":
                    _money_text(row["Invoice Total"]),
            }
        )

    return output.getvalue().encode("utf-8")


def _upload_blob(blob_name, content, content_type):
    account = _env(
        "REPORT_STORAGE_ACCOUNT",
        required=True,
    )

    container = _env(
        "REPORT_CONTAINER",
        required=True,
    )

    service = BlobServiceClient(
        account_url=(
            f"https://{account}.blob.core.windows.net"
        ),
        credential=_credential_client(),
    )

    client = service.get_blob_client(
        container=container,
        blob=blob_name,
    )

    client.upload_blob(
        content,
        overwrite=True,
        content_settings=ContentSettings(
            content_type=content_type
        ),
    )


def _email_enabled():
    return (
        os.getenv("EMAIL_ENABLED", "false")
        .strip()
        .lower()
        in {"1", "true", "yes"}
    )


def _send_email(
    report_month,
    invoice_count,
    total_amount,
    summary_name,
    summary_csv,
    detail_name,
    detail_csv,
):
    recipients = [
        item.strip()
        for item in _env(
            "REPORT_RECIPIENTS",
            required=True,
        ).split(",")
        if item.strip()
    ]

    if not recipients:
        raise RuntimeError(
            "REPORT_RECIPIENTS contains no recipients."
        )

    username_secret_name = _env(
        "SMTP_USERNAME_SECRET_NAME",
        "smtp-username",
    )

    from_secret_name = _env(
        "SMTP_FROM_ADDRESS_SECRET_NAME",
        "smtp-from-address",
    )

    password_secret_name = _env(
        "SMTP_PASSWORD_SECRET_NAME",
        "smtp-app-password",
    )

    smtp_username = _secret(username_secret_name)
    from_address = _secret(from_secret_name)
    smtp_password = _secret(password_secret_name)

    smtp_host = _env(
        "SMTP_HOST",
        "smtp.gmail.com",
    )

    try:
        smtp_port = int(
            _env(
                "SMTP_PORT",
                "587",
            )
        )
    except ValueError as exc:
        raise RuntimeError(
            "SMTP_PORT must be an integer."
        ) from exc

    prefix = _env(
        "REPORT_SUBJECT_PREFIX",
        "Azure Invoice Expense Report",
    )

    subject = f"{prefix} - {report_month}"

    body = (
        f"Attached is the automated Azure invoice expense "
        f"report for {report_month}.\n\n"
        f"Paid invoices: {invoice_count}\n"
        f"Invoice total: ${total_amount:,.2f}\n\n"
        "The report was generated directly from Azure "
        "Billing invoice data."
    )

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_address
    message["To"] = ", ".join(recipients)
    message.set_content(body)

    message.add_attachment(
        summary_csv,
        maintype="text",
        subtype="csv",
        filename=summary_name,
    )

    message.add_attachment(
        detail_csv,
        maintype="text",
        subtype="csv",
        filename=detail_name,
    )

    tls_context = ssl.create_default_context()

    try:
        with smtplib.SMTP(
            smtp_host,
            smtp_port,
            timeout=90,
        ) as smtp:
            smtp.ehlo()
            smtp.starttls(context=tls_context)
            smtp.ehlo()
            smtp.login(
                smtp_username,
                smtp_password,
            )
            smtp.send_message(
                message,
                from_addr=from_address,
                to_addrs=recipients,
            )

    except (
        smtplib.SMTPException,
        OSError,
    ) as exc:
        raise RuntimeError(
            f"SMTP email delivery failed: {exc}"
        ) from exc

    logging.info(
        "Report email sent successfully to %d recipient(s).",
        len(recipients),
    )


def run_monthly_report():
    report_start, report_end = _report_period()
    report_month = report_start.strftime("%Y-%m")

    subscriptions = _list_enabled_subscriptions()

    if not subscriptions:
        raise RuntimeError(
            "No enabled subscriptions were discovered."
        )

    records = _collect_invoices(
        subscriptions,
        report_start,
        report_end,
    )

    summary = _summary_rows(records)

    detail_total = sum(
        (
            row["Total Amount"]
            for row in records
        ),
        Decimal("0"),
    ).quantize(MONEY)

    summary_total = sum(
        (
            row["Invoice Total"]
            for row in summary
        ),
        Decimal("0"),
    ).quantize(MONEY)

    if detail_total != summary_total:
        raise RuntimeError(
            "Invoice reconciliation failed: "
            f"detail={detail_total} "
            f"summary={summary_total}"
        )

    summary_content = _summary_csv(summary)
    detail_content = _detail_csv(records)

    year = report_start.strftime("%Y")
    month = report_start.strftime("%m")

    prefix = f"{year}/{month}"

    summary_name = (
        f"Azure-Expenses-{report_month}.csv"
    )

    detail_name = (
        f"Azure-Invoice-Detail-{report_month}.csv"
    )

    summary_blob = f"{prefix}/{summary_name}"
    detail_blob = f"{prefix}/{detail_name}"
    manifest_blob = f"{prefix}/manifest.json"

    manifest = {
        "report_month": report_month,
        "report_start": report_start.isoformat(),
        "report_end": report_end.isoformat(),
        "generated_utc":
            datetime.now(timezone.utc).isoformat(),
        "subscriptions_queried":
            len(subscriptions),
        "invoice_count": len(records),
        "total_amount": _money_text(detail_total),
        "currency": "USD",
        "reconciliation_difference": "0.00",
        "summary_blob": summary_blob,
        "detail_blob": detail_blob,
    }

    _upload_blob(
        summary_blob,
        summary_content,
        "text/csv; charset=utf-8",
    )

    _upload_blob(
        detail_blob,
        detail_content,
        "text/csv; charset=utf-8",
    )

    _upload_blob(
        manifest_blob,
        json.dumps(
            manifest,
            indent=2,
        ).encode("utf-8"),
        "application/json",
    )

    if _email_enabled():
        _send_email(
            report_month=report_month,
            invoice_count=len(records),
            total_amount=detail_total,
            summary_name=summary_name,
            summary_csv=summary_content,
            detail_name=detail_name,
            detail_csv=detail_content,
        )
    else:
        logging.info(
            "Email delivery is disabled."
        )

    return manifest
