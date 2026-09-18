"""Read-only report adapters. Imports and sample reports require only Python's stdlib."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import uuid


SCRIPTS = {
    "foundry-tokens": Path("coreteam") / "finops" / "runbooks" / "Update-FoundryTokenReport.ps1",
    "showback": Path("coreteam") / "finops" / "runbooks" / "showback" / "Update-ShowbackReport.ps1",
    "foundry-usage": Path("projectteam") / "foundry-usage" / "foundry_usage_report.py",
}
RUNBOOKS = {"foundry-tokens": "Update-FoundryTokenReport", "showback": "Update-ShowbackReport"}
ARM = "https://management.azure.com"
AUTOMATION_API = "2023-11-01"
LOGIC_API = "2016-06-01"
RESOURCE = re.compile(
    r"/subscriptions/([0-9a-f-]{36})/resourceGroups/([A-Za-z0-9_.()-]+)/providers/"
    r"(Microsoft\.Automation/automationAccounts/[A-Za-z0-9_-]+(?:/runbooks/[A-Za-z0-9_-]+)?"
    r"|Microsoft\.Logic/workflows/[A-Za-z0-9_-]+)", re.I
)


class ReportError(Exception):
    def __init__(self, message, status="failed"):
        super().__init__(message)
        self.status = status


def _folder(folder):
    root = Path(folder).expanduser().resolve()
    for candidate in (root, root / "automation", root / "aifactory" / "automation"):
        if (candidate / SCRIPTS["foundry-tokens"]).is_file():
            return candidate
    raise ReportError("Selected folder does not contain the AI Factory report automation.", "unavailable")


def discover(folder):
    root = _folder(folder)
    return [
        {"report_type": kind, "path": str(root / relative), "compute": ["local", "runbook", "logicapp"] if kind in RUNBOOKS else ["local"]}
        for kind, relative in SCRIPTS.items() if (root / relative).is_file()
    ]


def plan(folder, report_type, project_number, environment, days, compute="local",
         cloud_resource_id=None, dry_run=False):
    """Offline skeleton; callers must supply exact subscription/tenant/RGs before live execution."""
    root = _folder(folder)
    if report_type not in SCRIPTS:
        raise ReportError("Unsupported report type.")
    config_path = (root / SCRIPTS[report_type]).with_name("report-config.json")
    config = json.loads(config_path.read_text(encoding="utf-8-sig")) if config_path.exists() else {}
    naming = config.get("naming", {}).copy()
    naming.update(projectNumber="" if str(project_number).casefold() == "all" else str(project_number), env=environment)
    config["naming"] = naming
    return {
        "version": 1, "action": "run", "compute": compute, "report_type": report_type,
        "factory_folder": str(root), "target": {
            "subscription_id": "", "tenant_id": "", "project_number": str(project_number),
            "environment": environment, "project_resource_group": "", "common_resource_group": "",
            "naming": naming,
        }, "days": days, "dry_run": dry_run, "cloud_resource_id": cloud_resource_id,
        "run_id": None, "report_config": config,
        "filters": {"aiFactory": "All", "scaleset": "All", "project": "All"},
    }


def _result(request, state, message="", report=None, run_id=None, **extra):
    return {
        "status": state, "source": "sample" if request.get("dry_run") else "live",
        "compute": request.get("compute", "local"), "run_id": run_id,
        "output": report.get("output", "") if report else message,
        "report": report, "warnings": list(report.get("warnings", [])) if report else ([message] if message else []),
        **extra,
    }


def _guid(value, label):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise ReportError(f"{label} must be a valid UUID.") from None


def _validate(request):
    request = deepcopy(request)
    if type(request.get("version")) is not int or request["version"] != 1 or request.get("action", "run") not in ("run", "status"):
        raise ReportError("Unsupported report request version or action.")
    if request.get("compute") not in ("local", "runbook", "logicapp") or request.get("report_type") not in SCRIPTS:
        raise ReportError("Unsupported report type or compute.")
    if type(request.get("days")) is not int or not 1 <= request["days"] <= 90:
        raise ReportError("Report days must be between 1 and 90.")
    if type(request.get("dry_run", False)) is not bool:
        raise ReportError("dry_run must be a boolean.")
    if not isinstance(request.get("factory_folder"), str):
        raise ReportError("factory_folder must be an explicit path.")
    root = _folder(request["factory_folder"])
    request["factory_folder"] = str(root)
    target = request.get("target")
    if not isinstance(target, dict) or not isinstance(request.get("report_config"), dict):
        raise ReportError("Exact target and report_config objects are required.")
    for field in ("project_number", "environment"):
        if not isinstance(target.get(field), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", target[field]):
            raise ReportError(f"Invalid target {field}.")
        if target[field].casefold() == "all":
            raise ReportError("This on-demand collector requires one concrete project/environment. "
                              "All is supported only over already collected authorized rows; "
                              "collect each reviewed target separately or use native_monitoring.py. "
                              "No Azure resource named All will be queried.", "unavailable")
    filters = request.setdefault("filters", {"aiFactory": "All", "scaleset": "All", "project": "All"})
    if not isinstance(filters, dict) or set(filters) - {"aiFactory", "scaleset", "project"}:
        raise ReportError("Invalid report scope filters.")
    for key, selected in filters.items():
        if not isinstance(selected, str) or not selected:
            raise ReportError("Scope filters must be non-empty strings.")
        known = target.get("factory", target.get("aiFactory")) if key == "aiFactory" else target.get("project_number" if key == "project" else key)
        if selected.casefold() != "all" and selected != known:
            raise ReportError("Selected scope does not match this collector's exact reviewed target; "
                              "unknown scope cannot match a concrete filter.", "unavailable")
    if not request.get("dry_run"):
        for field in ("subscription_id", "tenant_id"):
            target[field] = _guid(target.get(field), field)
        for field in ("project_resource_group", "common_resource_group"):
            if (not isinstance(target.get(field), str) or not re.fullmatch(r"[A-Za-z0-9_.()-]{1,90}", target[field])
                    or target[field].casefold() == "all"):
                raise ReportError(f"Exact target {field} is required.")
    config = request["report_config"]
    if not isinstance(config.get("naming", {}), dict) or not isinstance(target.get("naming", {}), dict):
        raise ReportError("Report naming must be an object.")
    if "showback" in config and not isinstance(config["showback"], dict):
        raise ReportError("Showback configuration must be an object.")
    # Credentials never belong in a report request or an Automation job's parameter history.
    def check_config(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if re.search(r"(password|secret|credential|connectionstring|access.?token|api.?key|sas.?url)", key, re.I):
                    raise ReportError("Report configuration must not contain credentials, secrets or callback URLs.")
                check_config(item)
        elif isinstance(value, list):
            for item in value:
                check_config(item)
        elif isinstance(value, float) and not math.isfinite(value):
            raise ReportError("Report configuration contains a non-finite number.")
    config["naming"] = {**config.get("naming", {}), **target.get("naming", {}),
                        "projectNumber": target["project_number"], "env": target["environment"]}
    check_config(config)
    if "showback" in config:
        config["showback"]["uploadToLake"] = False
    return request


@contextmanager
def _workspace():
    with tempfile.TemporaryDirectory(prefix=".report-compute-", dir=Path.cwd()) as temporary:
        yield Path(temporary)


def _process(command, timeout=180):
    try:
        with tempfile.TemporaryFile(dir=Path.cwd()) as output, tempfile.TemporaryFile(dir=Path.cwd()) as errors:
            process = subprocess.run(command, stdout=output, stderr=errors, stdin=subprocess.DEVNULL,
                                     timeout=timeout, shell=False, check=False)
            output.seek(0)
            errors.seek(0)
            stdout, stderr = output.read(2 * 1024 * 1024 + 1), errors.read(2 * 1024 * 1024 + 1)
            if len(stdout) > 2 * 1024 * 1024 or len(stderr) > 2 * 1024 * 1024:
                raise ReportError("Report command exceeded the 2 MiB output limit.")
            return subprocess.CompletedProcess(command, process.returncode,
                                               stdout.decode("utf-8", errors="replace"),
                                               stderr.decode("utf-8", errors="replace"))
    except FileNotFoundError:
        raise ReportError("Optional report runtime is not installed.", "unavailable") from None
    except subprocess.TimeoutExpired:
        raise ReportError("Report command timed out; no automatic retry was performed.") from None


def _az_command():
    executable = shutil.which("az")
    if executable:
        path = Path(executable)
        if path.suffix.lower() not in (".cmd", ".bat"):
            return [str(path)]
        # Azure CLI's official Windows installation bundles its own interpreter.
        for parent in (path.parent, path.parent.parent):
            python = parent / "python.exe"
            if python.is_file():
                return [str(python), "-m", "azure.cli"]
    if not getattr(sys, "frozen", False):
        try:
            if importlib.util.find_spec("azure.cli") is not None:
                return [sys.executable, "-m", "azure.cli"]
        except ModuleNotFoundError:
            pass
    raise ReportError("Azure CLI is optional but required for cloud compute and live Python usage reports.", "unavailable")


def _az(args, json_output=True):
    process = _process(_az_command() + args + ["--only-show-errors", "--output", "json"], timeout=120)
    if process.returncode:
        raise ReportError("Azure CLI request failed. Verify sign-in, selected tenant/subscription and report-only RBAC.")
    if not json_output:
        try:
            return json.loads(process.stdout)
        except ValueError:
            return process.stdout
    try:
        return json.loads(process.stdout)
    except ValueError:
        raise ReportError("Azure CLI returned an invalid JSON response.") from None


def _verify_account(request):
    account = _az(["account", "show"])
    target = request["target"]
    if str(account.get("id", "")).lower() != target["subscription_id"].lower() or str(account.get("tenantId", "")).lower() != target["tenant_id"].lower():
        raise ReportError("Current Azure CLI subscription/tenant does not match the selected target. Select the exact account first.")


def _resource(resource_id, request, kind):
    match = RESOURCE.fullmatch(resource_id or "")
    if not match or match[1].lower() != request["target"]["subscription_id"].lower():
        raise ReportError("Cloud resource ID must be a supported ARM resource in the selected subscription.")
    segment = match[3].lower()
    if kind == "runbook":
        expected = "/runbooks/" + RUNBOOKS[request["report_type"]].lower()
        if not segment.startswith("microsoft.automation/") or not segment.endswith(expected):
            raise ReportError("Only the matching known report runbook may be invoked.")
    elif kind == "account":
        if not segment.startswith("microsoft.automation/") or "/runbooks/" in segment:
            raise ReportError("Invalid report Automation Account resource ID.")
    elif not segment.startswith("microsoft.logic/workflows/"):
        raise ReportError("Only a dedicated report-dispatch Logic App is supported.")
    return resource_id


def _rest(method, resource_id, api=AUTOMATION_API, body=None, raw=False):
    uri = ARM + resource_id + "?api-version=" + api
    args = ["rest", "--method", method, "--url", uri]
    if body is None:
        return _az(args, json_output=not raw)
    with _workspace() as work:
        payload = work / "body.json"
        payload.write_text(json.dumps(body, allow_nan=False), encoding="utf-8")
        return _az(args + ["--body", "@" + str(payload), "--headers", "Content-Type=application/json"], json_output=not raw)


def _parameters(request):
    target = request["target"]
    return {
        "ConfigJson": json.dumps(request["report_config"], separators=(",", ":"), allow_nan=False),
        "ReportFormat": "Json", "NoUpload": "true", "SubscriptionId": target["subscription_id"],
        "TenantId": target["tenant_id"], "ProjectNumber": target["project_number"],
        "ProjectResourceGroup": target["project_resource_group"],
        "CommonResourceGroup": target["common_resource_group"], "Env": target["environment"],
        "LookbackDays": str(request["days"]),
    }


def _check_runbook(request, resource_id):
    runbook = _rest("get", resource_id)
    parameters = {key.lower() for key in runbook.get("properties", {}).get("parameters", {})}
    if not set(key.lower() for key in _parameters(request)) <= parameters:
        raise ReportError("Published runbook lacks the safe JSON/NoUpload/target protocol. Publish the updated report script first; existing schedules need no changes.", "unavailable")
    if runbook.get("properties", {}).get("state", "").lower() != "published":
        raise ReportError("Selected report runbook is not published.", "unavailable")


def _accept_report(request, report, run_id=None, **extra):
    if not isinstance(report, dict) or report.get("schema_version") != 1 or report.get("report_type") != request["report_type"]:
        raise ReportError("Report output does not implement the expected JSON protocol.", "unavailable")
    if report.get("source") != ("sample" if request.get("dry_run") else "live"):
        raise ReportError("Report source does not match the requested live/sample mode.")
    for key in ("subscription_id", "project_resource_group", "common_resource_group", "environment"):
        expected = request["target"].get(key, "")
        if expected and str(report.get("target", {}).get(key, "")).lower() != str(expected).lower():
            raise ReportError("Returned report target does not match the selected target.")
    if report.get("status") not in ("completed", "warning", "failed") or not isinstance(report.get("output"), str):
        raise ReportError("Report returned invalid status or output.")
    for key in ("tables", "charts", "warnings"):
        if not isinstance(report.get(key), list):
            raise ReportError("Report returned invalid structured content.")
    sources = {
        "showback": ("Cost Management", "ActualCost: sum returned Cost by validated resource group and currency; forecast is separate, never billed actual."),
        "foundry-tokens": ("Log Analytics workspace; Calculated", "Account input/output token sums; TPM = tokens / window minutes. PAYGO/PTU estimates use explicit configured rates, discount, cache rate and capacity, not billed cost or business value."),
        "foundry-usage": ("Azure Monitor metrics; Log Analytics workspace; Application Insights", "Sum observed resource/deployment/day metrics; hourly session sums are not distinct period sessions. Missing observations remain unavailable."),
    }
    source, formula = sources[request["report_type"]]
    if request.get("dry_run"):
        source = "Sample fixture (not live): " + source
    lineage = {"dataSource": source, "formula": formula, "inputs": {
        "target": deepcopy(request["target"]), "period": deepcopy(report.get("period", {})),
        "configuration": deepcopy(request["report_config"]),
    }}
    report.setdefault("dataSource", source)
    report.setdefault("lineage", lineage)
    report["filters"] = deepcopy(request["filters"])
    report["scope_limitation"] = "All means all rows collected for this one reviewed target, not subscription-wide discovery."
    for item in [*report["tables"], *report["charts"]]:
        item.setdefault("dataSource", source)
        item.setdefault("lineage", lineage)
    if "Data source:" not in report["output"]:
        report["output"] += f"\n\nData source: {source}\n\nCalculation: {formula}"
    return _result(request, report["status"], report=report, run_id=run_id, **extra)


def _sample(request):
    kind = request["report_type"]
    warnings = ["SAMPLE DATA ONLY. No Azure authentication, report scripts, uploads or cloud jobs were invoked."]
    if kind == "foundry-tokens":
        columns = ["Metric", "Value", "Unit"]
        rows = [["Input tokens", 120000, "tokens"], ["Output tokens", 8000, "tokens"], ["Requests", 600, "requests"]]
        warnings.append("Pricing and PTU estimates require configured rates and assumptions; sample usage is not actual billing.")
        chart = {"title": "Sample tokens", "labels": ["Input", "Output"], "series": [{"name": "Tokens", "values": [120000, 8000]}]}
    elif kind == "showback":
        columns = ["Project", "Current sample cost", "Forecast sample cost"]
        rows = [[request["target"]["project_number"], 640.1, 1490.0]]
        chart = {"title": "Sample costs (not actual billing)", "labels": ["Current", "Forecast"], "series": [{"name": "Sample cost", "values": [640.1, 1490.0]}]}
    else:
        columns = ["Day", "Requests", "Input tokens", "Output tokens", "Sessions"]
        rows = [[datetime.now(timezone.utc).date().isoformat(), 600, 120000, 8000, None]]
        chart = {"title": "Sample daily requests", "labels": [rows[0][0]], "series": [{"name": "Requests", "values": [600]}]}
        warnings.append("Sessions are unavailable in this sample; missing measurements are not zero.")
    now = datetime.now(timezone.utc)
    report = {
        "schema_version": 1, "report_type": kind, "source": "sample", "generated_at": now.isoformat(),
        "period": {"days": request["days"], "start": (now - timedelta(days=request["days"])).isoformat(), "end": now.isoformat()},
        "target": {key: request["target"].get(key, "") for key in ("subscription_id", "project_resource_group", "common_resource_group", "environment")},
        "status": "warning", "warnings": warnings,
        "tables": [{"title": "Sample report", "columns": columns, "rows": rows}], "charts": [chart],
        "output": f"# {kind} — SAMPLE DATA\n\n" + "\n\n".join(warnings),
    }
    return _accept_report(request, report)


def _local(request):
    root = Path(request["factory_folder"])
    if request["report_type"] == "foundry-usage":
        return _usage(request)
    pwsh = shutil.which("pwsh")
    if not pwsh:
        raise ReportError("PowerShell 7 is optional but required for live PowerShell reports.", "unavailable")
    helper = root / "report-local.ps1"
    if not helper.is_file():
        raise ReportError("Selected factory is missing the local reporting helper.", "unavailable")
    with _workspace() as work:
        path = work / "request.json"
        path.write_text(json.dumps(request, allow_nan=False), encoding="utf-8")
        process = _process([pwsh, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(helper), "-RequestPath", str(path)])
    try:
        report = json.loads(process.stdout.lstrip("\ufeff"))
    except ValueError:
        raise ReportError("PowerShell did not return a JSON report. Check optional Az modules and the selected report version.") from None
    if isinstance(report, dict) and report.get("report") is None and report.get("status") == "failed":
        return _result(request, "failed", report.get("output", "Local report failed."))
    result = _accept_report(request, report)
    if process.returncode and result["status"] != "failed":
        return _result(request, "failed", "Report process failed; partial output was not accepted.")
    return result


def _usage(request):
    if getattr(sys, "frozen", False):
        raise ReportError(
            "Live Python usage reports are unavailable in the packaged application. "
            "Run this adapter with a regular Python interpreter and the optional foundry-usage "
            "requirements instead. PowerShell reports and saved-report viewing are unaffected.",
            "unavailable",
        )
    root = Path(request["factory_folder"])
    script = root / SCRIPTS["foundry-usage"]
    if "--tenant-id" not in script.read_text(encoding="utf-8"):
        raise ReportError("Python usage script lacks exact tenant/CLI credential support; update it first.", "unavailable")
    probe = _process([sys.executable, "-c", "import azure.identity, azure.mgmt.monitor, azure.mgmt.resource, azure.monitor.query, reportlab"])
    if probe.returncode:
        raise ReportError("Optional Python usage dependencies are missing. Install projectteam/foundry-usage/requirements.txt in this interpreter to run this report; viewing and other reports do not require them.", "unavailable")
    _verify_account(request)
    target = request["target"]
    warnings = ["Session counts represent summed hourly activity, not period-wide distinct users or sessions."]
    workspace_id = request["report_config"].get("workspace_id")
    if workspace_id:
        workspace_id = _guid(workspace_id, "workspace_id")
        # Never query an arbitrary workspace outside the explicitly selected common RG.
        workspaces = _rest("get", f"/subscriptions/{target['subscription_id']}/resourceGroups/{target['common_resource_group']}/providers/Microsoft.OperationalInsights/workspaces", api="2022-10-01")
        if not any(str(item.get("properties", {}).get("customerId", "")).lower() == workspace_id for item in workspaces.get("value", [])):
            raise ReportError("Configured Log Analytics workspace is not in the selected common resource group.")
    with _workspace() as work:
        data_path = work / "aggregate.json"
        command = [sys.executable, str(script), "--subscription-id", target["subscription_id"],
                   "--tenant-id", target["tenant_id"], "--resource-group", target["project_resource_group"],
                   "--days", str(request["days"]), "--output", str(work / "usage.pdf"),
                   "--debug-json", str(data_path)]
        if workspace_id:
            command += ["--workspace-id", workspace_id]
        process = _process(command)
        if process.returncode or not data_path.is_file():
            raise ReportError("Python usage report failed. Verify optional packages, selected Azure CLI context, telemetry and resource access.")
        data = json.loads(data_path.read_text(encoding="utf-8"))
    warnings.extend(data.get("warnings", []))
    if process.stderr and not data.get("warnings"):
        warnings.append("Usage script reported diagnostic messages; measurements may be incomplete.")
    metrics = ["requests", "input_tokens", "output_tokens", "cached_tokens", "sessions"]
    tables = []
    daily = {}
    for period in ("daily", "hourly"):
        rows = []
        for key, values in sorted(data.get(period, {}).items()):
            parts = key.split("|", 2)
            if len(parts) != 3:
                continue
            row = parts + [values.get(metric) for metric in metrics]
            if not data.get("sessions_available"):
                row[-1] = None
            rows.append(row)
            if period == "daily":
                bucket = daily.setdefault(parts[0], {})
                for metric in metrics[:-1]:
                    if metric in values:
                        bucket[metric] = bucket.get(metric, 0) + values[metric]
        tables.append({"title": period.title() + " aggregate usage", "columns": ["Period", "Resource", "Deployment"] + metrics, "rows": rows})
    if not any(table["rows"] for table in tables):
        warnings.append("No usage records returned; this is not evidence of zero usage.")
    labels = sorted(daily)
    report = {
        "schema_version": 1, "report_type": "foundry-usage", "source": "live",
        "generated_at": datetime.now(timezone.utc).isoformat(), "period": data.get("period", {"days": request["days"]}),
        "target": {key: target[key] for key in ("subscription_id", "project_resource_group", "common_resource_group", "environment")},
        "status": "warning" if warnings else "completed", "warnings": warnings, "tables": tables,
        "charts": [{"title": "Daily aggregate usage", "labels": labels, "series": [
            {"name": metric, "values": [daily[label].get(metric) for label in labels]} for metric in metrics[:-1]
        ]}],
        "output": "# Foundry usage report\n\nDaily and hourly aggregate telemetry. Missing values are unavailable, not zero.\n\n" + "\n\n".join(warnings),
    }
    return _accept_report(request, report)


def _logic_account(request):
    resource = _resource(request.get("cloud_resource_id"), request, "logicapp")
    workflow = _rest("get", resource, LOGIC_API)
    tags = workflow.get("tags", {})
    if tags.get("aifactory-purpose") != "report-dispatch" or tags.get("aifactory-report-protocol") != "1":
        raise ReportError("Logic App is not a tagged report-dispatch workflow. Network-throttling workflows must never be invoked.")
    properties = workflow.get("properties", {})
    access = properties.get("accessControl", {}).get("triggers", {})
    if access.get("sasAuthenticationPolicy", {}).get("state") != "Disabled":
        raise ReportError("Report-dispatch Logic App must disable SAS authentication and use Entra OAuth.")
    policies = access.get("openAuthenticationPolicies", {}).get("policies", {})
    expected_issuer = "https://sts.windows.net/" + request["target"]["tenant_id"] + "/"
    if not any(
        policy.get("type") == "AAD"
        and {claim.get("name"): claim.get("value") for claim in policy.get("claims", [])}.get("iss") == expected_issuer
        and {claim.get("name"): claim.get("value") for claim in policy.get("claims", [])}.get("aud") == "https://management.core.windows.net/"
        for policy in policies.values()
    ):
        raise ReportError("Report-dispatch OAuth policy does not match the selected tenant and ARM audience.")
    account = properties.get("parameters", {}).get("automationAccountResourceId", {}).get("value")
    return _resource(account, request, "account")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ReportError("Report endpoint redirects are not allowed.")


def _invoke_logic(request, job_id, account):
    resource = request["cloud_resource_id"]
    callback = _rest("post", resource + "/triggers/manual/listCallbackUrl", LOGIC_API)
    url = urlsplit(callback.get("value", ""))
    if (url.scheme != "https" or not re.fullmatch(r"prod-[0-9]+\.[a-z0-9-]+\.logic\.azure\.com", url.hostname or "")
            or url.port not in (None, 443) or url.username or url.password or url.fragment
            or not re.fullmatch(r"/workflows/[a-fA-F0-9]+(?:/versions/[0-9]+)?/triggers/manual/paths/invoke", url.path)):
        raise ReportError("Azure returned an unsupported report-dispatch endpoint.")
    # listCallbackUrl is only for discovery. SAS values never leave this process or get invoked.
    query = [(key, value) for key, value in parse_qsl(url.query) if key == "api-version"]
    endpoint = urlunsplit((url.scheme, url.netloc, url.path, urlencode(query), ""))
    token = _az(["account", "get-access-token", "--resource", "https://management.core.windows.net/",
                 "--tenant", request["target"]["tenant_id"], "--subscription", request["target"]["subscription_id"]])
    if (not isinstance(token, dict) or not isinstance(token.get("accessToken"), str)
            or not re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", token["accessToken"])
            or str(token.get("tenant", "")).casefold() != request["target"]["tenant_id"].casefold()
            or str(token.get("subscription", "")).casefold() != request["target"]["subscription_id"].casefold()):
        raise ReportError("Report-dispatch token does not match the requested subscription/tenant.")
    payload = {"version": 1, "report_type": request["report_type"], "job_id": job_id, "parameters": _parameters(request)}
    call = Request(endpoint, data=json.dumps(payload).encode("utf-8"), method="POST",
                   headers={"Content-Type": "application/json", "Authorization": "Bearer " + token["accessToken"]})
    try:
        with build_opener(_NoRedirect).open(call, timeout=120) as response:
            result = json.loads(response.read(1024 * 1024))
    except (OSError, ValueError, ReportError):
        raise ReportError("Report dispatch response was unavailable. Check status using the returned job ID before attempting another run.") from None
    if str(result.get("run_id", "")).lower() != job_id or str(result.get("automation_account_resource_id", "")).lower() != account.lower():
        raise ReportError("Report dispatch returned an unexpected job or Automation Account.")


def _cloud(request):
    if request["report_type"] not in RUNBOOKS:
        raise ReportError("Cloud JSON protocol is currently supported by the two PowerShell report runbooks only; use local compute for foundry-usage.", "unavailable")
    _verify_account(request)
    if request["compute"] == "logicapp":
        account = _logic_account(request)
        runbook = account + "/runbooks/" + RUNBOOKS[request["report_type"]]
    else:
        runbook = _resource(request.get("cloud_resource_id"), request, "runbook")
        account = runbook.rsplit("/runbooks/", 1)[0] if "/runbooks/" in runbook else runbook[:runbook.lower().rfind("/runbooks/")]
    _check_runbook(request, runbook)
    job_id = str(uuid.uuid4())
    extra = {"automation_account_resource_id": account, "job_resource_id": account + "/jobs/" + job_id}
    try:
        if request["compute"] == "logicapp":
            _invoke_logic(request, job_id, account)
        else:
            _rest("put", extra["job_resource_id"], body={"properties": {"runbook": {"name": RUNBOOKS[request["report_type"]]}, "parameters": _parameters(request)}})
    except ReportError as error:
        return _result(request, "warning", str(error) + " Submission may have reached Azure; check status before retrying.", run_id=job_id, **extra)
    return _result(request, "running", "Azure report job submitted. Existing schedules were not changed; blob upload is disabled.", run_id=job_id, **extra)


def execute(request):
    if not isinstance(request, dict):
        return _result({}, "failed", "Report request must be a JSON object.")
    try:
        request = _validate(request)
        if request.get("action") == "status":
            return status(request, request.get("run_id"))
        if request.get("dry_run"):
            return _sample(request)
        return _local(request) if request["compute"] == "local" else _cloud(request)
    except ReportError as error:
        return _result(request, error.status, str(error))
    except (OSError, ValueError):
        return _result(request, "failed", "Report request could not be processed. Check configuration and the selected report runtime.")


def status(request, run_id):
    try:
        request = _validate(request)
        if request.get("dry_run"):
            return _sample(request)
        if request["compute"] == "local":
            raise ReportError("Local reports execute synchronously; there is no cloud job to poll.", "unavailable")
        if request["report_type"] not in RUNBOOKS:
            raise ReportError("Cloud JSON polling is unavailable for this report type.", "unavailable")
        run_id = _guid(run_id, "run_id")
        _verify_account(request)
        if request["compute"] == "logicapp":
            account = _logic_account(request)
        else:
            runbook = _resource(request.get("cloud_resource_id"), request, "runbook")
            account = runbook[:runbook.lower().rfind("/runbooks/")]
        job_resource = account + "/jobs/" + run_id
        job = _rest("get", job_resource)
        properties = job.get("properties", {})
        if properties.get("runbook", {}).get("name", "").lower() != RUNBOOKS[request["report_type"]].lower():
            raise ReportError("Azure job is not the selected known report runbook.")
        parameters = {key.lower(): str(value) for key, value in properties.get("parameters", {}).items()}
        for key, value in _parameters(request).items():
            if key.lower() == "configjson":
                try:
                    if json.loads(parameters.get("configjson", "")) != json.loads(value):
                        raise ReportError("Azure job report configuration does not match the original request.")
                except ValueError:
                    raise ReportError("Azure job report configuration is missing or invalid.") from None
                continue
            if parameters.get(key.lower(), "").lower() != value.lower():
                raise ReportError("Azure job parameters do not match the selected target or safe report protocol.")
        extra = {"automation_account_resource_id": account, "job_resource_id": job_resource}
        state = properties.get("status", "").lower()
        if state in ("new", "activating", "running", "queued", "starting", "resuming"):
            return _result(request, "running", "Azure report job is " + state + ".", run_id=run_id, **extra)
        if state != "completed":
            return _result(request, "failed", "Azure report job did not complete successfully (" + state + ").", run_id=run_id, **extra)
        output = _rest("get", job_resource + "/output", raw=True)
        if isinstance(output, str):
            try:
                output = json.loads(output.lstrip("\ufeff").strip())
            except ValueError:
                raise ReportError("Completed runbook returned non-JSON output. Publish the JSON-capable script before running again.", "unavailable") from None
        return _accept_report(request, output, run_id=run_id, **extra)
    except ReportError as error:
        return _result(request, error.status, str(error), run_id=run_id)
    except (OSError, ValueError):
        return _result(request, "failed", "Report job status could not be read safely.", run_id=run_id)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, help="Path to a version-1 JSON request.")
    args = parser.parse_args(argv)
    try:
        with Path(args.request).open("rb") as stream:
            content = stream.read(2 * 1024 * 1024 + 1)
        if len(content) > 2 * 1024 * 1024:
            raise ValueError("Request exceeds 2 MiB.")
        request = json.loads(content.decode("utf-8-sig"))
        if not isinstance(request, dict):
            raise ValueError("Request must be an object")
        result = execute(request)
    except (OSError, ValueError, RecursionError):
        result = _result({}, "failed", "Could not read the report request JSON.")
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 1 if result["status"] in ("failed", "unavailable") else 0


if __name__ == "__main__":
    raise SystemExit(main())
