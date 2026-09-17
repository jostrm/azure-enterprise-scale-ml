"""Strict local-only adapters for the existing token and showback runbooks."""

from __future__ import annotations

import argparse
import base64
import json
import math
import runpy
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener


CONTRACT = "aifactory.aggregate-report.v1"
MAX_BYTES = 2 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RuntimeError("Redirected reporting requests are not permitted.")


def retry_delay(headers):
    delays = []
    for key, value in headers.items():
        key = key.lower()
        if key != "retry-after" and not (key.startswith("x-ms-ratelimit-microsoft.costmanagement-") and key.endswith("retry-after")):
            continue
        text = str(value).strip()
        if text.isascii() and text.isdigit() and len(text) <= 8:
            delays.append(int(text))
        elif key == "retry-after" and len(text) <= 100:
            try:
                delays.append(max(0, int((parsedate_to_datetime(text) - datetime.now(timezone.utc)).total_seconds())))
            except (ValueError, TypeError):
                pass
    return max(delays, default=60)


def read_json(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Report request exceeds its size limit.")
    return json.loads(raw)


def arm(request, url, body=None):
    scope = request["scope"]
    prefix = f"https://management.azure.com/subscriptions/{scope['subscription_id']}/resourceGroups/{scope['resource_group']}"
    if not url.startswith(prefix + "/") or not url.endswith("?api-version=2023-03-01"):
        raise ValueError("Cost query must target the exact reviewed resource group.")
    command = [*request["azure_cli"], "account", "get-access-token", "--subscription", scope["subscription_id"],
               "--resource", "https://management.azure.com/", "--query", "accessToken",
               "--output", "tsv", "--only-show-errors"]
    result = subprocess.run(command, shell=False, stdin=subprocess.DEVNULL, capture_output=True,
                            text=True, encoding="utf-8", timeout=30)
    if result.returncode or len(result.stdout) > 32768:
        raise RuntimeError("Selected Azure CLI token acquisition failed.")
    token = result.stdout.strip()
    try:
        encoded = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        expiry, not_before = float(claims.get("exp", 0)), float(claims.get("nbf", 0))
        now = datetime.now(timezone.utc).timestamp()
        if (claims.get("tid", "").lower() != scope["tenant_id"].lower()
                or claims.get("oid", "").lower() != request["object_id"].lower()
                or not math.isfinite(expiry) or not math.isfinite(not_before)
                or expiry <= now or not_before > now + 60
                or claims.get("aud") not in {"https://management.azure.com/", "https://management.azure.com",
                                             "https://management.core.windows.net/"}):
            raise ValueError
    except (ValueError, IndexError, AttributeError, TypeError):
        raise RuntimeError("Azure CLI identity changed after report confirmation.") from None
    encoded_body = json.dumps(body, allow_nan=False).encode("utf-8") if body is not None else None
    http_request = Request(url, data=encoded_body,
                           headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
                           method="POST" if body is not None else "GET")
    deadline = time.monotonic() + 240
    opener = build_opener(NoRedirect())
    for attempt in range(3):
        try:
            with opener.open(http_request, timeout=45) as response:
                if response.geturl() != url:
                    raise RuntimeError("Redirected reporting responses are not accepted.")
                raw = response.read(MAX_BYTES + 1)
            break
        except HTTPError as error:
            delay = retry_delay(error.headers) if error.code == 429 else 0
            error.close()
            if error.code != 429 or attempt == 2 or delay + 10 > deadline - time.monotonic():
                raise
            time.sleep(max(1, delay))
    if len(raw) > MAX_BYTES:
        raise ValueError("Azure aggregate reporting response exceeds its size limit.")
    return json.loads(raw)


def showback(request):
    scope = request["scope"]
    if str(scope.get("resource_group", "")).casefold() == "all":
        raise ValueError("All is a scope filter, never an Azure resource-group identifier.")
    end = datetime.fromisoformat(scope["window_end"]) - timedelta(seconds=1)
    url = (f"https://management.azure.com/subscriptions/{scope['subscription_id']}/resourceGroups/"
           f"{scope['resource_group']}/providers/Microsoft.CostManagement/query?api-version=2023-03-01")
    response = arm(request, url, {
        "type": "ActualCost", "timeframe": "Custom",
        "timePeriod": {"from": scope["window_start"], "to": end.isoformat()},
        "dataset": {"granularity": "Daily", "aggregation": {"totalCost": {"name": "PreTaxCost", "function": "Sum"}}},
    })
    properties = response["properties"]
    if properties.get("nextLink"):
        raise ValueError("Cost response is paginated; a partial report is not published.")
    columns = [column["name"] for column in properties["columns"]]
    if len(columns) != len(set(columns)) or not set(columns).issubset({"PreTaxCost", "Cost", "UsageDate", "Currency"}):
        raise ValueError("Unsupported cost reporting columns.")
    if "UsageDate" not in columns or "Currency" not in columns or len(set(columns) & {"Cost", "PreTaxCost"}) != 1:
        raise ValueError("Required cost reporting columns are missing.")
    rows, currencies, seen = [], set(), set()
    if len(properties["rows"]) > 10000:
        raise ValueError("Too many daily cost observations.")
    for values in properties["rows"]:
        if len(values) != len(columns):
            raise ValueError("Cost row shape differs from its schema.")
        row = dict(zip(columns, values))
        value = row.get("PreTaxCost", row.get("Cost"))
        if type(value) not in (float, int) or abs(value) > sys.float_info.max or not math.isfinite(value):
            raise ValueError("Cost must be a finite actual observation.")
        day = datetime.strptime(str(row["UsageDate"]), "%Y%m%d").replace(tzinfo=timezone.utc)
        if day in seen:
            raise ValueError("Duplicate daily cost observations are not combined.")
        seen.add(day)
        currency = row["Currency"]
        if not isinstance(currency, str) or len(currency) != 3 or not currency.isascii() or not currency.isalpha():
            raise ValueError("Cost currency is invalid.")
        currencies.add(currency.upper())
        rows.append({"timestamp": day.isoformat(), "resource": scope["resource_group"],
                     "deployment": "Actual cost", "metrics": {"actual_cost": value}})
    if len(currencies) > 1:
        raise ValueError("Different billing currencies cannot be combined.")
    return {
        "contract": CONTRACT, "report_id": "showback",
        **{key: scope[key] for key in ("subscription_id", "resource_group", "workspace_id", "window_start", "window_end")},
        "generated_at": datetime.now(timezone.utc).isoformat(), "daily": rows,
        "currency": next(iter(currencies), None),
        "dataSource": "Cost Management",
        "lineage": {"formula": "Sum daily observed PreTaxCost/Cost at the exact reviewed resource-group scope; no forecast or estimate",
                    "inputs": {"subscriptionId": scope["subscription_id"], "resourceGroup": scope["resource_group"],
                               "windowStart": scope["window_start"], "windowEnd": scope["window_end"], "costBasis": "ActualCost"}},
        "warnings": ["selected_project_cost_only", "cost_data_lag", *([] if rows else ["no_data"])],
    }


def run(request_path):
    request = read_json(request_path)
    if request.get("contract") != CONTRACT or request.get("report_id") not in {"foundry-token", "showback"}:
        raise ValueError("Only the strict token/showback report contract is supported.")
    directory = Path(request_path).resolve().parent
    if request["report_id"] == "showback":
        document = showback(request)
    else:
        scope = request["scope"]
        script = Path(__file__).resolve().parents[4] / "projectteam" / "foundry-usage" / "foundry_usage_report.py"
        sys.argv = [str(script), "--subscription-id", scope["subscription_id"], "--resource-group", scope["resource_group"],
            "--workspace-id", scope["workspace_id"], "--tenant-id", scope["tenant_id"],
            "--expected-object-id", request["object_id"], "--time-zone", "UTC",
            "--as-of-date", request["as_of_date"], "--days", str(request["lookback_days"]),
            "--automation-json", str(directory / "aggregate.json"), "--output", str(directory / "usage.pdf"),
            "--model-requests-output", str(directory / "requests.pdf"), "--foundry-token-output", str(directory / "tokens.pdf")]
        module = runpy.run_path(str(script), run_name="aifactory_report_runtime")
        if module["main"]() != 0:
            raise RuntimeError("Observed token report did not complete.")
        document = read_json(directory / "aggregate.json")
        document["report_id"] = "foundry-token"
        for row in document["daily"]:
            row["metrics"] = {key: value for key, value in row["metrics"].items()
                              if key in {"input_tokens", "output_tokens", "cached_tokens", "tokens"}}
        document["warnings"].append("token_pricing_not_evaluated")
    (directory / "aggregate.json").write_text(json.dumps(document, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    arguments = parser.parse_args()
    try:
        run(arguments.request)
    except HTTPError as error:
        request = read_json(arguments.request)
        scope = request["scope"]
        failure = {"contract": "aifactory.report-error.v1", "report_id": request["report_id"],
                   "subscription_id": scope["subscription_id"], "resource_group": scope["resource_group"],
                   "code": "cost_rate_limited" if error.code == 429 else
                           "cost_access_denied" if error.code in {401, 403} else "cost_query_failed",
                   "retry_after_seconds": retry_delay(error.headers) if error.code == 429 else None}
        (Path(arguments.request).resolve().parent / "report-error.json").write_text(
            json.dumps(failure, allow_nan=False), encoding="utf-8")
        raise SystemExit(1)
