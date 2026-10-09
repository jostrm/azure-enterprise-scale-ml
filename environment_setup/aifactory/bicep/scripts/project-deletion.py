#!/usr/bin/env python3
"""Confirm project deletion through bounded, extension-free ARM observations."""

import argparse
from http import HTTPStatus
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit
from uuid import uuid4


ARM = "https://management.azure.com"
API_VERSIONS = {
    "microsoft.databricks/workspaces": "2024-05-01",
    "microsoft.machinelearningservices/workspaces": "2024-10-01",
    "microsoft.datafactory/factories": "2018-06-01",
    "microsoft.cognitiveservices/accounts": "2025-06-01",
    "microsoft.portal/dashboards": "2020-09-01-preview",
    "microsoft.insights/components": "2020-02-02",
    "microsoft.search/searchservices": "2023-11-01",
    "microsoft.network/privateendpoints": "2024-05-01",
    "microsoft.network/networkinterfaces": "2024-05-01",
}
GROUP_API = "2021-04-01"
NETWORK_API = "2024-05-01"
ML_TYPE = "microsoft.machinelearningservices/workspaces"
ABSENT_CODES = {"ResourceNotFound", "ResourceGroupNotFound"}
CONFLICT_CODES = {"RequestConflict", "AnotherOperationInProgress", "ApplianceBeingDeleted"}
BUSY_STATES = {"creating", "updating", "accepted"}
MAX_DELETE_ATTEMPTS = 3


class DeletionError(Exception):
    def __init__(self, code, message, resource_id="", status="failed"):
        self.code = code
        self.message = sanitize(message)
        self.resource_id = resource_id
        self.status = status
        super().__init__(f"{code}: {self.message}" + (f" [{resource_id}]" if resource_id else ""))


def sanitize(value):
    text = str(value)
    text = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [redacted]", text)
    sensitive = (
        r"access_token|refresh_token|token|sig|signature|client_secret|password|"
        r"authorization|api[_-]?key|accountkey|secret"
    )
    text = re.sub(
        rf"(?i)\b({sensitive})\b[\"']?\s*[:=]\s*(?:\"[^\"]*\"|'[^']*')",
        r"\1=[redacted]", text,
    )
    text = re.sub(
        rf"(?i)\b({sensitive})\b[\"']?\s*[:=]\s*[^\s,;\"']+",
        r"\1=[redacted]", text,
    )
    text = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "[redacted]", text)
    text = re.sub(r"(https?://[^\s?]+)\?[^\s]+", r"\1?[redacted]", text)
    return " ".join(text.split())[:600]


def json_value(text):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON field")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("Nonfinite JSON value")

    return json.loads(text, object_pairs_hook=unique_pairs, parse_constant=invalid_constant)


