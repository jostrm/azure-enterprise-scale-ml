"""Explicitly scoped, read-only discovery; infrastructure is managed by AI Factory."""

import json
import shutil
import subprocess
from pathlib import Path
from uuid import UUID

from .config import boolean, load_json, validate_runtime


def azure_cli(*arguments):
    launcher = shutil.which("az")
    if not launcher:
        raise FileNotFoundError("Azure CLI is required for project discovery")
    command = [launcher, *arguments, "--output", "json", "--only-show-errors"]
    if Path(launcher).suffix.lower() in (".cmd", ".bat"):
        bundled_python = Path(launcher).parent.parent / "python.exe"
        if not bundled_python.is_file():
            raise FileNotFoundError("Azure CLI bundled Python was not found; install a supported Azure CLI")
        command = [str(bundled_python), "-IBm", "azure.cli", *arguments, "--output", "json", "--only-show-errors"]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
    if result.returncode:
        raise ValueError(f"Azure CLI {' '.join(arguments[:2])} failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def select_one(values, label, name=None):
    selected = [row for row in values if not name or row["name"] == name]
    if len(selected) != 1:
        names = ", ".join(row["name"] for row in selected) or "none"
        raise ValueError(f"Select exactly one existing {label}; found {names}. Provision missing infrastructure through AI Factory.")
    return selected[0]


def discover(project_file: Path) -> dict:
    project_file = Path(project_file).resolve()
    project = load_json(project_file)
    variables_path = (project_file.parent / project["variables_file"]).resolve()
    environment = project.get("environment", "dev")
    if environment not in ("dev", "test", "prod"):
        raise ValueError("environment must be dev, test, or prod")
    document = load_json(variables_path)
    section = environment if environment in document else ("stage_prod" if environment != "dev" else "dev")
    if section not in document:
        raise ValueError(f"variables.json has no configuration for {environment}")
    values = document[section]
    if not boolean(values.get("enableAzureMachineLearning", False)):
        raise ValueError("Azure Machine Learning is disabled in the selected AI Factory configuration")
    subscription = str(UUID(values[f"{environment}_sub_id"]))
    tenant = str(UUID(values["tenantId"]))
    group = project["resource_group"]
    account = azure_cli("account", "show", "--subscription", subscription)
    if account["id"].lower() != subscription or account["tenantId"].lower() != tenant:
        raise ValueError("Authenticated subscription/tenant does not match the selected project")
    resources = azure_cli("resource", "list", "--subscription", subscription, "--resource-group", group)
    workspaces = [row for row in resources
                  if row["type"].lower() == "microsoft.machinelearningservices/workspaces"
                  and row.get("kind", "").lower() not in ("hub", "project")]
    workspace = select_one(workspaces, "Azure ML workspace", project.get("workspace_name"))
    computes = azure_cli("ml", "compute", "list", "--subscription", subscription,
                         "--resource-group", group, "--workspace-name", workspace["name"])
    cpu = [row for row in computes if row.get("type", "").lower() == "amlcompute"
           and not any(part in row.get("size", "").lower() for part in ("standard_nc", "standard_nd", "standard_nv"))]
    compute = select_one(cpu, "CPU AmlCompute", project.get("compute"))
    runtime = {
        "subscription_id": subscription, "tenant_id": tenant, "resource_group": group,
        "workspace_name": workspace["name"], "compute": compute["name"],
        **{key: project[key] for key in ("input_data", "gpu_compute", "datastore", "serving", "credential", "managed_identity_client_id") if key in project},
    }
    if project.get("environment_asset"):
        runtime["environment"] = project["environment_asset"]
    return validate_runtime(runtime)
