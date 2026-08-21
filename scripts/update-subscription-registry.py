#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode


BASE = "https://management.azure.com"
ARM_API = "2022-12-01"
BILLING_API = "2024-04-01"

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCAL_STATE_DIR = REPO_ROOT / "output" / "state"
LOCAL_REGISTRY = LOCAL_STATE_DIR / "subscription-registry.json"

UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{12}$"
)


def run(args, check=True):
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
    )

    if check and result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip()
            or result.stdout.strip()
        )

    return result


def az_get(url):
    result = run(
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
        check=False,
    )

    if result.returncode != 0:
        return None, (
            result.stderr.strip()
            or result.stdout.strip()
        )

    try:
        return json.loads(result.stdout), None
    except json.JSONDecodeError as exc:
        return None, str(exc)


def paged_get(url):
    items = []
    seen = set()

    while url:
        if url in seen:
            raise RuntimeError(
                "Repeated Azure nextLink detected"
            )

        seen.add(url)

        payload, error = az_get(url)

        if error:
            return items, error

        items.extend(
            payload.get("value", [])
        )

        url = payload.get("nextLink")

    return items, None


def shell_config():
    command = f"""
source "{REPO_ROOT}/config/config.sh"

printf '%s\\n' \
  "$STORAGE_RESOURCE_ID" \
  "$STORAGE_CONTAINER" \
  "$EXPORT_ROOT_PATH"
"""

    result = run(
        ["bash", "-lc", command]
    )

    values = result.stdout.splitlines()

    if len(values) < 3:
        raise RuntimeError(
            "Unable to load storage configuration"
        )

    storage_resource_id = values[0].strip()
    container = values[1].strip()
    export_root = values[2].strip().rstrip("/")

    if not storage_resource_id or not container:
        raise RuntimeError(
            "Storage configuration is incomplete"
        )

    return (
        storage_resource_id,
        container,
        export_root,
    )


def download_existing_registry(
    account_name,
    container,
    blob_name,
):
    LOCAL_STATE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    result = run(
        [
            "az",
            "storage",
            "blob",
            "download",
            "--account-name",
            account_name,
            "--container-name",
            container,
            "--name",
            blob_name,
            "--file",
            str(LOCAL_REGISTRY),
            "--auth-mode",
            "login",
            "--overwrite",
            "--only-show-errors",
        ],
        check=False,
    )

    if result.returncode != 0:
        return {
            "version": 1,
            "subscriptions": {},
        }

    try:
        with LOCAL_REGISTRY.open(
            encoding="utf-8"
        ) as handle:
            return json.load(handle)
    except Exception:
        return {
            "version": 1,
            "subscriptions": {},
        }


