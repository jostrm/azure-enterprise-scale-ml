"""Persona integration for configure-first bootstrap and protected ARM workers."""
from __future__ import annotations

import base64
import copy
import importlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
from urllib.parse import quote, unquote, urlsplit


MARKER = "AIF-Persona-Access"
FIELDS = ("enablePersonas", "persona_access_mode", "persona_access_manifest")
HUMAN_PARAMETERS = {
    "technicaladminsobjectid", "technicaladminsemail", "technicalcontactid",
    "technicalcontactemail", "projectmembers", "projectmembersemails",
    "project_members", "project_members_emails", "postgres_admin_emails",
    "technical_admins_ad_object_id", "technical_admins_email",
    "groups_project_members_esml", "groups_project_members_genai_1",
    "groups_coreteam_members", "rbac_admins_oid", "postgresadminemails",
    "team_group_id", "team_group_name", "team_member_email",
}


def mode(values):
    # This helper is independently copied and source-pinned by protected workers.
    for key in ("enablePersonas", "ENABLEPERSONAS", "ENABLE_PERSONAS"):
        if key not in values:
            continue
        enabled = values[key]
        if type(enabled) is bool:
            return "groups-v1" if enabled else "legacy"
        if isinstance(enabled, str) and enabled in ("true", "false"):
            return "groups-v1" if enabled == "true" else "legacy"
        raise ValueError("enablePersonas must be a boolean or the exact string true/false")
    selected = values.get("persona_access_mode", values.get("PERSONA_ACCESS_MODE", "legacy"))
    if selected not in ("legacy", "groups-v1"):
        raise ValueError("persona_access_mode must be legacy or groups-v1")
    return selected


def relative_manifest(values):
    path = values.get("persona_access_manifest", "")
    if not isinstance(path, str):
        raise ValueError("persona_access_manifest must be a repository-relative file path")
    path = path.replace("\\", "/")
    if (not path or path.startswith("/") or re.match(r"^[A-Za-z]:", path)
            or any(part in ("", ".", "..") for part in path.split("/"))
            or any(ord(char) < 32 for char in path)):
        raise ValueError("groups-v1 requires a repository-relative persona_access_manifest")
    return str(PurePosixPath(path))


def pipeline_module(source_root=None):
    helpers = Path(__file__).resolve().parents[1]
    roots = ([Path(source_root)] if source_root else
             [helpers.parent, helpers / "azure-enterprise-scale-ml"])
    directories = [root / "environment_setup" / "aifactory" / "bicep" for root in roots]
    if source_root is None:
        directories.append(helpers / ".azurefactory-tools" / "persona-engine")
    for bicep in directories:
        if (bicep / "personas" / "pipeline.py").is_file():
            sys.path.insert(0, str(bicep))
            module = importlib.import_module("personas.pipeline")
            if Path(module.__file__).resolve() != (bicep / "personas" / "pipeline.py").resolve():
                raise ValueError("Loaded persona engine differs from the reviewed source checkout")
            return module
    raise ValueError("The reviewed source must include bicep/personas; refresh the source helpers")


def selected_config(config, environment):
    if not isinstance(config, dict):
        raise ValueError("Registered deployment configuration must be an object")
    if not any(key in config for key in ("dev", "stage_prod", "test", "prod")):
        return canonical_persona_values(copy.deepcopy(config))
    result = {}
    for key in ("dev", *(("stage_prod", "test" if environment == "stage" else environment)
                         if environment != "dev" else ())):
        section = config.get(key, {})
        if not isinstance(section, dict):
            raise ValueError(f"{key} must be a configuration object")
        result.update(canonical_persona_values(copy.deepcopy(section)))
    return result


def canonical_persona_values(values):
    # Remain self-contained when copied into a source-pinned protected worker.
    result = dict(values)
    for alias, canonical in {
        "ENABLEPERSONAS": "enablePersonas", "ENABLE_PERSONAS": "enablePersonas",
        "PERSONA_ACCESS_MODE": "persona_access_mode",
        "PERSONA_ACCESS_MANIFEST": "persona_access_manifest",
    }.items():
        if alias in result:
            result.setdefault(canonical, result.pop(alias))
    return result