def azure_error(result, resource_id):
    errors = []
    raw = []
    ambiguous = False
    contradictory_absence = False
    contradictory_conflict = False
    http_reasons = {status.phrase.lower(): status.value for status in HTTPStatus if status.value >= 400}
    for output in (result.stderr, result.stdout):
        text = (output or "").strip()
        if not text:
            continue
        raw.append(text)
        candidate = re.sub(r"^ERROR:\s*", "", text)
        statuses = []
        # Azure CLI core send_raw_request raises HTTPError(reason + '(' + body + ')').
        wrapper = re.fullmatch(r"([A-Za-z][A-Za-z -]*)\((.*)\)", candidate, re.S)
        if wrapper and wrapper.group(1).lower() in http_reasons:
            statuses.append(http_reasons[wrapper.group(1).lower()])
            candidate = wrapper.group(2)
        try:
            value = json_value(candidate)
        except ValueError:
            value = None
        if isinstance(value, dict):
            primary = value.get("error", value)
            for container in (value, primary):
                if not isinstance(container, dict):
                    continue
                status = container.get("statusCode", container.get("status"))
                if isinstance(status, (int, str)) and str(status).isdigit():
                    statuses.append(int(status))
            contradictory_absence |= any(status != 404 for status in statuses)
            contradictory_conflict |= any(status != 409 for status in statuses)
            if isinstance(value.get("error"), dict) and isinstance(value.get("code"), str):
                errors.append((value["code"], value.get("message", "")))
            if isinstance(primary, dict) and isinstance(primary.get("code"), str) and re.fullmatch(
                r"[A-Za-z][A-Za-z0-9_.-]{0,99}", primary["code"]
            ):
                if primary["code"] in ABSENT_CODES | CONFLICT_CODES:
                    for container, keys in (
                        (value, ("errors", "details", "innererror", "innerError")),
                        (primary, ("error", "errors", "details", "innererror", "innerError")),
                    ):
                        if any(container.get(key) not in (None, [], {}) for key in keys):
                            ambiguous = True
                if not isinstance(primary.get("message", ""), str):
                    ambiguous = True
                errors.append((primary["code"], primary.get("message", "")))
                continue
        matches = list(re.finditer(r"^ERROR:\s*\(([A-Za-z][A-Za-z0-9_.-]*)\)", text, re.M))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            errors.append((match.group(1), text[match.end():end].strip()))
        if not matches or re.search(r"^ERROR:(?!\s*\([A-Za-z][A-Za-z0-9_.-]*\))", text, re.M):
            ambiguous = True
    # Never recognize a nested/mentioned not-found code beneath a primary denial.
    codes = {code for code, _ in errors}
    if len(errors) == 1 and not ambiguous and not (
        contradictory_absence and codes & ABSENT_CODES or contradictory_conflict and codes & CONFLICT_CODES
    ):
        return DeletionError(errors[0][0], errors[0][1], resource_id)
    return DeletionError("AzureCLIError", " ".join(raw) or "Azure CLI command failed.", resource_id)


def valid_name(value, label="resource name", maximum=260):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_().-]+", value) or (
        value in {".", ".."} or len(value) > maximum
    ):
        raise DeletionError("InvalidArgument", f"Invalid {label}.")
    return value


def valid_inventory_name(segment, resource_id):
    decoded = segment
    for _ in range(len(segment) + 1):
        if not decoded.strip() or decoded.strip() in {".", ".."} or any(
            character in "/\\?#" or unicodedata.category(character).startswith("C")
            for character in decoded
        ):
            raise DeletionError("MalformedInventory", "Unsafe resource-name segment in ARM inventory.", resource_id)
        unescaped = unquote(decoded)
        if unescaped == decoded:
            return
        decoded = unescaped
    raise DeletionError("MalformedInventory", "Invalid encoded resource-name segment.", resource_id)


def valid_resource_name(resource_type, name):
    kind = resource_type.lower()
    if kind == "microsoft.insights/components":
        if not isinstance(name, str) or not 1 <= len(name) <= 260 or name.endswith((" ", ".")) or any(
            character in "%&" for character in name
        ):
            raise DeletionError("InvalidArgument", "Invalid Application Insights component name.")
        try:
            valid_inventory_name(name, "")
        except DeletionError:
            raise DeletionError("InvalidArgument", "Unsafe Application Insights resource-name segment.") from None
    elif kind == "microsoft.portal/dashboards":
        # A dashboard's hidden-title tag, not its ARM resource name, permits display symbols.
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9-]{3,160}", name):
            raise DeletionError("InvalidArgument", "Dashboard names require 3-160 alphanumeric/hyphen characters.")
    else:
        valid_name(name)


def resource_group_id(subscription, group):
    return f"/subscriptions/{subscription}/resourceGroups/{group}"


def supported_type(value):
    if not isinstance(value, str) or value.lower() not in API_VERSIONS:
        raise DeletionError("UnsupportedResourceType", "Use a supported project resource type.")
    return value


def cli_prefix(executable, *, windows=None):
    if (os.name == "nt" if windows is None else windows) and Path(executable).suffix.lower() in {".cmd", ".bat"}:
        python = Path(executable).parent.parent / "python.exe"
        if python.is_file():
            # Match the MSI launcher without cmd.exe interpreting ARM nextLink '&' arguments.
            return [str(python), "-IBm", "azure.cli"]
    return [executable]


