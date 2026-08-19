#!/usr/bin/env python3

"""
Inspect Azure Cost Management CSV exports.

Reads a single CSV file or all CSV partitions in a directory,
counts data rows, identifies a supported cost column, and calculates
the total cost.

This script contains no environment-specific configuration.
"""

from __future__ import annotations

import argparse
import csv
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path


COST_COLUMNS = (
    "PreTaxCost",
    "CostInBillingCurrency",
    "Cost",
)


def find_csv_files(path: Path) -> list[Path]:
    if path.is_file():
        if path.suffix.lower() != ".csv":
            raise ValueError("Input file must be a CSV file.")
        return [path]

    if not path.is_dir():
        raise ValueError(f"Path does not exist: {path}")

    files = sorted(path.glob("*.csv"))

    if not files:
        raise ValueError(f"No CSV files found in: {path}")

    return files


def inspect_files(files: list[Path]) -> tuple[int, Decimal, str]:
    total_rows = 0
    total_cost = Decimal("0")
    cost_column = None

    for file_path in files:
        with file_path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as handle:
            reader = csv.DictReader(handle)

            if not reader.fieldnames:
                continue

            if cost_column is None:
                cost_column = next(
                    (
                        column
                        for column in COST_COLUMNS
                        if column in reader.fieldnames
                    ),
                    None,
                )

                if cost_column is None:
                    raise ValueError(
                        "No supported cost column found. "
                        f"Expected one of: {', '.join(COST_COLUMNS)}"
                    )

            for row in reader:
                if not any(
                    value and value.strip()
                    for value in row.values()
                    if value is not None
                ):
                    continue

                total_rows += 1

                value = (row.get(cost_column) or "").strip()

                if not value:
                    continue

                try:
                    total_cost += Decimal(value)
                except InvalidOperation as exc:
                    raise ValueError(
                        f"Invalid cost value in {file_path.name}: {value!r}"
                    ) from exc

    if cost_column is None:
        raise ValueError("No readable Azure Cost Management data found.")

    return total_rows, total_cost, cost_column


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect an Azure Cost Management CSV export."
    )

    parser.add_argument(
        "path",
        type=Path,
        help="CSV file or directory containing CSV partitions.",
    )

    args = parser.parse_args()

    try:
        files = find_csv_files(args.path)
        rows, total, cost_column = inspect_files(files)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("Azure Cost Export Summary")
    print("-------------------------")
    print(f"CSV files   : {len(files)}")
    print(f"Cost column : {cost_column}")
    print(f"Data rows   : {rows:,}")
    print(f"Cost total  : {total:.2f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
