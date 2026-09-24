"""Configure-first bridge for modern Simple/Full shell launchers.

The API owns catalog validation, projection, source review and confirmation.
This adapter never writes factory records or invokes a cloud/bootstrap command.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

import release_version


COMMON_FIELDS = {
    "AIF_DEV_SUBSCRIPTION_ID": "subscription_id", "AIF_TENANT_ID": "tenant_id",
    "AIF_LOCATION": "location", "AIF_PREFIX": "factory_prefix",
    "AIF_TEAM_MEMBER_EMAIL": "team_member_email", "AIF_TEAM_GROUP_NAME": "team_group_name",
    "AIF_COST_CENTER": "cost_center",
    "AIF_ACCESS_HUB_SUBSCRIPTION_ID": "access_hub_subscription_id",
    "AIF_ACCESS_HUB_RESOURCE_GROUP": "access_hub_resource_group",
    "AIF_ACCESS_HUB_VNET_NAME": "access_hub_vnet_name",
    "AIF_ACCESS_HUB_VNET_CIDR": "access_hub_vnet_cidr",
    "AIF_VPN_CLIENT_CIDR": "vpn_client_cidr",
    "AIF_COORDINATION_MODE": "coordination_mode",
}
FULL_FIELDS = {
    "GITHUB_REPOSITORY": "github_repository", "GITHUB_REPOSITORY_VISIBILITY": "github_visibility",
    "AIF_PROJECT_NUMBER": "project_number", "AIF_SCALESET_SUFFIX": "scale_set_number",
    "ADO_ORGANIZATION": "ado_organization",
    "ADO_PROJECT": "ado_project", "ADO_REPOSITORY_NAME": "ado_repository",
    "ADO_SERVICE_CONNECTION_NAME": "ado_service_connection", "ADO_TENANT": "ado_tenant_id",
    "AIF_MI_RESOURCE_ID": "managed_identity_resource_id", "AIF_TEAM_GROUP_ID": "team_group_id",
    "AIF_RUNNER_VM_NAME": "runner_vm_name", "AIF_RUNNER_VM_RESOURCE_GROUP": "runner_vm_resource_group",
    "AIF_ADMIN_VM_SIZE": "admin_vm_size", "ADO_AGENT_POOL": "ado_agent_pool",
    "ADO_AGENT_NAME": "ado_agent_name", "GHA_RUNNER_NAME": "gha_runner_name",
    "GHA_RUNNER_LABEL": "gha_runner_label", "AIF_DEV_VNET_CIDR": "dev_vnet_cidr",
    "AIF_VPN_CLIENT_CIDR": "vpn_client_cidr",
}
SIMPLE_FIELDS = {
    "GITHUB_REPOSITORY": "github_repository", "GITHUB_REPOSITORY_VISIBILITY": "github_visibility",
    "AIF_APP_GATEWAY_HOSTNAME": "app_gateway_hostname",
    "AIF_APP_GATEWAY_BACKEND_FQDN": "app_gateway_backend_fqdn",
    "AIF_APP_GATEWAY_CERT_SECRET_ID": "app_gateway_certificate_secret_id",
}


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("provider", choices=("ado", "gha"))
    result.add_argument("--select-layout", action="store_true")
    result.add_argument("--repo-root", default=os.environ.get("AIFACTORY_REPO_ROOT"))
    result.add_argument("--aifactory-version")
    result.add_argument("--save-receipt", default=os.environ.get("AIF_SAVE_RECEIPT"))
    result.add_argument("--dry-run", action="store_true")
    result.add_argument("--non-interactive", action="store_true", default=os.environ.get("AIF_NON_INTERACTIVE") == "true")
    result.add_argument("--prepare-only", action="store_true")
    result.add_argument("--no-wait", action="store_true")
    result.add_argument("--yes", action="store_true")
    return result


def selected_version(args, environ):
    requested = args.aifactory_version or environ.get("AIF_VERSION_ARGUMENT")
    explicit = requested or environ.get("AIFACTORY_VERSION") or environ.get("AIF_SUBMODULE_BRANCH")
    saved = release_version.saved_version(args.repo_root) if args.repo_root and not explicit else None
    return release_version.select(requested, saved=saved, default="main", environ=environ)["requested_version"]


def modern(version):
    if version == "main":
        return True
    dotted = release_version.branch_for(version).removeprefix("release/v")
    return tuple(map(int, dotted.split("."))) >= (1, 25)


def ordinary(path):
    path = Path(os.path.abspath(path))
    if any(item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction())
           for item in (path, *path.parents)):
        raise ValueError("Creation paths must not traverse symbolic links or junctions.")
    return path


def consumer_root(value):
    if not value:
        raise ValueError("Modern creation requires --repo-root PATH (the consumer repository, not the shared source).")
    root = ordinary(value)
    if root.exists() and not root.is_dir():
        raise ValueError("Consumer repository path is not a directory.")
    if root.name.casefold() == "azurefactory":
        raise ValueError("--repo-root must be the consumer directory above azurefactory.")
    for ancestor in (root, *root.parents):
        if (ancestor / "environment_setup" / "aifactory").is_dir() and (ancestor / "bootstrap").is_dir():
            raise ValueError("Do not create a consumer inside the shared source checkout.")
        if (ancestor.name.casefold() == "aifactory" or
                (ancestor / "aifactory").exists() and (ancestor == root or (ancestor / ".git").exists())):
            raise ValueError("Existing legacy aifactory requires separately reviewed migration; no automatic conversion.")
        if (ancestor.name.casefold() == "azurefactory" and (ancestor / "register.json").exists() or
                (ancestor / "azurefactory" / "register.json").exists()
                and (ancestor == root or (ancestor / ".git").exists())):
            raise ValueError("Existing register requires azurefactory.sh factory create or reviewed lifecycle operations.")
    target = ordinary(root / "azurefactory")
    if target.exists():
        if not target.is_dir() or any(child.name != ".azurefactory" for child in target.iterdir()):
            raise ValueError("Without a register, azurefactory must be empty or contain only pending catalog metadata.")
        internal = ordinary(target / ".azurefactory")
        if internal.exists():
            allowed = {".catalog.lock", "catalog-operations.sqlite", "catalog-operations.sqlite-journal",
                       "catalog-operations.sqlite-wal", "catalog-operations.sqlite-shm"}
            if not internal.is_dir() or any(
                    ordinary(child).name not in allowed or not child.is_file() or child.stat().st_nlink != 1
                    for child in internal.iterdir()):
                raise ValueError("Unrecognized pending catalog metadata; no files will be overwritten.")
        # The API revalidates this pending-only destination and its catalog under its lock.
    return root


def load_sdk():
    base = Path(__file__).resolve().parents[1]
    for candidate in (
        base / ".azurefactory-tools",
        base.parent / "environment_setup" / "azurefactory-cli" / "src",
        base / "azure-enterprise-scale-ml" / "environment_setup" / "azurefactory-cli" / "src",
    ):
        if (candidate / "azurefactory" / "client.py").is_file():
            sys.path.insert(0, str(candidate))
            break
    try:
        from azurefactory.client import AzureFactoryClient
        from azurefactory.review import write_receipt
    except ImportError:
        raise ValueError("Current shared azurefactory SDK is required; run the approved 01-start-v125-and-above.sh installer.") from None
    return AzureFactoryClient, write_receipt


def boolean(value, name):
    if value not in ("true", "false", "y", "n"):
        raise ValueError(f"{name} must be true/false or y/n.")
    return value in ("true", "y")


def creation_input(args, root, version, environ):
    simple = boolean(environ.get("AIF_SIMPLE_MODE", "false"), "AIF_SIMPLE_MODE")
    if simple and args.provider != "gha":
        raise ValueError("The Simple preset is GHA-only; select Full configuration for ADO.")
    routes = {"ado": {"a", "ado", "azure-devops", "azuredevops"},
              "gha": {"g", "gh", "gha", "github", "github-actions"}}
    if environ.get("AIF_ORCHESTRATOR") and environ["AIF_ORCHESTRATOR"].lower() not in routes[args.provider]:
        raise ValueError("AIF_ORCHESTRATOR conflicts with the selected launcher provider.")
    # Never forward credentials or infer cloud identity from the host CLI cache.
    if any(environ.get(name) for name in ("AIF_SP_CLIENT_SECRET", "AIF_SP_CLIENT_ID")):
        raise ValueError("Registered configuration accepts no service-principal credentials; use reviewed enrollment separately.")
    if environ.get("AIF_CREATE_PROJECTS") or environ.get("AIF_PROJECT_MODE"):
        raise ValueError("Scoped/common-only creation requires azurefactory.sh factory create --common-only; no implicit project001 fallback is allowed.")
    fields = {**COMMON_FIELDS, **(SIMPLE_FIELDS if simple else FULL_FIELDS)}
    fixed = {
        "AIF_TOPOLOGY": {"s"}, "AIF_NETWORK_MODE": {"priv"},
        "AIF_CONFIGURE_VPN_CLIENT": {"false", "n"},
        "AIF_SEEDING_MODE": {"c"}, "AIF_SEED_PROJECT_SP": {"false", "n"},
    }
    if simple:
        fixed.update(AIF_SCALESET_SUFFIX={"001"}, AIF_DEV_VNET_CIDR={"172.16.0.0/20"},
                     AIF_IDENTITY_MODE={"c", "create"}, AIF_RUNNER_MODE={"github-hosted", "hosted"})
    for name, supported in fixed.items():
        if environ.get(name) and environ[name] not in supported:
            raise ValueError(f"{name} is not represented by the modern form; use explicit catalog configuration instead.")
    accepted = set(fields) | set(fixed) | {
        "AIF_SIMPLE_MODE", "AIF_SETUP_HUB_ACCESS", "AIF_ACCESS_HUB_MODE", "AIF_ORCHESTRATOR", "AIF_SUBMODULE_BRANCH", "AIF_SUBMODULE_REF", "AIF_SAVE_RECEIPT", "AIF_VERSION_ARGUMENT",
        "AIF_DRY_RUN", "AIF_NON_INTERACTIVE", "AIF_PREPARE_ONLY", "AIF_NO_WAIT", "AIF_YES",
    } | ({"AIF_ENABLE_APPLICATION_GATEWAY", "AIF_SIMPLE_PROJECT_RESOURCES_JSON", "AIF_PROJECT_NUMBER"} if simple else
         {"AIF_IDENTITY_MODE", "AIF_RUNNER_MODE"})
    unsupported = sorted(name for name, value in environ.items()
                         if value and name.startswith(("AIF_", "ADO_", "GHA_", "GITHUB_")) and name not in accepted)
    if unsupported:
        raise ValueError("Unmapped modern bootstrap settings (never silently discarded): " + ", ".join(unsupported)
                         + ". Use explicit catalog configuration/enrollment for these choices.")
    config = {target: environ[name] for name, target in fields.items() if environ.get(name)}
    if config.get("coordination_mode", "blob") not in ("blob", "single-writer"):
        raise ValueError("AIF_COORDINATION_MODE must be blob or single-writer; automatic fallback is not supported.")
    config.update(repo_root=str(root), aifactory_version=version)
    if simple:
        config["enable_application_gateway"] = boolean(
            environ.get("AIF_ENABLE_APPLICATION_GATEWAY", "false"), "AIF_ENABLE_APPLICATION_GATEWAY")
        if "AIF_SIMPLE_PROJECT_RESOURCES_JSON" in environ:
            resources = json.loads(environ["AIF_SIMPLE_PROJECT_RESOURCES_JSON"])
            if not isinstance(resources, list) or any(not isinstance(value, str) for value in resources):
                raise ValueError("AIF_SIMPLE_PROJECT_RESOURCES_JSON must be an array of resource IDs.")
            config["project_resources"] = resources
    else:
        config.setdefault("scale_set_number", "001")
        if environ.get("AIF_IDENTITY_MODE"):
            choices = {"c": "create", "create": "create", "mi": "existing", "existing": "existing"}
            if environ["AIF_IDENTITY_MODE"] not in choices:
                raise ValueError("AIF_IDENTITY_MODE must be c/create or mi/existing; enrollment is a separate review.")
            config["identity_mode"] = choices[environ["AIF_IDENTITY_MODE"]]
        if environ.get("AIF_RUNNER_MODE"):
            choices = {"self-hosted": "self-hosted", "github-hosted": "hosted", "microsoft-hosted": "hosted", "hosted": "hosted"}
            if environ["AIF_RUNNER_MODE"] not in choices:
                raise ValueError("AIF_RUNNER_MODE must be self-hosted, hosted, github-hosted or microsoft-hosted.")
            config["runner_mode"] = choices[environ["AIF_RUNNER_MODE"]]
    if "AIF_SETUP_HUB_ACCESS" in environ:
        config["setup_hub_access"] = boolean(environ["AIF_SETUP_HUB_ACCESS"], "AIF_SETUP_HUB_ACCESS")
    if "AIF_ACCESS_HUB_MODE" in environ:
        choices = {"i": "integrated", "integrated": "integrated", "e": "external", "external": "external"}
        if environ["AIF_ACCESS_HUB_MODE"] not in choices:
            raise ValueError("AIF_ACCESS_HUB_MODE must be i/integrated or e/external.")
        config["access_hub_mode"] = choices[environ["AIF_ACCESS_HUB_MODE"]]
    external_fields = ("access_hub_subscription_id", "access_hub_resource_group",
                       "access_hub_vnet_name", "access_hub_vnet_cidr")
    if config.get("access_hub_mode") == "external":
        missing_external = [key for key in external_fields if not config.get(key)]
        if missing_external:
            raise ValueError("External hub requires explicit reviewed coordinates: " + ", ".join(missing_external))
    elif any(config.get(key) for key in external_fields):
        raise ValueError("External hub coordinates require AIF_ACCESS_HUB_MODE=external; they are never silently ignored.")
    required = ["subscription_id", "tenant_id", "factory_prefix", "location",
                "team_member_email", "team_group_name"]
    required += (["github_repository"] if args.provider == "gha" else
                 ["ado_organization", "ado_project", "ado_repository", "ado_service_connection"])
    defaults = {"factory_prefix": "aif-", "location": "swedencentral"}
    missing = []
    for key in required:
        if not config.get(key):
            if not args.non_interactive and sys.stdin.isatty():
                default = defaults.get(key, "")
                config[key] = input(f"{key}" + (f" [{default}]" if default else "") + ": ").strip() or default
            elif key in defaults:
                config[key] = defaults[key]
            if not config.get(key):
                missing.append(next(name for name, target in fields.items() if target == key))
    if missing:
        raise ValueError("Required nonsecret configuration: " + ", ".join(missing))
    body = {"contract_version": 1, "folder": str(root), "mode": "simple" if simple else "full-bootstrap",
            "orchestrator": args.provider, "config": config}
    if simple and environ.get("AIF_PROJECT_NUMBER"):
        body["initial_project"] = {"number": environ["AIF_PROJECT_NUMBER"]}
    return body


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if sum(value == "--aifactory-version" or value.startswith("--aifactory-version=")
           for value in arguments) > 1:
        raise ValueError("Specify --aifactory-version only once.")
    # Help must remain available even with no SDK/API or complete consumer bundle.
    args, unknown = parser().parse_known_args(arguments)
    if args.select_layout:
        print("registered" if modern(selected_version(args, os.environ)) else "legacy")
        return 0
    if unknown:
        raise ValueError("Unsupported modern creation arguments: " + ", ".join(unknown))
    version = selected_version(args, os.environ)
    if not modern(version):
        raise ValueError("Registered creation requires main or v1.25+. Use the legacy124 launcher path for 124.")
    root = consumer_root(args.repo_root)
    return prepare(args, root, version)


def prepare(args, root, version):
    request = creation_input(args, root, version, os.environ)
    if args.dry_run or os.environ.get("AIF_DRY_RUN") == "true":
        print(json.dumps({"status": "offline-input-only", "request": request,
                          "message": "No files or cloud resources changed. API validation, configuration review and runtime source review are still required."}, indent=2))
        return 0
    if not root.is_dir():
        raise ValueError("Create the consumer repository directory before preparing configuration; --dry-run does not require it.")
    if not args.save_receipt:
        raise ValueError("Specify --save-receipt PATH for the separate configuration review (or --dry-run for offline inputs). --yes never auto-confirms.")
    receipt_path = ordinary(args.save_receipt)
    if receipt_path.exists() or not receipt_path.parent.is_dir():
        raise ValueError("Receipt must be a new file in an existing directory; existing receipts are never replaced.")
    if receipt_path.is_relative_to(root / "azurefactory"):
        raise ValueError("Keep the review receipt outside the generated azurefactory directory.")
    client_type, write_receipt = load_sdk()
    client = client_type()
    preview = client.request("POST", "/api/v1/creation/prepare", body=request)
    if not isinstance(preview, dict) or preview.get("operation_mode") != "configuration":
        raise ValueError("The API did not return configure-first review. Update the local API; no legacy fallback or bootstrap start is allowed.")
    capabilities = preview.get("capabilities")
    if (not isinstance(capabilities, list) or any(not isinstance(value, str) for value in capabilities)
            or not {"initial-project-v1", "draft-scale-identity-v1"}.issubset(capabilities)):
        raise ValueError("The API lacks required initial-project-v1/draft-scale-identity-v1 capabilities; no approval receipt was saved.")
    target = preview.get("target")
    if (type(preview.get("contract_version")) is not int or preview["contract_version"] != 1
            or not isinstance(target, dict) or not isinstance(preview.get("folder"), str)
            or not Path(preview["folder"]).is_absolute()
            or ordinary(preview["folder"]) != root / "azurefactory"
            or release_version.normalize(target.get("aifactory_version")) != version
            or target.get("version_ref") != version):
        raise ValueError("The API changed the registered destination, version or configuration action; no approval receipt was saved.")
    projects = target.get("projects")
    expected = request.get("initial_project", {}).get("number", request["config"].get("project_number", "001"))
    if (not isinstance(projects, list) or len(projects) != 1 or not isinstance(projects[0], dict)
            or projects[0].get("number") != expected):
        raise ValueError("The API changed the requested initial project; no approval receipt was saved.")
    scales = target.get("scale_sets")
    config = request["config"]
    if (target.get("prefix") != config["factory_prefix"]
            or target.get("region") != config["location"] or target.get("kind") != "ai"
            or target.get("default_orchestrator") != args.provider
            or not isinstance(scales, list) or len(scales) != 1 or not isinstance(scales[0], dict)
            or not scales[0].get("id") or scales[0].get("environment") != "dev"
            or scales[0].get("orchestrator") != args.provider
            or any(scales[0].get(key) != config[key] for key in ("tenant_id", "subscription_id"))
            or scales[0].get("suffix") != config.get("scale_set_number", "001")
            or projects[0].get("placements") != [{"environment": "dev", "scale_set_id": scales[0]["id"]}]):
        raise ValueError("The API changed the requested factory/scale-set identity; no approval receipt was saved.")
    # Catalog confirmation consumes the same server-held preparation, not a new create request.
    body = {**request, "folder": preview["folder"], "action": "create-factory"}
    receipt = write_receipt(str(receipt_path), client=client, purpose="catalog-confirm",
                            operation="factory-create", request_body=body, preview=preview)
    print(json.dumps(receipt["preview"], indent=2))
    print(f"\nConfiguration review saved: {receipt_path}")
    print("NOT DEPLOYED: no Azure resources, repository publication, identity, enrollment or runner setup was performed.")
    print("Review this receipt; --yes on the bootstrap launcher does not approve it.")
    if preview.get("can_execute") is not True:
        print("BLOCKED: resolve the preview blockers, then prepare a new receipt. Do not confirm this receipt.")
        return 3
    print(f'Confirm configuration only: azurefactory catalog confirm --receipt "{receipt_path}" --yes')
    wrapper = Path(__file__).resolve().parents[1] / "azurefactory.sh"
    if wrapper.is_file():
        print(f'Or use: bash "{wrapper.as_posix()}" catalog confirm --receipt "{receipt_path}" --yes')
    print("After confirmation, inspect catalog IDs and generated project variables; complete enrollment/binding separately.")
    print("Deploy only after a NEW runtime prepare/review/confirm with exact factory, scale-set and project IDs.")
    print("Published source/ref verification and protected manifests remain mandatory for runtime; no dirty source is installed or published.")
    if os.environ.get("AIF_SUBMODULE_REF"):
        print("AIF_SUBMODULE_REF is not executed or installed by configuration; select and verify it in the separate runtime review.")
    return 0 if preview.get("can_execute") is True else 3


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"ERROR: Registered creation stopped: {exc}", file=sys.stderr)
        sys.exit(2)