class Deletion:
    def __init__(self, args, *, runner=None, clock=None, sleep=None):
        self.args = args
        self.clock = clock or time.monotonic
        self.sleep = sleep or time.sleep
        self.runner = runner or subprocess.run
        self.deadline = self.clock() + args.timeout_seconds
        self.group_id = resource_group_id(args.subscription, args.resource_group)
        self.active_id = self.group_id
        self.states = {}
        self.diagnostics = []
        self.az = shutil.which("az")
        if self.az is None:
            raise DeletionError("AzureCLIUnavailable", "Azure CLI is required; no extensions are needed.")
        self.cli = cli_prefix(self.az)
        self.environment = os.environ.copy()
        self.environment.update({
            "AZURE_EXTENSION_USE_DYNAMIC_INSTALL": "no",
            "MSYS_NO_PATHCONV": "1",
            "MSYS2_ARG_CONV_EXCL": "*",
        })
        if len(self.cli) > 1:
            self.environment["AZ_INSTALLER"] = "MSI"

    def remaining(self):
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise DeletionError(
                "DeadlineExceeded", "Deletion was not confirmed before the deadline; inspect the remaining resource.",
                self.active_id, "timeout",
            )
        return remaining

    def pause(self):
        self.sleep(min(self.args.poll_seconds, self.remaining()))
        self.remaining()

    def command(self, arguments, resource_id, *, read_json=True, timeout_cap=120):
        self.active_id = resource_id
        command = [*self.cli, *arguments, "--subscription", self.args.subscription,
                   "--only-show-errors", "--output", "json"]
        try:
            result = self.runner(
                command, capture_output=True, text=True, check=False,
                env=self.environment, timeout=min(timeout_cap, self.remaining()),
            )
        except subprocess.TimeoutExpired:
            raise DeletionError(
                "CommandTimeout",
                "Azure CLI timed out; the operation outcome is uncertain. No delete will be resubmitted.",
                resource_id, "timeout",
            ) from None
        except OSError as error:
            raise DeletionError("CommandFailed", str(error), resource_id) from None
        self.remaining()
        if result.returncode:
            raise azure_error(result, resource_id)
        if not read_json:
            return None
        try:
            return json_value(result.stdout)
        except (ValueError, TypeError):
            raise DeletionError("MalformedResponse", "Azure CLI did not return unambiguous JSON.", resource_id) from None

    def rest(self, method, resource_id, version, *, url=None, read_json=True):
        return self.command(
            ["rest", "--method", method, "--url",
             url or f"{ARM}{quote(resource_id, safe='/.-_')}?api-version={version}"],
            resource_id, read_json=read_json,
        )

    def state(self, item):
        properties = item.get("properties", {})
        if properties is None:
            properties = {}
        if not isinstance(properties, dict):
            raise DeletionError("MalformedResponse", "Resource properties must be an object.", item["id"])
        nested = properties.get("provisioningState")
        outer = item.get("provisioningState")
        if nested is not None and outer is not None and nested != outer:
            raise DeletionError("MalformedResponse", "Conflicting provisioning states.", item["id"])
        state = nested if nested is not None else outer if outer is not None else "Unknown"
        if not isinstance(state, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,79}", state):
            raise DeletionError("MalformedResponse", "Invalid provisioning state.", item["id"])
        if state != "Unknown" or item["id"] not in self.states:
            self.states[item["id"]] = state
        return state.lower()

    def validate_item(self, item, group_id, *, collection=None):
        if not isinstance(item, dict) or not all(isinstance(item.get(k), str) for k in ("id", "name", "type")):
            raise DeletionError("MalformedInventory", "Inventory entries require id, name and type.", group_id)
        resource_id = item["id"]
        prefix = group_id + "/providers/"
        if not resource_id.lower().startswith(prefix.lower()):
            raise DeletionError("ScopeMismatch", "Inventory resource is outside the requested group.", group_id)
        named_group = item.get("resourceGroup")
        if named_group is not None and (
            not isinstance(named_group, str) or named_group.lower() != group_id.rsplit("/", 1)[-1].lower()
        ):
            raise DeletionError("ScopeMismatch", "Inventory group field disagrees with its ARM ID.", group_id)
        segments = resource_id[len(prefix):].split("/")
        if len(segments) < 3 or len(segments) % 2 != 1:
            raise DeletionError("MalformedInventory", "Invalid ARM resource ID.", group_id)
        # Extension resources can have another provider namespace inside the same RG.
        provider_index = 0
        namespaces = {0}
        for index in range(3, len(segments), 2):
            if segments[index].lower() == "providers":
                if index + 3 >= len(segments):
                    raise DeletionError("MalformedInventory", "Incomplete extension resource ID.", group_id)
                provider_index = index + 1
                namespaces.add(provider_index)
        for index, segment in enumerate(segments):
            if index in namespaces or index % 2 == 1:
                if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", segment):
                    raise DeletionError("MalformedInventory", "Invalid ARM namespace or resource type.", group_id)
            else:
                valid_inventory_name(segment, group_id)
        provider = segments[provider_index:]
        actual_type = "/".join([provider[0], *provider[1::2]])
        names = provider[2::2]
        if item["type"].lower() != actual_type.lower() or item["name"].lower() not in {
            "/".join(names).lower(), names[-1].lower(),
        }:
            raise DeletionError("MalformedInventory", "Resource name/type does not agree with its ARM ID.", resource_id)
        selected_type = self.args.action == "names" and actual_type.lower() == self.args.resource_type.lower()
        if (actual_type.lower() in API_VERSIONS or selected_type) and resource_id.lower() != (
            f"{group_id}/providers/{actual_type}/{item['name']}".lower()
        ):
            raise DeletionError("ScopeMismatch", "Supported project resources must be directly scoped to the requested group.", resource_id)
        if collection and (
            resource_id.rsplit("/", 1)[0].lower() != collection.lower()
        ):
            raise DeletionError("ScopeMismatch", "Resource is outside the requested collection.", collection)
        self.state(item)
        return item

    def get(self, resource_id, version):
        try:
            item = self.rest("get", resource_id, version)
        except DeletionError as error:
            if error.code in ABSENT_CODES:
                self.states[resource_id] = "Absent"
                return None
            raise
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or (
            item["id"].lower() != resource_id.lower()
        ):
            raise DeletionError("ScopeMismatch", "GET did not return the requested ARM resource.", resource_id)
        if resource_id.lower() == self.group_id.lower():
            if not isinstance(item.get("name"), str) or item["name"].lower() != self.args.resource_group.lower():
                raise DeletionError("MalformedResponse", "GET returned a different resource group name.", resource_id)
        else:
            self.validate_item(item, self.group_id)
        self.state(item)
        return item

    def inventory(self, *, timeout_cap=120):
        try:
            items = self.command(
                ["resource", "list", "--resource-group", self.args.resource_group],
                self.group_id, timeout_cap=timeout_cap,
            )
        except DeletionError as error:
            if error.code == "ResourceGroupNotFound":
                return []
            raise
        if not isinstance(items, list):
            raise DeletionError("MalformedInventory", "Resource list must be a JSON array.", self.group_id)
        seen = set()
        for item in items:
            self.validate_item(item, self.group_id)
            key = item["id"].lower()
            if key in seen:
                raise DeletionError("MalformedInventory", "Duplicate resource ID in inventory.", item["id"])
            seen.add(key)
        return items

    def names(self):
        prefixes = tuple(prefix.lower() for prefix in self.args.prefix)
        return [
            item["name"] for item in self.inventory()
            if item["type"].lower() == self.args.resource_type.lower()
            and (not prefixes or item["name"].lower().startswith(prefixes))
        ]

    def page_url(self, link, collection, version):
        if not isinstance(link, str) or not link:
            raise DeletionError("MalformedPagination", "Invalid nextLink.", collection)
        url = urljoin(ARM + "/", link)
        try:
            parsed = urlsplit(url)
            valid = (
                parsed.scheme == "https" and parsed.netloc.lower() == "management.azure.com"
                and not parsed.fragment
                and unquote(parsed.path).lower() == collection.lower()
                and parse_qs(parsed.query).get("api-version") == [version]
            )
        except ValueError:
            valid = False
        if not valid:
            raise DeletionError("ScopeMismatch", "Pagination must remain on the exact ARM collection and API version.", collection)
        return url

    def collection(self, collection, version, group_id):
        items, seen_ids, seen_urls = [], set(), set()
        url = f"{ARM}{quote(collection, safe='/.-_')}?api-version={version}"
        while url:
            if url in seen_urls:
                raise DeletionError("MalformedPagination", "Repeated continuation link.", collection)
            seen_urls.add(url)
            page = self.rest("get", collection, version, url=url)
            if not isinstance(page, dict) or not isinstance(page.get("value"), list):
                raise DeletionError("MalformedInventory", "REST list must contain a value array.", collection)
            for item in page["value"]:
                self.validate_item(item, group_id, collection=collection)
                key = item["id"].lower()
                if key in seen_ids:
                    raise DeletionError("MalformedInventory", "Duplicate resource across pages.", item["id"])
                seen_ids.add(key)
                items.append(item)
            link = page.get("nextLink")
            url = None if link is None else self.page_url(link, collection, version)
        return items

    def wait_absent(self, resource_id, version, *, deleting=False, group=False):
        while True:
            item = self.get(resource_id, version)
            if item is None:
                return
            state = self.state(item)
            if state == "deleting":
                deleting = True
            elif (deleting and state not in BUSY_STATES) or state in {"failed", "canceled", "cancelled"}:
                raise DeletionError(
                    "GroupDeletionFailed" if group else "ResourceDeletionFailed",
                    f"Deletion rollback or failure: provider state is {state}. "
                    "Inspect the resource and unblock the provider before another explicit deletion.",
                    resource_id,
                )
            self.pause()

    def wait_ready(self, resource_id, version, item):
        while item is not None and self.state(item) in BUSY_STATES:
            self.pause()
            item = self.get(resource_id, version)
        return item

    def delete_resource(self, resource_id, version, *, ml_workspace=False):
        item = self.wait_ready(resource_id, version, self.get(resource_id, version))
        if item is None:
            return
        if self.state(item) == "deleting":
            self.wait_absent(resource_id, version, deleting=True)
            return
        if ml_workspace:
            endpoints = self.collection(resource_id + "/onlineEndpoints", version, self.group_id)
            for endpoint in endpoints:
                self.delete_resource(endpoint["id"], version)
            item = self.wait_ready(resource_id, version, self.get(resource_id, version))
            if item is None:
                return
            if self.state(item) == "deleting":
                self.wait_absent(resource_id, version, deleting=True)
                return
        for attempt in range(MAX_DELETE_ATTEMPTS):
            try:
                self.rest("delete", resource_id, version, read_json=False)
            except DeletionError as error:
                if error.code in ABSENT_CODES:
                    self.wait_absent(resource_id, version)
                    return
                if error.code not in CONFLICT_CODES:
                    raise
                item = self.get(resource_id, version)
                if item is None:
                    return
                if self.state(item) == "deleting":
                    self.wait_absent(resource_id, version, deleting=True)
                    return
                if attempt + 1 >= MAX_DELETE_ATTEMPTS:
                    raise error
                self.pause()
                item = self.wait_ready(resource_id, version, self.get(resource_id, version))
                if item is None:
                    return
                if self.state(item) == "deleting":
                    self.wait_absent(resource_id, version, deleting=True)
                    return
            else:
                self.wait_absent(resource_id, version)
                return

    def resource(self):
        resource_id = f"{self.group_id}/providers/{self.args.resource_type}/{self.args.name}"
        self.delete_resource(
            resource_id, API_VERSIONS[self.args.resource_type.lower()],
            ml_workspace=self.args.resource_type.lower() == ML_TYPE,
        )

    def query_state(self):
        resource_id = f"{self.group_id}/providers/{self.args.resource_type}/{self.args.name}"
        item = self.get(resource_id, API_VERSIONS[self.args.resource_type.lower()])
        if item is None:
            return "absent"
        state = self.state(item)
        if state in {"unknown", "absent"}:
            raise DeletionError(
                "UnknownProvisioningState", "GET did not establish the resource's provisioning state.", resource_id,
            )
        return state

    def diagnose_group(self):
        # Diagnostics share the original deadline and cannot replace its primary error.
        if self.deadline <= self.clock():
            return
        try:
            inventory = self.inventory(timeout_cap=5)
            remaining = [{"id": item["id"], "state": self.states[item["id"]]} for item in inventory]
            self.diagnostics.append({"remaining": remaining})
            for item in remaining:
                print(f"Remaining: {item['id']} state={item['state']}", file=sys.stderr)
        except DeletionError as error:
            self.diagnostics.append({"inventory_error": str(error)})
        if self.deadline <= self.clock():
            return
        try:
            events = self.command(
                ["monitor", "activity-log", "list", "--resource-group", self.args.resource_group,
                 "--offset", "1h", "--max-events", "10"],
                self.group_id, timeout_cap=5,
            )
            if not isinstance(events, list):
                raise DeletionError("MalformedResponse", "Activity log must be an array.", self.group_id)
            for event in events[:10]:
                if not isinstance(event, dict):
                    continue
                properties = event.get("properties", {})
                if isinstance(properties, dict) and properties.get("statusMessage"):
                    message = sanitize(properties["statusMessage"])
                    self.diagnostics.append({"activity_error": message})
                    print(f"Activity: {message}", file=sys.stderr)
        except DeletionError as error:
            self.diagnostics.append({"activity_error": str(error)})

    def watch_group(self, *, deleting=False):
        try:
            self.wait_absent(self.group_id, GROUP_API, deleting=deleting, group=True)
        except DeletionError:
            self.diagnose_group()
            raise

    def group(self):
        item = self.get(self.group_id, GROUP_API)
        if item is None:
            return
        if self.state(item) == "deleting":
            self.watch_group(deleting=True)
            return
        for resource in self.inventory():
            version = API_VERSIONS.get(resource["type"].lower())
            if version is None:
                continue
            resource_id = resource["id"]
            current = self.wait_ready(resource_id, version, self.get(resource_id, version))
            if current is not None and self.state(current) == "deleting":
                self.wait_absent(resource_id, version, deleting=True)
        item = self.wait_ready(self.group_id, GROUP_API, self.get(self.group_id, GROUP_API))
        if item is None:
            return
        if self.state(item) == "deleting":
            self.watch_group(deleting=True)
            return
        self.command(
            ["group", "delete", "--name", self.args.resource_group, "--yes", "--no-wait"],
            self.group_id, read_json=False,
        )
        self.watch_group()

    def verify_network(self):
        group_id = resource_group_id(self.args.subscription, self.args.network_resource_group)
        vnets_path = group_id + "/providers/Microsoft.Network/virtualNetworks"
        nsgs_path = group_id + "/providers/Microsoft.Network/networkSecurityGroups"
        token = f"prj{self.args.project_number}-".lower()
        remaining = []
        for vnet in self.collection(vnets_path, NETWORK_API, group_id):
            for subnet in self.collection(vnet["id"] + "/subnets", NETWORK_API, group_id):
                if token in subnet["id"].rsplit("/", 1)[-1].lower():
                    remaining.append(subnet["id"])
        for nsg in self.collection(nsgs_path, NETWORK_API, group_id):
            if token in nsg["name"].lower():
                remaining.append(nsg["id"])
        if remaining:
            for resource_id in remaining:
                print(f"Remaining project network resource: {resource_id}", file=sys.stderr)
            raise DeletionError(
                "ProjectNetworkResourcesRemain",
                f"{len(remaining)} project subnet(s)/NSG(s) remain; no network resources were modified.",
                remaining[0],
            )


