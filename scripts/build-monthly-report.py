#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
from decimal import Decimal

from reporting_common import (
    REPO_ROOT,
    blob_clients,
    build_month,
    credential,
    discover_subscriptions,
    list_latest_manifests,
    load_config,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a monthly Azure cost report from Blob Storage."
    )

    parser.add_argument("year", type=int)
    parser.add_argument("month", type=int)

    args = parser.parse_args()

    if not 1 <= args.month <= 12:
        parser.error("month must be between 1 and 12")

    config = load_config()
    cred = credential()

    print("Discovering Azure subscriptions...")
    subscriptions = discover_subscriptions(cred)

    print(f"Active subscriptions: {len(subscriptions)}")
    print("Indexing Cost Management manifests...")

    container = blob_clients(cred, config)

    manifest_index = list_latest_manifests(
        container,
        config["export_root_path"],
    )

    print(
        f"Building report for "
        f"{args.year:04d}-{args.month:02d}..."
    )

    totals, missing = build_month(
        container,
        subscriptions,
        manifest_index,
        args.year,
        args.month,
    )

    output_dir = REPO_ROOT / "output" / "monthly"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / (
        f"Azure-Cost-Report-"
        f"{args.year:04d}-{args.month:02d}.csv"
    )

    rows_by_subscription = {}

    for total in totals:
        rows_by_subscription.setdefault(
            total.subscription_id,
            [],
        ).append(total)

    grand_totals: dict[str, Decimal] = {}

    with output_file.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as handle:

        writer = csv.writer(handle)

        writer.writerow(
            [
                "Subscription",
                "Subscription ID",
                "Status",
                "Currency",
                "Cost",
                "Data Rows",
            ]
        )

        for subscription in subscriptions:
            report_rows = rows_by_subscription.get(
                subscription.subscription_id
            )

            if not report_rows:
                writer.writerow(
                    [
                        subscription.display_name,
                        subscription.subscription_id,
                        "No export data / inaccessible",
                        "",
                        "",
                        "",
                    ]
                )
                continue

            for row in report_rows:
                if row.rows == 0:
                    status = "No usage"
                    currency = ""
                else:
                    status = "Data available"
                    currency = row.currency

                writer.writerow(
                    [
                        row.display_name,
                        row.subscription_id,
                        status,
                        currency,
                        f"{row.cost:.2f}",
                        row.rows,
                    ]
                )

                # Don't create meaningless blank-currency zero totals.
                if row.currency and row.cost != Decimal("0"):
                    grand_totals[row.currency] = (
                        grand_totals.get(
                            row.currency,
                            Decimal("0"),
                        )
                        + row.cost
                    )

        writer.writerow([])

        for currency, total in sorted(
            grand_totals.items()
        ):
            writer.writerow(
                [
                    "TOTAL",
                    "",
                    "",
                    currency,
                    f"{total:.2f}",
                    "",
                ]
            )

    print()
    print("Monthly report created")
    print("----------------------")
    print(f"File            : {output_file}")
    print(f"Active subs     : {len(subscriptions)}")
    print(f"Exports found   : {len(subscriptions) - len(missing)}")
    print(f"Exports missing : {len(missing)}")

    for currency, total in sorted(
        grand_totals.items()
    ):
        print(f"Total {currency:<12}: {total:.2f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