def sanitize(values):
    result = copy.deepcopy(values)
    for key in result:
        if key.lower() in HUMAN_PARAMETERS:
            result[key] = [] if isinstance(result[key], list) else ""
        elif key in ("tags", "tagsProject"):
            tags = json.loads(result[key]) if isinstance(result[key], str) else result[key]
            if not isinstance(tags, dict):
                raise ValueError("Persona deployment tags must be an object")
            result[key] = {**tags, MARKER: "groups-v1"}
        elif key in ("disableContributorAccessForUsers", "disableRBACAdminOnRGForUsers"):
            result[key] = True
        elif key == "personaAccessMode":
            result[key] = "groups-v1"
    return result


def local_manifest(values, root, *, source_root=None):
    if mode(values) == "legacy":
        return None
    pipeline = pipeline_module(source_root)
    path = pipeline.resolve_repo_path(relative_manifest(values), Path(root))
    return pipeline.policy.validate_manifest(json.loads(path.read_text(encoding="utf-8-sig")), require_lake=True)


def check_identity(manifest, *, tenant, environment, project=None):
    environment = "test" if environment == "stage" else environment
    if manifest["tenant_id"].lower() != tenant.lower() or manifest["environment"] != environment:
        raise ValueError("Persona manifest tenant/environment differs from the registered target")
    if project and manifest["project"] != "project" + str(project).zfill(3):
        raise ValueError("Persona manifest project differs from the registered target")


def seeds(manifest, *, source_root=None, cli=None):
    pipeline = pipeline_module(source_root)
    try:
        return pipeline.groups.resolve_seeded_groups(manifest, "project", cli or pipeline.azure_cli)
    except (ValueError, RuntimeError, OSError) as exc:
        raise ValueError("All nine persona groups must already be seeded in an existing readable Key Vault; "
                         "registered bootstrap never creates Entra groups") from exc


def remote_manifest(cloud, route, values):
    path = relative_manifest(values)
    if route["kind"] == "gha":
        repository = urlsplit(route["repository"]).path.strip("/")
        raw = cloud.command(["gh", "api", "--method", "GET", "repos/" + repository
                             + "/contents/" + quote(path, safe="/") + "?ref=" + route["commit"]])
        item = json.loads(raw)
        if item.get("type") != "file" or item.get("encoding") != "base64":
            raise ValueError("Persona manifest must be an ordinary file in the reviewed consumer commit")
        return json.loads(base64.b64decode(item["content"]).decode("utf-8-sig"))
    organization, project, _, repository = unquote(urlsplit(route["repository"]).path).strip("/").split("/")
    url = ("https://dev.azure.com/" + quote(organization, safe="") + "/" + quote(project, safe="")
           + "/_apis/git/repositories/" + quote(repository, safe="") + "/items?path="
           + quote("/" + path, safe="") + "&versionDescriptor.version=" + route["commit"]
           + "&versionDescriptor.versionType=commit&includeContent=true&api-version=7.1")
    item = cloud.request("GET", url, "https://app.vssps.visualstudio.com/")[2]
    if item.get("gitObjectType") != "blob" or not isinstance(item.get("content"), str):
        raise ValueError("Persona manifest must be an ordinary file in the reviewed consumer commit")
    return json.loads(item["content"])


def binding_values(document, values, steps):
    target = document["target"]
    result = copy.deepcopy(values)
    environment = "test" if target["environment"] == "stage" else target["environment"]
    projects = target["project_ids"]
    if len(projects) > 1:
        raise ValueError("groups-v1 requires one reviewed project manifest per registered deployment; split projects")
    location = {step["parameters"]["locationSuffix"] for step in steps
                if step["parameters"].get("locationSuffix")}
    if len(location) > 1:
        raise ValueError("Registered templates disagree on locationSuffix")
    result.update({
        "tenantId": target["tenant_id"], environment + "_sub_id": target["subscription_id"],
        "admin_aifactoryPrefixRG": target["prefix"], "admin_aifactorySuffixRG": "-" + target["suffix"],
        "project_number_000": projects[0] if projects else values.get("project_number_000", "001"),
    })
    if location:
        result["admin_locationSuffix"] = next(iter(location))
    for key in ("commonResourceGroup_param", "vnetResourceGroupBase", "projectPrefix", "projectSuffix"):
        actual = {step["parameters"][key] for step in steps if step["parameters"].get(key)}
        if len(actual) > 1:
            raise ValueError(f"Registered templates disagree on {key}")
        if actual:
            result[key] = next(iter(actual))
    return result


