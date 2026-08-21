#!/usr/bin/env python3

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = REPO_ROOT / "output" / "invoices"


def money(value: str) -> Decimal:
    value = (value or "").strip()
    return Decimal(value) if value else Decimal("0")


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit(
            "Usage: build-invoice-summary.py START_YEAR END_YEAR"
        )

    start_year = int(sys.argv[1])
    end_year = int(sys.argv[2])
    current_year = datetime.now().year

    if end_year < start_year:
        raise SystemExit("END_YEAR must be >= START_YEAR")

    reports = []

    for year in range(start_year, end_year + 1):
        is_current = year == current_year

        label = (
            f"{year} YTD"
            if is_current
            else str(year)
        )

        filename = (
            f"Azure-Invoice-Report-{year}-YTD.csv"
            if is_current
            else f"Azure-Invoice-Report-{year}.csv"
        )

        reports.append(
            (
                year,
                label,
                REPORT_DIR / filename,
            )
        )

    output_file = (
        REPORT_DIR
        / f"Azure-Invoice-Summary-{start_year}-{end_year}.csv"
    )

    values = defaultdict(
        lambda: {
            "names": {},
            "years": defaultdict(
                lambda: Decimal("0")
            ),
        }
    )

    source_totals = defaultdict(
        lambda: defaultdict(
            lambda: Decimal("0")
        )
    )

    for year, label, path in reports:
        if not path.exists():
            raise SystemExit(
                f"Missing report: {path}"
            )

        with path.open(
            encoding="utf-8-sig",
            newline="",
        ) as handle:

            reader = csv.DictReader(handle)

            for row in reader:
                name = (
                    row.get("Subscription")
                    or ""
                ).strip()

                sid = (
                    row.get("Subscription ID")
                    or ""
                ).strip()

                invoice_type = (
                    row.get("Type")
                    or ""
                ).strip()

                currency = (
                    row.get("Currency")
                    or ""
                ).strip()

                total = money(
                    row.get("Year Total")
                )

                if name == "TOTAL":
                    source_totals[
                        year
                    ][currency] += total
                    continue

                if not sid:
                    continue

                key = (
                    sid,
                    invoice_type,
                    currency,
                )

                values[key]["names"][
                    year
                ] = name

                values[key]["years"][
                    year
                ] += total

    def latest_name(record):
        for year in range(
            end_year,
            start_year - 1,
            -1,
        ):
            name = record["names"].get(year)

            if name:
                return name

        return ""

    rows = sorted(
        values.items(),
        key=lambda item: (
            latest_name(item[1]).casefold(),
            item[0][1].casefold(),
            item[0][2],
        ),
    )

    totals = defaultdict(
        lambda: defaultdict(
            lambda: Decimal("0")
        )
    )

    year_labels = [
        label
        for _, label, _ in reports
    ]

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
                *year_labels,
                "Period Total",
            ]
        )

        for (
            sid,
            invoice_type,
            currency,
        ), record in rows:

            year_values = [
                record["years"][year]
                for year, _, _ in reports
            ]

            period_total = sum(
                year_values,
                Decimal("0"),
            )

            for (
                year,
                _,
                _,
            ), value in zip(
                reports,
                year_values,
            ):
                totals[currency][year] += value

            totals[
                currency
            ]["period"] += period_total

            writer.writerow(
                [
                    latest_name(record),
                    sid,
                    invoice_type,
                    currency,
                    *[
                        f"{value:.2f}"
                        for value in year_values
                    ],
                    f"{period_total:.2f}",
                ]
            )

        writer.writerow([])

        for currency in sorted(totals):
            writer.writerow(
                [
                    "TOTAL",
                    "",
                    "",
                    currency,
                    *[
                        f"{totals[currency][year]:.2f}"
                        for year, _, _ in reports
                    ],
                    f"{totals[currency]['period']:.2f}",
                ]
            )

    print("Multi-year invoice summary created")
    print("----------------------------------")
    print(f"File: {output_file}")

    print()
    print("Validation")

    for year, label, _ in reports:
        for currency, expected in sorted(
            source_totals[year].items()
        ):
            actual = totals[currency][year]

            status = (
                "OK"
                if actual == expected
                else "MISMATCH"
            )

            print(
                f"{label:<10} "
                f"{currency:<5} "
                f"{actual:>10.2f} "
                f"{status}"
            )

    print()
    print("Period totals")

    for currency in sorted(totals):
        print(
            f"{currency:<5} "
            f"{totals[currency]['period']:.2f}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
