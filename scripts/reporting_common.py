#!/usr/bin/env python3

from __future__ import annotations

import calendar
import csv
import hashlib
import io
import json
import subprocess
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient


REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = REPO_ROOT / "config" / "config.sh"

EXPORT_NAME = "cost-usage-history"

COST_COLUMNS = (
    "PreTaxCost",
    "CostInBillingCurrency",
    "Cost",
)

CURRENCY_COLUMNS = (
    "BillingCurrency",
    "BillingCurrencyCode",
    "Currency",
)


@dataclass
class Subscription:
    subscription_id: str
    display_name: str
    report_key: str


@dataclass
class MonthlyTotal:
    subscription_id: str
    display_name: str
    report_key: str
    currency: str
    cost: Decimal
    rows: int
    manifest_blob: str


def load_config() -> dict[str, str]:
    if not CONFIG_FILE.exists():
        raise RuntimeError(
            f"Private configuration not found: {CONFIG_FILE}"
        )

    script = r'''
set -euo pipefail
source "$1"
printf '%s\0%s\0%s\0' \
  "${STORAGE_RESOURCE_ID:-}" \
  "${STORAGE_CONTAINER:-}" \
  "${EXPORT_ROOT_PATH:-azure-cost-history}"
'''

    result = subprocess.run(
        ["bash", "-c", script, "_", str(CONFIG_FILE)],
        check=True,
        capture_output=True,
    )

    parts = result.stdout.split(b"\0")

    values = [part.decode() for part in parts[:3]]

    config = {
        "storage_resource_id": values[0],
        "storage_container": values[1],
        "export_root_path": values[2],
    }

    for key, value in config.items():
        if not value:
            raise RuntimeError(f"Required configuration missing: {key}")

    config["storage_account_name"] = (
        config["storage_resource_id"].rstrip("/").split("/")[-1]
    )

    return config


def credential() -> DefaultAzureCredential:
    return DefaultAzureCredential(
        exclude_interactive_browser_credential=True
    )


def arm_get_json(
    cred: DefaultAzureCredential,
    url: str,
) -> dict:
    token = cred.get_token(
        "https://management.azure.com/.default"
    ).token

    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )

    with urllib.request.urlopen(request) as response:
        return json.load(response)


def report_key(subscription_id: str) -> str:
    digest = hashlib.sha256(
        subscription_id.encode("utf-8")
    ).hexdigest()

    return f"sub-{digest[:12]}"


def discover_subscriptions(
    cred: DefaultAzureCredential,
) -> list[Subscription]:
    data = arm_get_json(
        cred,
        "https://management.azure.com/"
        "subscriptions?api-version=2022-12-01",
    )

    subscriptions = []

    for item in data.get("value", []):
        if item.get("state") != "Enabled":
            continue

        sid = item["subscriptionId"]

        subscriptions.append(
            Subscription(
                subscription_id=sid,
                display_name=item.get("displayName", sid),
                report_key=report_key(sid),
            )
        )

    subscriptions.sort(
        key=lambda value: value.display_name.lower()
    )

    return subscriptions


def storage_date_range(year: int, month: int) -> str:
    last_day = calendar.monthrange(year, month)[1]

    return (
        f"{year:04d}{month:02d}01-"
        f"{year:04d}{month:02d}{last_day:02d}"
    )


def blob_clients(
    cred: DefaultAzureCredential,
    config: dict[str, str],
):
    service = BlobServiceClient(
        account_url=(
            f"https://{config['storage_account_name']}"
            ".blob.core.windows.net"
        ),
        credential=cred,
    )

    return service.get_container_client(
        config["storage_container"]
    )