def bounded_seconds(maximum):
    def parse(value):
        try:
            number = float(value)
        except ValueError:
            raise argparse.ArgumentTypeError("Expected positive seconds.") from None
        if not math.isfinite(number) or not 0 < number <= maximum:
            raise argparse.ArgumentTypeError(f"Seconds must be positive and at most {maximum}.")
        return number
    return parse


def arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--timeout-seconds", default=1800, type=bounded_seconds(86400))
    parser.add_argument("--poll-seconds", default=15, type=bounded_seconds(300))
    parser.add_argument("--report-dir")
    commands = parser.add_subparsers(dest="action", required=True)
    names = commands.add_parser("names", help="List authoritative matching project resource names.")
    names.add_argument("--resource-type", required=True)
    names.add_argument("--prefix", action="append", default=[])
    resource = commands.add_parser("resource", help="Delete one supported resource and confirm absence.")
    resource.add_argument("--resource-type", required=True)
    resource.add_argument("--name", required=True)
    state = commands.add_parser("state", help="Read one resource's lowercase provisioning state or confirmed absence.")
    state.add_argument("--resource-type", required=True)
    state.add_argument("--name", required=True)
    group = commands.add_parser("group", help="Delete only the explicitly confirmed project resource group.")
    group.add_argument("--confirm-resource-group", required=True)
    network = commands.add_parser("verify-network", help="Read-only verification of project network cleanup.")
    network.add_argument("--network-resource-group", required=True)
    network.add_argument("--project-number", required=True)
    return parser.parse_args(argv)


