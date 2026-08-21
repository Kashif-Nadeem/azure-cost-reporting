#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import io
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from reporting_common import (
    COST_COLUMNS,
    blob_clients,
    credential,
    csv_blob_names,
    discover_subscriptions,
    list_latest_manifests,
    load_config,
    read_manifest,
    storage_date_range,
)


def field(row: dict, *names: str) -> str:
    lookup = {
        str(key).casefold(): (value or "")
        for key, value in row.items()
        if key is not None
    }

    for name in names:
        value = lookup.get(name.casefold())

        if value is not None:
            return str(value).strip()

    return ""


def classify(
    charge_type: str,
    publisher_type: str,
    pricing_model: str,
    reservation_id: str,
) -> str:

    publisher = publisher_type.casefold()
    pricing = pricing_model.casefold()
    charge = charge_type.casefold()

    if (
        publisher == "marketplace"
        or "reservation" in pricing
        or "savingsplan" in pricing
        or reservation_id
    ):
        return "Marketplace / Reservation"

    if charge == "purchase":
        return "Other Purchase"

    return "Azure services"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audit historical Azure cost export names and "
            "charge classifications directly from Blob Storage."
        )
    )

    parser.add_argument("year", type=int)

    args = parser.parse_args()

    config = load_config()
    cred = credential()

    subscriptions = discover_subscriptions(cred)

    by_key = {
        subscription.report_key: subscription
        for subscription in subscriptions
    }

    container = blob_clients(cred, config)

    print("Indexing manifests...")

    manifest_index = list_latest_manifests(
        container,
        config["export_root_path"],
    )

    totals = defaultdict(lambda: Decimal("0"))
    rows = defaultdict(int)

    for month in range(1, 13):
        date_range = storage_date_range(args.year, month)

        print(
            f"Reading {args.year}-{month:02d}..."
        )

        for report_key, subscription in by_key.items():
            manifest_blob = manifest_index.get(
                (report_key, date_range)
            )

            if not manifest_blob:
                continue

            manifest = read_manifest(
                container,
                manifest_blob,
            )

            for csv_blob in csv_blob_names(manifest):
                payload = (
                    container
                    .download_blob(csv_blob)
                    .readall()
                )

                reader = csv.DictReader(
                    io.StringIO(
                        payload.decode("utf-8-sig")
                    )
                )

                if not reader.fieldnames:
                    continue

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
                        f"No cost column in {csv_blob}"
                    )

                for row in reader:
                    raw_cost = (
                        row.get(cost_column) or ""
                    ).strip()

                    if not raw_cost:
                        continue

                    try:
                        cost = Decimal(raw_cost)
                    except InvalidOperation:
                        continue

                    historical_name = field(
                        row,
                        "SubscriptionName",
                        "subscriptionName",
                    )

                    historical_id = field(
                        row,
                        "SubscriptionId",
                        "subscriptionId",
                    )

                    charge_type = field(
                        row,
                        "ChargeType",
                        "chargeType",
                    )

                    publisher_type = field(
                        row,
                        "PublisherType",
                        "publisherType",
                    )

                    pricing_model = field(
                        row,
                        "PricingModel",
                        "pricingModel",
                    )

                    reservation_id = field(
                        row,
                        "ReservationId",
                        "reservationId",
                    )

                    currency = field(
                        row,
                        "BillingCurrency",
                        "BillingCurrencyCode",
                        "Currency",
                    )

                    category = classify(
                        charge_type,
                        publisher_type,
                        pricing_model,
                        reservation_id,
                    )

                    key = (
                        historical_name
                        or subscription.display_name,
                        subscription.display_name,
                        historical_id
                        or subscription.subscription_id,
                        currency,
                        category,
                        charge_type,
                        publisher_type,
                        pricing_model,
                    )

                    totals[key] += cost
                    rows[key] += 1

    output_dir = (
        __import__("pathlib").Path(__file__)
        .resolve()
        .parent.parent
        / "output"
        / "audit"
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_file = (
        output_dir
        / f"Azure-Cost-Structure-{args.year}.csv"
    )

    with output_file.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as handle:

        writer = csv.writer(handle)

        writer.writerow(
            [
                "Historical Subscription Name",
                "Current Subscription Name",
                "Subscription ID",
                "Currency",
                "Provisional Category",
                "Charge Type",
                "Publisher Type",
                "Pricing Model",
                "Cost",
                "Rows",
            ]
        )

        for key in sorted(
            totals,
            key=lambda value: (
                value[0].casefold(),
                value[4],
                value[5],
            ),
        ):
            writer.writerow(
                [
                    *key,
                    f"{totals[key]:.2f}",
                    rows[key],
                ]
            )

    print()
    print("Audit complete")
    print("--------------")
    print(f"File: {output_file}")

    category_totals = defaultdict(
        lambda: Decimal("0")
    )

    historical_names = set()
    renamed = set()

    for key, amount in totals.items():
        historical_name = key[0]
        current_name = key[1]
        currency = key[3]
        category = key[4]

        historical_names.add(historical_name)

        if (
            historical_name
            and current_name
            and historical_name.casefold()
            != current_name.casefold()
        ):
            renamed.add(
                (historical_name, current_name)
            )

        category_totals[
            (currency, category)
        ] += amount

    print()
    print("Category totals")
    print("---------------")

    for (currency, category), amount in sorted(
        category_totals.items()
    ):
        print(
            f"{category:28} "
            f"{currency:5} "
            f"{amount:12.2f}"
        )

    print()
    print(
        f"Historical subscription names: "
        f"{len(historical_names)}"
    )

    print(
        f"Historical/current name changes: "
        f"{len(renamed)}"
    )

    if renamed:
        print()
        print("Historical -> current names")
        print("---------------------------")

        for old, current in sorted(
            renamed,
            key=lambda item: item[0].casefold(),
        ):
            print(f"{old} -> {current}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
