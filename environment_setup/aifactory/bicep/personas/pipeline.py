#!/usr/bin/env python3
"""Fail-closed bridge between AI Factory configuration and persona provisioning."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import uuid

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from personas import access, groups, policy
    from personas.cli import azure_cli
else:
    from . import access, groups, policy
    from .cli import azure_cli


MARKER = "AIF-Persona-Access"
HUMAN_CHANNELS = (
    "technical_admins_ad_object_id", "technical_admins_email",
    "technicalContactId", "technicalContactEmail",
    "PROJECT_MEMBERS", "PROJECT_MEMBERS_EMAILS",
    "groups_project_members_esml", "groups_project_members_genai_1",
    "groups_coreteam_members", "GROUPS_PROJECT_MEMBERS_ESML",
    "GROUPS_PROJECT_MEMBERS_GENAI_1", "GROUPS_CORETEAM_MEMBERS",
    "RBAC_ADMINS_OID", "postGresAdminEmails", "POSTGRES_ADMIN_EMAILS",
)
ALIASES = {
    "enablePersonas": "ENABLE_PERSONAS",
    "persona_access_mode": "PERSONA_ACCESS_MODE",
    "persona_access_manifest": "PERSONA_ACCESS_MANIFEST",
    "admin_aifactoryPrefixRG": "AIFACTORY_PREFIX",
    "admin_aifactorySuffixRG": "AIFACTORY_SUFFIX",
    "admin_locationSuffix": "AIFACTORY_LOCATION_SHORT",
    "project_number_000": "PROJECT_NUMBER",
    "projectPrefix": "PROJECT_PREFIX",
    "projectSuffix": "PROJECT_SUFFIX",
    "vnetResourceGroupBase": "VNET_RESOURCE_GROUP_BASE",
    "commonResourceGroup_param": "COMMON_RESOURCE_GROUP_PARAM",
}


def value(values: dict, name: str, default=""):
    for key in (name, name.upper(), ALIASES.get(name, name)):
        if key in values:
            result = values[key]
            if result is None:
                raise ValueError(f"{name} cannot be null")
            if isinstance(result, str) and result.startswith("$("):
                continue
            return result
    return default


def select_config(config: dict, environment: str) -> dict:
    """Keep the established baseline/Stage-Prod overlay and allow exact overrides."""
    if not isinstance(config, dict) or set(config) - {"dev", "stage_prod", "test", "prod", "_wizard"}:
        raise ValueError("Configuration requires dev/stage_prod/test/prod sections, not a flat or unknown configuration")
    if any(not isinstance(section, dict) for key, section in config.items() if key != "_wizard"):
        raise ValueError("Configuration environment sections must be objects")
    environment = "test" if environment == "stage" else environment
    result = canonical_persona_values(config.get("dev", {}))
    if environment != "dev":
        result.update(canonical_persona_values(config.get("stage_prod", {})))
        result.update(canonical_persona_values(config.get(environment, {})))
    return result


def canonical_persona_values(values: dict) -> dict:
    result = dict(values)
    for alias, canonical in {
        "ENABLEPERSONAS": "enablePersonas", "ENABLE_PERSONAS": "enablePersonas",
        "PERSONA_ACCESS_MODE": "persona_access_mode",
        "PERSONA_ACCESS_MANIFEST": "persona_access_manifest",
    }.items():
        if alias in result:
            result.setdefault(canonical, result.pop(alias))
    return result


def access_mode(values: dict) -> str:
    missing = object()
    enabled = value(values, "enablePersonas", missing)
    if enabled is not missing:
        if type(enabled) is bool:
            return "groups-v1" if enabled else "legacy"
        if isinstance(enabled, str) and enabled in ("true", "false"):
            return "groups-v1" if enabled == "true" else "legacy"
        raise ValueError("enablePersonas must be a boolean or the exact string true/false")
    mode = value(values, "persona_access_mode", "legacy")
    if mode not in ("legacy", "groups-v1"):
        raise ValueError(f"Unsupported persona_access_mode {mode!r}; use legacy or groups-v1")
    return mode


def mode_variables(mode: str) -> dict:
    enabled = str(mode == "groups-v1").lower()
    return {"enablePersonas": enabled, "ENABLEPERSONAS": enabled, "ENABLE_PERSONAS": enabled,
            "persona_access_mode": mode, "PERSONA_ACCESS_MODE": mode}


def resolve_repo_path(path: str, root: Path) -> Path:
    # Manifest paths are always repository-relative, not relative to variables.json.
    normalized = path.replace("\\", "/")
    if not normalized or normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise ValueError("persona_access_manifest must be a repository-relative file path")
    resolved = (root / normalized).resolve()
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
        raise ValueError(f"Persona manifest missing or outside repository: {path}")
    return resolved


def configuration(values: dict, environment: str, root: Path) -> tuple[str, dict | None]:
    mode = access_mode(values)
    environment = "test" if environment == "stage" else environment
    deployment_subscription(values, environment)
    if mode == "legacy":
        return mode, None
    path = str(value(values, "persona_access_manifest"))
    manifest = json.loads(resolve_repo_path(path, root).read_text(encoding="utf-8-sig"))
    manifest = policy.validate_manifest(manifest, require_lake=True)
    if manifest["environment"] != environment:
        raise ValueError("Persona manifest environment does not match the deployment")
    scopes = deployment_scopes(values, environment)
    for scope in ("common", "project"):
        if manifest[f"{scope}_scope"].lower() != scopes[scope].lower():
            raise ValueError(f"Persona {scope}_scope must match the generated deployment RG: {scopes[scope]}")
    project = f"project{str(value(values, 'project_number_000', '001')).zfill(3)}"
    if manifest["project"] != project:
        raise ValueError(f"Persona manifest project must be {project}")
    tenant = value(values, "tenantId")
    if tenant and tenant.lower() != manifest["tenant_id"].lower():
        raise ValueError("Persona manifest tenant_id does not match tenantId")
    lake_enabled = str(value(values, "enableProjectLakeAccess")).lower()
    gateway_only = str(value(values, "deployOnlyAIGatewayNetworking")).lower() == "true"
    if manifest.get("lake") and (lake_enabled == "false" or gateway_only):
        raise ValueError("Manifest lake access conflicts with disabled/gateway-only lake configuration")
    return mode, manifest


def deployment_subscription(values: dict, environment: str) -> str:
    environment = "test" if environment == "stage" else environment
    runtime_environment = value(values, "dev_test_prod")
    if runtime_environment and runtime_environment != environment:
        raise ValueError("dev_test_prod must match the selected persona deployment environment")
    selected = value(values, f"{environment}_sub_id")
    runtime = value(values, "dev_test_prod_sub_id")
    if selected and runtime and selected.lower() != runtime.lower():
        raise ValueError("Selected subscription and dev_test_prod_sub_id must agree before persona provisioning")
    return runtime or selected or value(values, "AZURE_SUBSCRIPTION_ID")


def deployment_scopes(values: dict, environment: str) -> dict[str, str]:
    environment = "test" if environment == "stage" else environment
    subscription = deployment_subscription(values, environment)
    if not subscription:
        raise ValueError("The deployment subscription is required for persona scope/downgrade checks")
    prefix = value(values, "admin_aifactoryPrefixRG")
    suffix = value(values, "admin_aifactorySuffixRG")
    location = value(values, "admin_locationSuffix")
    if not location:
        raise ValueError("admin_locationSuffix is required for persona scope/downgrade checks")
    common = value(values, "commonResourceGroup_param") or (
        f"{prefix}{value(values, 'vnetResourceGroupBase', 'esml-common')}-{location}-{environment}{suffix}"
    )
    project = (
        f"{prefix}{value(values, 'projectPrefix', 'esml-')}project"
        f"{str(value(values, 'project_number_000', '001')).zfill(3)}"
        f"-{location}-{environment}{suffix}{value(values, 'projectSuffix', '-rg')}"
    )
    return {key: f"/subscriptions/{subscription}/resourceGroups/{name}"
            for key, name in (("common", common), ("project", project))}


def safe_variables(values: dict) -> dict:
    result = {name: "" for name in HUMAN_CHANNELS}
    result.update({name.upper(): "" for name in HUMAN_CHANNELS})
    result.update({
        **mode_variables("groups-v1"),
        "disableContributorAccessForUsers": "true",
        "disableRBACAdminOnRGForUsers": "true",
        "use_ad_groups": "true", "useAdGroups": "true", "use_groups": "true",
    })
    for name in ("tags", "tagsProject"):
        raw = value(values, name, "{}") or "{}"
        tags = json.loads(raw) if isinstance(raw, str) else dict(raw)
        tags[MARKER] = "groups-v1"
        result[name] = json.dumps(tags, separators=(",", ":"))
    return result


def guard_downgrade(values: dict, environment: str, mode: str, cli=None) -> dict[str, bool]:
    run = cli or azure_cli
    existing = {}
    for name, scope in deployment_scopes(values, environment).items():
        parts = scope.split("/")
        exists = run("group", "exists", "--subscription", parts[2], "--name", parts[4])
        if type(exists) is not bool:
            raise ValueError("Resource-group existence check must return a boolean")
        existing[name] = exists
        if not exists:
            continue
        group = run("group", "show", "--subscription", parts[2], "--name", parts[4])
        previous = (group.get("tags") or {}).get(MARKER)
        if previous and previous != mode:
            raise ValueError(f"{scope} is marked {previous}; refusing downgrade to {mode}. "
                             "Restore its reviewed groups-v1 configuration; migration is an explicit operator action.")
    return existing


def emit(variables: dict, output_format: str) -> None:
    for name, val in variables.items():
        text = str(val)
        if output_format == "azure-devops":
            escaped = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
            print(f"##vso[task.setvariable variable={name}]{escaped}")
        elif output_format == "github":
            delimiter = "PERSONA_" + uuid.uuid4().hex
            with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(f"{name}<<{delimiter}\n{text}\n{delimiter}\n")


def run(values: dict, environment: str, root: Path, scope: str, phase: str, cli=None) -> dict:
    mode, manifest = configuration(values, environment, root)
    if phase == "validate":
        return {"mode": mode, "variables": safe_variables(values) if manifest else mode_variables(mode)}
    existing = guard_downgrade(values, environment, mode, cli)
    if mode == "legacy":
        return {"mode": mode, "status": "unchanged",
                "variables": {**mode_variables(mode), "persona_preflight_ready": "true"}}
    deleting = any(str(value(values, name)).lower() == "true"
                   for name in ("deleteAllForProject", "deleteAllServicesForProject"))
    if phase == "preflight":
        try:
            seeded = groups.resolve_seeded_groups(manifest, scope="project", cli=cli or azure_cli)
        except (ValueError, RuntimeError, OSError) as error:
            raise ValueError("Persona groups must be bootstrapped and published to the manifest's "
                             "seeding Key Vault before factory/common or project provisioning. "
                             f"The pipeline never creates Entra groups: {error}") from error
        preview_scope = "project" if scope == "project" and existing["project"] else "common"
        preview = None
        if not deleting and existing[preview_scope]:
            # Existing deployments must be audited before templates can alter vault
            # authorization or storage credentials. New RGs get seed-only preflight.
            preview = access.provision(manifest, scope=preview_scope, execute=False, cli=cli)
            if preview.get("state") == "blocked" or preview.get("blockers"):
                raise ValueError("Existing persona deployment requires remediation before any template runs: "
                                 + "; ".join(preview.get("blockers") or ["Policy preview blocked"]))
        return {"mode": mode, "status": "seed-validated", "groups": seeded,
                "existing_scope_preview": preview,
                "workload_access": "Legacy broad lake roles/ACLs and common-vault access policies are not granted. Review workload credentials and explicitly scoped workload access separately.",
                "variables": {**safe_variables(values), "persona_preflight_ready": "true"}}
    if deleting:
        return {"mode": mode, "status": "deletion-preserves-groups", "variables": safe_variables(values)}
    report = access.provision(manifest, scope=scope, execute=True, cli=cli)
    return {"mode": mode, "status": "applied", "report": report, "variables": safe_variables(values)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="", help="variables.json; omit for CI environment variables")
    parser.add_argument("--repo-root", default=".", help="consumer repository root containing the manifest")
    parser.add_argument("--environment", choices=("dev", "test", "stage", "prod"), required=True)
    parser.add_argument("--scope", choices=("common", "project"), required=True)
    parser.add_argument("--phase", choices=("validate", "preflight", "apply"), required=True)
    parser.add_argument("--format", choices=("github", "azure-devops", "json"), default="json")
    args = parser.parse_args()
    try:
        values = dict(os.environ)
        # GitHub exposes an unset repository variable as an empty environment value.
        for key in ("enablePersonas", "ENABLEPERSONAS", "ENABLE_PERSONAS"):
            if values.get(key) == "":
                values.pop(key)
        if args.config and not args.config.startswith("$("):
            config_path = Path(args.config.replace("\\", os.sep))
            selected = select_config(json.loads(config_path.read_text(encoding="utf-8-sig")), args.environment)
            # Explicit JSON persona settings outrank CI/template defaults, including old mode-only configs.
            if any(key in selected for key in ("enablePersonas", "ENABLEPERSONAS", "ENABLE_PERSONAS",
                                               "persona_access_mode", "PERSONA_ACCESS_MODE")):
                for key in ("enablePersonas", "ENABLEPERSONAS", "ENABLE_PERSONAS",
                            "persona_access_mode", "PERSONA_ACCESS_MODE"):
                    values.pop(key, None)
            values.update(selected)
        report = run(values, args.environment, Path(args.repo_root), args.scope, args.phase)
        emit(report.pop("variables"), args.format)
        print(json.dumps(report, default=str))
        return 0
    except (ValueError, RuntimeError, OSError, KeyError) as error:
        print(f"Persona access prerequisite failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