def validate_arguments(args):
    if not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", args.subscription):
        raise DeletionError("InvalidArgument", "--subscription must be a subscription GUID.")
    valid_name(args.resource_group, "resource group", 90)
    if args.action in {"resource", "state"}:
        supported_type(args.resource_type)
    if args.action == "names":
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*/[A-Za-z][A-Za-z0-9_.-]*", args.resource_type):
            raise DeletionError("InvalidArgument", "--resource-type must be a top-level ARM provider/type.")
        for prefix in args.prefix:
            valid_name(prefix, "name prefix")
    if args.action in {"resource", "state"}:
        valid_resource_name(args.resource_type, args.name)
    if args.action == "group" and args.confirm_resource_group != args.resource_group:
        raise DeletionError("ConfirmationMismatch", "--confirm-resource-group must exactly equal --resource-group.")
    if args.action == "verify-network":
        valid_name(args.network_resource_group, "network resource group", 90)
        if not re.fullmatch(r"[0-9]{3}", args.project_number):
            raise DeletionError("InvalidArgument", "--project-number must contain exactly three digits.")


def write_report(args, client, error):
    if not args.report_dir:
        return
    report = {
        "action": args.action, "subscription": args.subscription, "resource_group": args.resource_group,
        "status": error.status if error else "succeeded",
        "states": client.states if client else {},
        "diagnostics": client.diagnostics if client else [],
    }
    if error:
        report["error"] = {"code": error.code, "message": error.message, "resource_id": error.resource_id}
    folder = Path(args.report_dir)
    folder.mkdir(parents=True, exist_ok=True)
    label = args.action
    if args.action in {"resource", "names", "state"}:
        label += "-" + args.resource_type + "-" + getattr(args, "name", "inventory")
    label = re.sub(r"[^A-Za-z0-9_.-]", "-", label)[:200]
    for filename in ("deletion-" + label + ".json", "last-deletion.json"):
        pending = folder / (filename + "." + uuid4().hex + ".part")
        try:
            pending.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            os.replace(pending, folder / filename)
        finally:
            pending.unlink(missing_ok=True)


def main(argv=None, *, runner=None, clock=None, sleep=None):
    args = arguments(argv)
    client, error, names = None, None, None
    try:
        validate_arguments(args)
        client = Deletion(args, runner=runner, clock=clock, sleep=sleep)
        if args.action == "names":
            names = client.names()
        elif args.action == "state":
            names = [client.query_state()]
        else:
            getattr(client, args.action.replace("-", "_"))()
    except DeletionError as failure:
        error = failure
        print(str(failure), file=sys.stderr)
    try:
        write_report(args, client, error)
    except OSError as failure:
        print(f"ReportWriteFailed: {sanitize(failure)}", file=sys.stderr)
        return 1
    if error:
        return 1
    if names:
        print("\n".join(names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