def validate_binding(pipeline, manifest, document, values):
    target = document["target"]
    check_identity(manifest, tenant=target["tenant_id"], environment=target["environment"],
                   project=values["project_number_000"])
    lake_enabled = str(values.get("enableProjectLakeAccess", "")).lower()
    gateway_only = str(values.get("deployOnlyAIGatewayNetworking", "")).lower() == "true"
    if manifest.get("lake") and (lake_enabled == "false" or gateway_only):
        raise ValueError("Persona lake policy conflicts with disabled/gateway-only configuration")
    scopes = pipeline.deployment_scopes(values, target["environment"])
    locked = {scope.lower() for scope in document["locks"]["scopes"]
              + document["locks"]["common_dependencies"]}
    if any(scope.lower() not in locked for scope in manifest["connectivity_scopes"]):
        raise ValueError("Persona connectivity grants require their exact registered scope locks; provision them separately when not part of this reviewed operation")
    for scope in ("common", "project"):
        if manifest[scope + "_scope"].lower() != scopes[scope].lower():
            raise ValueError(f"Persona {scope} scope differs from the generated registered RG")
        if (scope == "common" or target["project_ids"]) and scopes[scope].lower() not in locked:
            raise ValueError("Persona writes require the exact registered common/project scope locks")
    return scopes


def preflight(pipeline, manifest, values, environment, *, source_root=None, cli=None, project=True):
    existing = pipeline.guard_downgrade(values, environment, mode(values), cli)
    if manifest is None:
        return
    resolved = seeds(manifest, source_root=source_root, cli=cli)
    scope = "project" if project and existing["project"] else "common"
    if existing[scope]:
        report = pipeline.access.provision(manifest, scope=scope, execute=False, cli=cli)
        if report.get("state") == "blocked" or report.get("blockers"):
            raise ValueError("Existing persona access must be remediated before deployment: "
                             + "; ".join(report.get("blockers") or ["blocked"]))
    return resolved


def freeze(cloud, document, plan, source_root):
    values = selected_config(document["config"], document["target"]["environment"])
    enabled = mode(values) == "groups-v1"
    if not enabled:
        return
    pipeline = pipeline_module(source_root)
    values = binding_values(document, values, plan["steps"])
    manifest = pipeline.policy.validate_manifest(remote_manifest(cloud, document["route"], values), require_lake=True)
    validate_binding(pipeline, manifest, document, values)
    preflight(pipeline, manifest, values, document["target"]["environment"],
              source_root=source_root, project=bool(document["target"]["project_ids"]))
    for step in plan["steps"]:
        step["parameters"] = sanitize(step["parameters"])
        if step["template"].endswith("/08b-rbac-common-rg.bicep"):
            step["parameters"]["personaAccessMode"] = "groups-v1"
    plan["persona_access"] = {"mode": "groups-v1", "manifest": manifest, "path": relative_manifest(values)}


def worker(document, source_root, *, execute=False, cli=None):
    values = selected_config(document["config"], document["target"]["environment"])
    plan = document["deployment"]
    frozen = plan.get("persona_access")
    enabled = mode(values) == "groups-v1"
    if not enabled and frozen:
        raise ValueError("Frozen persona policy cannot be downgraded to legacy")
    if not enabled:
        return None
    pipeline = pipeline_module(source_root)
    values = binding_values(document, values, plan["steps"])
    if not isinstance(frozen, dict) or frozen.get("mode") != "groups-v1" or frozen.get("path") != relative_manifest(values):
        raise ValueError("A freshly reviewed registered persona deployment plan is required")
    manifest = pipeline.policy.validate_manifest(frozen["manifest"], require_lake=True)
    validate_binding(pipeline, manifest, document, values)
    for step in plan["steps"]:
        parameters = step["parameters"]
        if sanitize(parameters) != parameters:
            raise ValueError("Frozen template parameters still contain legacy human grants or lack persona tags")
        if step["template"].endswith("/08b-rbac-common-rg.bicep") and parameters.get("personaAccessMode") != "groups-v1":
            raise ValueError("Registered legacy common-RBAC step must explicitly disable legacy grants")
    if not execute:
        preflight(pipeline, manifest, values, document["target"]["environment"], source_root=source_root,
                  cli=cli, project=bool(document["target"]["project_ids"]))
        return None
    reports = {"common": pipeline.access.provision(manifest, scope="common", execute=True, cli=cli)}
    if document["target"]["project_ids"]:
        reports["project"] = pipeline.access.provision(manifest, scope="project", execute=True, cli=cli)
    return reports
