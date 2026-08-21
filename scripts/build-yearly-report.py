#!/usr/bin/env python3

from __future__ import annotations

import argparse
import calendar
import csv
from collections import defaultdict
from datetime import datetime, timezone
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


MONTH_NAMES = [
    calendar.month_abbr[index]
    for index in range(1, 13)
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a yearly Azure cost report from Blob Storage."
    )

    parser.add_argument("year", type=int)

    parser.add_argument(
        "--through-month",
        type=int,
        default=None,
        help="Last month to include. Defaults to December for past years "
             "and the current UTC month for the current year.",
    )

    args = parser.parse_args()

    now = datetime.now(timezone.utc)

    if args.through_month is not None:
        through_month = args.through_month
    elif args.year == now.year:
        through_month = now.month
    elif args.year < now.year:
        through_month = 12
    else:
        parser.error("Cannot build a report for a future year.")

    if not 1 <= through_month <= 12:
        parser.error("through-month must be between 1 and 12")

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

    # subscription_id -> currency -> month -> cost
    costs = defaultdict(
        lambda: defaultdict(dict)
    )

    # subscription_id -> months with valid manifests
    coverage = defaultdict(set)

    for month in range(1, through_month + 1):
        print(
            f"Reading {args.year:04d}-{month:02d} "
            f"({month}/{through_month})..."
        )

        month_totals, _ = build_month(
            container,
            subscriptions,
            manifest_index,
            args.year,
            month,
        )

        seen_this_month = set()

        for item in month_totals:
            coverage[item.subscription_id].add(month)
            seen_this_month.add(item.subscription_id)

            # A zero-row export may have no currency.
            # Record zero under USD only if another month later establishes
            # a currency; otherwise the zero is represented through coverage.
            if item.currency:
                costs[item.subscription_id][item.currency][month] = (
                    item.cost
                )

    output_dir = REPO_ROOT / "output" / "yearly"
    output_dir.mkdir(parents=True, exist_ok=True)

    suffix = (
        "YTD"
        if through_month < 12
        else str(args.year)
    )

    if through_month < 12:
        filename = f"Azure-Cost-Report-{args.year}-YTD.csv"
    else:
        filename = f"Azure-Cost-Report-{args.year}.csv"

    output_file = output_dir / filename

    yearly_totals: dict[str, Decimal] = defaultdict(
        lambda: Decimal("0")
    )

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
                "Currency",
                *MONTH_NAMES,
                "Year Total",
                "Coverage",
                "Status",
            ]
        )

        for subscription in subscriptions:
            sid = subscription.subscription_id
            covered = coverage.get(sid, set())
            currency_map = costs.get(sid, {})

            if not covered:
                writer.writerow(
                    [
                        subscription.display_name,
                        sid,
                        "",
                        *([""] * 12),
                        "",
                        f"0/{through_month}",
                        "No export data / inaccessible",
                    ]
                )
                continue

            if not currency_map:
                # All available months have zero rows / no usage.
                values = []

                for month in range(1, 13):
                    if month > through_month:
                        values.append("")
                    elif month in covered:
                        values.append("0.00")
                    else:
                        values.append("")

                writer.writerow(
                    [
                        subscription.display_name,
                        sid,
                        "",
                        *values,
                        "0.00",
                        f"{len(covered)}/{through_month}",
                        "No usage",
                    ]
                )
                continue

            for currency, month_map in sorted(
                currency_map.items()
            ):
                values = []
                year_total = Decimal("0")

                for month in range(1, 13):
                    if month > through_month:
                        values.append("")
                        continue

                    if month in month_map:
                        value = month_map[month]
                    elif month in covered:
                        value = Decimal("0")
                    else:
                        values.append("")
                        continue

                    values.append(f"{value:.2f}")
                    year_total += value

                yearly_totals[currency] += year_total

                status = (
                    "Complete"
                    if len(covered) == through_month
                    else "Partial"
                )

                writer.writerow(
                    [
                        subscription.display_name,
                        sid,
                        currency,
                        *values,
                        f"{year_total:.2f}",
                        f"{len(covered)}/{through_month}",
                        status,
                    ]
                )

        writer.writerow([])

        for currency, total in sorted(
            yearly_totals.items()
        ):
            writer.writerow(
                [
                    "TOTAL",
                    "",
                    currency,
                    *([""] * 12),
                    f"{total:.2f}",
                    "",
                    "",
                ]
            )

    print()
    print("Yearly report created")
    print("---------------------")
    print(f"File          : {output_file}")
    print(f"Year          : {args.year}")
    print(f"Through month : {through_month}")
    print(f"Subscriptions : {len(subscriptions)}")

    for currency, total in sorted(
        yearly_totals.items()
    ):
        print(f"Total {currency:<8}: {total:.2f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