def save_registry(
    registry,
    account_name,
    container,
    blob_name,
):
    LOCAL_STATE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    with LOCAL_REGISTRY.open(
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(
            registry,
            handle,
            indent=2,
            sort_keys=True,
        )

    result = run(
        [
            "az",
            "storage",
            "blob",
            "upload",
            "--account-name",
            account_name,
            "--container-name",
            container,
            "--name",
            blob_name,
            "--file",
            str(LOCAL_REGISTRY),
            "--auth-mode",
            "login",
            "--overwrite",
            "true",
            "--only-show-errors",
        ],
        check=False,
    )

    if result.returncode != 0:
        print(
            "WARNING: Registry saved locally but could not "
            "be persisted to Azure Blob."
        )
        return False

    return True


def subscription_id(item):
    properties = item.get(
        "properties",
        {},
    )

    for value in (
        properties.get("subscriptionId"),
        item.get("name"),
    ):
        if value and UUID_RE.match(
            str(value)
        ):
            return str(value).lower()

    return None


def main():
    (
        storage_resource_id,
        container,
        export_root,
    ) = shell_config()

    storage_account = (
        storage_resource_id.rstrip("/")
        .split("/")[-1]
    )

    registry_blob = (
        f"{export_root}/state/"
        "subscription-registry.json"
    )

    registry = download_existing_registry(
        storage_account,
        container,
        registry_blob,
    )

    subscriptions = registry.setdefault(
        "subscriptions",
        {},
    )

    now = datetime.now(
        timezone.utc
    ).isoformat()

    print(
        "Discovering current ARM subscriptions..."
    )

    arm_url = (
        f"{BASE}/subscriptions"
        f"?api-version={ARM_API}"
    )

    arm_items, error = paged_get(
        arm_url
    )

    if error:
        raise RuntimeError(error)

    current_ids = set()
    billing_accounts = {}

    for item in arm_items:
        sid = (
            item.get("subscriptionId")
            or ""
        ).lower()

        if not sid:
            continue

        current_ids.add(sid)

        record = subscriptions.setdefault(
            sid,
            {},
        )

        record["currentName"] = (
            item.get("displayName")
            or record.get("currentName")
            or ""
        )

        record["armState"] = (
            item.get("state")
            or ""
        )

        record.setdefault(
            "firstSeenUtc",
            now,
        )

        record["lastSeenUtc"] = now
        record["lastSeenSource"] = "ARM"
        record["currentlyVisibleInArm"] = True

        property_url = (
            f"{BASE}/subscriptions/{sid}/"
            "providers/Microsoft.Billing/"
            "billingProperty/default"
            f"?api-version={BILLING_API}"
        )

        billing_property, property_error = (
            az_get(property_url)
        )

        if property_error:
            record[
                "billingPropertyStatus"
            ] = "Unavailable"
            continue

        properties = billing_property.get(
            "properties",
            {},
        )

        account_id = (
            properties.get(
                "billingAccountId"
            )
            or ""
        )

        agreement = (
            properties.get(
                "billingAccountAgreementType"
            )
            or ""
        )

        record[
            "billingPropertyStatus"
        ] = "Available"

        record[
            "billingAgreementType"
        ] = agreement

        if account_id:
            account_name = (
                account_id.rstrip("/")
                .split("/")[-1]
            )

            record[
                "billingAccountName"
            ] = account_name

            billing_accounts.setdefault(
                account_name,
                agreement,
            )

    for sid, record in subscriptions.items():
        if sid not in current_ids:
            record[
                "currentlyVisibleInArm"
            ] = False

    print(
        f"Current ARM subscriptions: "
        f"{len(current_ids)}"
    )

    print(
        f"Billing accounts discovered: "
        f"{len(billing_accounts)}"
    )

    billing_ids = set()

    for account_name, agreement in (
        billing_accounts.items()
    ):
        params = {
            "api-version": BILLING_API,
            "includeDeleted": "true",
            "includeFailed": "true",
            "top": 50,
        }

        if (
            agreement
            == "MicrosoftOnlineServicesProgram"
        ):
            params[
                "includeTenantSubscriptions"
            ] = "true"

        url = (
            f"{BASE}/providers/"
            "Microsoft.Billing/"
            f"billingAccounts/{account_name}/"
            "billingSubscriptions?"
            f"{urlencode(params)}"
        )

        items, error = paged_get(
            url
        )

        if error:
            print(
                f"Billing account "
                f"{account_name}: unavailable"
            )
            continue

        print(
            f"Billing account "
            f"{account_name}: "
            f"{len(items)} subscription(s)"
        )

        for item in items:
            sid = subscription_id(item)

            if not sid:
                continue

            billing_ids.add(sid)

            properties = item.get(
                "properties",
                {},
            )

            record = (
                subscriptions.setdefault(
                    sid,
                    {},
                )
            )

            billing_name = (
                properties.get(
                    "displayName"
                )
                or properties.get(
                    "subscriptionName"
                )
                or ""
            )

            if billing_name:
                record[
                    "billingName"
                ] = billing_name

            record[
                "billingStatus"
            ] = (
                properties.get("status")
                or ""
            )

            record[
                "billingAgreementType"
            ] = agreement

            record[
                "billingAccountName"
            ] = account_name

            record.setdefault(
                "firstSeenUtc",
                now,
            )

            record["lastSeenUtc"] = now
            record[
                "lastSeenSource"
            ] = "Billing"

    registry["version"] = 1
    registry["updatedUtc"] = now

    registry["statistics"] = {
        "currentArmSubscriptions": len(
            current_ids
        ),
        "billingSubscriptions": len(
            billing_ids
        ),
        "registrySubscriptions": len(
            subscriptions
        ),
    }

    blob_persisted = save_registry(
        registry,
        storage_account,
        container,
        registry_blob,
    )

    historical = [
        sid
        for sid, record
        in subscriptions.items()
        if not record.get(
            "currentlyVisibleInArm",
            False,
        )
    ]

    print()
    print("Subscription registry updated")
    print("-----------------------------")
    print(
        f"Registry entries : "
        f"{len(subscriptions)}"
    )
    print(
        f"Current ARM      : "
        f"{len(current_ids)}"
    )
    print(
        f"Billing IDs      : "
        f"{len(billing_ids)}"
    )
    print(
        f"Historical       : "
        f"{len(historical)}"
    )
    print(
        f"Local registry   : "
        f"{LOCAL_REGISTRY}"
    )
    if blob_persisted:
        print(
            "Blob persistence : Success"
        )
    else:
        print(
            "Blob persistence : Not available"
        )


if __name__ == "__main__":
    main()