def list_latest_manifests(
    container,
    root_path: str,
) -> dict[tuple[str, str], str]:
    latest: dict[tuple[str, str], tuple[object, str]] = {}

    prefix = f"{root_path.rstrip('/')}/"

    for blob in container.list_blobs(name_starts_with=prefix):
        name = blob.name

        if not name.endswith("/manifest.json"):
            continue

        parts = name.split("/")

        # Expected:
        # root/report-key/export-name/date-range/run-id/manifest.json
        try:
            export_index = parts.index(EXPORT_NAME)
        except ValueError:
            continue

        if export_index < 1 or export_index + 2 >= len(parts):
            continue

        key = parts[export_index - 1]
        date_range = parts[export_index + 1]

        map_key = (key, date_range)

        previous = latest.get(map_key)

        if (
            previous is None
            or blob.last_modified > previous[0]
        ):
            latest[map_key] = (
                blob.last_modified,
                name,
            )

    return {
        key: value[1]
        for key, value in latest.items()
    }


def read_manifest(container, blob_name: str) -> dict:
    payload = container.download_blob(blob_name).readall()

    return json.loads(payload)


def csv_blob_names(manifest: dict) -> list[str]:
    names = []

    for item in manifest.get("blobs", []):
        name = item.get("blobName")

        if name:
            names.append(name)

    return names


def aggregate_csv_blob(
    container,
    blob_name: str,
) -> tuple[dict[str, Decimal], int]:
    payload = container.download_blob(blob_name).readall()

    text = io.StringIO(
        payload.decode("utf-8-sig"),
        newline="",
    )

    reader = csv.DictReader(text)

    if not reader.fieldnames:
        return {}, 0

    cost_column = next(
        (
            column
            for column in COST_COLUMNS
            if column in reader.fieldnames
        ),
        None,
    )

    if cost_column is None:
        raise RuntimeError(
            f"No supported cost column in {blob_name}"
        )

    currency_column = next(
        (
            column
            for column in CURRENCY_COLUMNS
            if column in reader.fieldnames
        ),
        None,
    )

    totals: dict[str, Decimal] = defaultdict(
        lambda: Decimal("0")
    )

    rows = 0

    for row in reader:
        if not any(
            value and value.strip()
            for value in row.values()
            if value is not None
        ):
            continue

        rows += 1

        raw_cost = (row.get(cost_column) or "").strip()

        if not raw_cost:
            continue

        currency = ""

        if currency_column:
            currency = (
                row.get(currency_column) or ""
            ).strip()

        try:
            totals[currency] += Decimal(raw_cost)
        except InvalidOperation as exc:
            raise RuntimeError(
                f"Invalid cost value {raw_cost!r} "
                f"in {blob_name}"
            ) from exc

    return dict(totals), rows


def build_month(
    container,
    subscriptions: list[Subscription],
    manifest_index: dict[tuple[str, str], str],
    year: int,
    month: int,
) -> tuple[list[MonthlyTotal], list[Subscription]]:
    date_range = storage_date_range(year, month)

    totals: list[MonthlyTotal] = []
    missing: list[Subscription] = []

    for subscription in subscriptions:
        manifest_blob = manifest_index.get(
            (subscription.report_key, date_range)
        )

        if not manifest_blob:
            missing.append(subscription)
            continue

        manifest = read_manifest(
            container,
            manifest_blob,
        )

        currency_totals: dict[str, Decimal] = defaultdict(
            lambda: Decimal("0")
        )

        total_rows = 0

        for csv_blob in csv_blob_names(manifest):
            blob_totals, rows = aggregate_csv_blob(
                container,
                csv_blob,
            )

            total_rows += rows

            for currency, amount in blob_totals.items():
                currency_totals[currency] += amount

        if not currency_totals:
            currency_totals[""] = Decimal("0")

        for currency, amount in currency_totals.items():
            totals.append(
                MonthlyTotal(
                    subscription_id=subscription.subscription_id,
                    display_name=subscription.display_name,
                    report_key=subscription.report_key,
                    currency=currency,
                    cost=amount,
                    rows=total_rows,
                    manifest_blob=manifest_blob,
                )
            )

    return totals, missing
