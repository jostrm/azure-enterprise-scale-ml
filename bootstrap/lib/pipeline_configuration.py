"""Create reviewable registered configuration drafts without the Factory API.

Writes only a new local azurefactory root. It never authenticates, publishes,
enrolls a writer, approves an operation or changes an existing factory.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

import aifactory_scaleset_config
import pipeline_inputs as inputs
import release_version


def _default_variables(source_root, spec):
    template = inputs.read_json(source_root, "environment_setup/aifactory/variables.json")

    def clear_placeholders(value):
        if isinstance(value, dict):
            return {key: clear_placeholders(item) for key, item in value.items()}
        if isinstance(value, list):
            return [clear_placeholders(item) for item in value]
        if isinstance(value, str) and value.startswith(("<todo>", "<optional>")):
            return ""
        return value

    inputs.require(isinstance(template.get("dev"), dict) and set(template) <= {"dev", "stage_prod"},
                   "unsupported-source-variables-template")
    values = clear_placeholders(template)
    values = {"dev": values["dev"], "stage_prod": {**copy.deepcopy(values["dev"]),
                                                 **values.get("stage_prod", {})}}
    network = aifactory_scaleset_config.subnet_plan(spec["cidr"])
    network.pop("cidr_selector")
    branch = release_version.branch_for(spec["version"])
    for section in ("dev", "stage_prod"):
        values[section].update(
            admin_aifactoryPrefixRG=spec["prefix"], admin_location=spec["region"],
            admin_locationSuffix=spec["region_short"], admin_aifactorySuffixRG="-" + spec["scale_set"],
            project_number_000=spec["project"], tenantId=spec["tenant"],
            dev_sub_id="", test_sub_id="", prod_sub_id="", aifactory_branch_chosen=branch,
            tags="{}", tagsProject="{}", GITHUB_NEW_REPO_VISIBILITY="private",
            commonLakeNamePrefixMax8chars=spec["prefix"].replace("-", "")[:8],
            inputCommonSPSecretKey="", project_service_principal_Secret_seeding_kv_name="",
            **network)
        values[section][inputs.SUBSCRIPTIONS[spec["environment"]]] = spec["subscription"]
        private = spec["network_mode"] in ("private", "hybrid")
        values[section].update(
            enablePublicGenAIAccess="false" if private else "true",
            allowPublicAccessWhenBehindVnet="false" if private else "true",
            enablePublicAccessWithPerimeter="true" if spec["network_mode"] == "hybrid" else "false",
            disableAgentNetworkInjection="false" if private else "true",
            useSelfHostedBuildAgent="true" if private else "false")
        if spec["version"] != "main":
            dotted = branch.removeprefix("release/v").split(".")
            values[section].update(aifactory_version_major=dotted[0], aifactory_version_minor=dotted[1])
    return values


def initial_document(source_root, spec, *, variables=None):
    required = {"factory", "prefix", "region", "region_short", "tenant", "subscription", "provider",
                "environment", "scale_set", "project", "cidr", "max_projects", "version", "network_mode"}
    inputs.require(isinstance(spec, dict) and set(spec) == required, "initial-configuration-fields-required")
    spec = copy.deepcopy(spec)
    inputs.readable_key(spec["factory"])
    inputs.identifier(spec["scale_set"])
    inputs.identifier(spec["project"])
    inputs.guid(spec["tenant"])
    inputs.guid(spec["subscription"])
    inputs.require(spec["environment"] in inputs.SUBSCRIPTIONS and spec["provider"] in ("gha", "ado"),
                   "initial-environment-provider-required")
    inputs.require(spec["network_mode"] in ("private", "hybrid", "public"), "explicit-network-mode-required")
    inputs.require(isinstance(spec["region_short"], str) and re.fullmatch(r"[a-z][a-z0-9]{1,7}", spec["region_short"]),
                   "region-short-name-required")
    spec["version"] = release_version.normalize(spec["version"])
    branch = release_version.branch_for(spec["version"])
    if spec["version"] != "main":
        inputs.require(tuple(map(int, branch.removeprefix("release/v").split("."))) >= (1, 25),
                       "registered-source-version-required")
    aifactory_scaleset_config.subnet_plan(spec["cidr"])
    factory_id, scale_id, project_id = (str(uuid4()) for _ in range(3))
    scale = {"id": scale_id, "environment": spec["environment"], "suffix": spec["scale_set"],
             "tenant_id": spec["tenant"], "subscription_id": spec["subscription"],
             "orchestrator": spec["provider"], "status": "draft", "owned_resource_ids": [],
             "network": {"vnet_cidr": spec["cidr"], "max_projects": spec["max_projects"]}}
    project = {"id": project_id, "key": "project-" + spec["project"] + "-" + spec["scale_set"],
               "number": spec["project"], "display_name": "Project " + spec["project"], "status": "draft",
               "storage_suffix": spec["scale_set"],
               "placements": [{"environment": spec["environment"], "scale_set_id": scale_id}]}
    factory = {"id": factory_id, "key": spec["factory"], "kind": "ai", "prefix": spec["prefix"],
               "region": spec["region"], "region_short_name": spec["region_short"],
               "default_orchestrator": spec["provider"], "aifactory_version": spec["version"],
               "version_ref": spec["version"], "status": "draft", "scale_sets": [scale], "projects": [project]}
    settings = {"orchestrator": spec["provider"], "network_mode": spec["network_mode"],
                "admin_aifactoryPrefixRG": spec["prefix"], "admin_location": spec["region"],
                "admin_locationSuffix": spec["region_short"],
                "version_branch": branch}
    config = {"factory": settings, "scale_sets": {scale_id: {"orchestrator": spec["provider"]}},
              "projects": {project_id: {"orchestrator": spec["provider"]}},
              "variables": {project_id: copy.deepcopy(variables) if variables is not None
                            else _default_variables(source_root, spec)}}
    document = {"schema_version": 2, "generation": str(uuid4()), "factories": [factory],
                "configurations": {factory_id: config}, "bindings": {}}
    inputs.validate_register(document)
    return document


def _draft(document, factory_key):
    inputs.validate_register(document)
    updated = copy.deepcopy(document)
    factories = [f for f in updated["factories"] if f["key"] == factory_key]
    inputs.require(len(factories) == 1, "exact-factory-required")
    updated["generation"] = str(uuid4())
    return updated, factories[0]


def add_scale(document, factory_key, spec):
    inputs.require(isinstance(spec, dict) and set(spec) == {
        "environment", "scale_set", "tenant", "subscription", "provider", "cidr", "max_projects"},
        "scale-configuration-fields-required")
    updated, factory = _draft(document, factory_key)
    inputs.identifier(spec["scale_set"])
    inputs.guid(spec["tenant"])
    inputs.guid(spec["subscription"])
    inputs.require(not any((s["environment"], s["suffix"]) == (spec["environment"], spec["scale_set"])
                           for s in factory["scale_sets"]), "duplicate-scale-definition")
    aifactory_scaleset_config.subnet_plan(spec["cidr"])
    scale_id = str(uuid4())
    factory["scale_sets"].append({
        "id": scale_id, "environment": spec["environment"], "suffix": spec["scale_set"],
        "tenant_id": spec["tenant"], "subscription_id": spec["subscription"], "orchestrator": spec["provider"],
        "status": "draft", "owned_resource_ids": [],
        "network": {"vnet_cidr": spec["cidr"], "max_projects": spec["max_projects"]}})
    updated["configurations"][factory["id"]]["scale_sets"][scale_id] = {"orchestrator": spec["provider"]}
    inputs.validate_register(updated)
    return updated


def upsert_project(source_root, document, factory_key, environment, scale_set, project_number, *, variables=None):
    updated, factory = _draft(document, factory_key)
    inputs.identifier(project_number)
    inputs.identifier(scale_set)
    scales = [s for s in factory["scale_sets"] if (s["environment"], s["suffix"]) == (environment, scale_set)]
    inputs.require(len(scales) == 1, "exact-scale-required")
    scale = scales[0]
    selected = [p for p in factory["projects"] if p["number"] == project_number and any(
        place == {"environment": environment, "scale_set_id": scale["id"]} for place in p["placements"])]
    inputs.require(len(selected) <= 1, "ambiguous-project")
    config = updated["configurations"][factory["id"]]
    if selected:
        inputs.require(variables is not None, "explicit-variables-required-for-update")
        project = selected[0]
    else:
        inputs.require(not any(p["storage_suffix"] == scale_set and p["number"] == project_number
                               for p in factory["projects"]), "project-home-occupied-use-explicit-placement-edit")
        project = {"id": str(uuid4()), "key": "project-" + project_number + "-" + scale_set,
                   "number": project_number, "display_name": "Project " + project_number,
                   "status": "draft", "storage_suffix": scale_set,
                   "placements": [{"environment": environment, "scale_set_id": scale["id"]}]}
        factory["projects"].append(project)
        config["projects"][project["id"]] = {"orchestrator": scale["orchestrator"]}
        if variables is None:
            inputs.require(config["factory"].get("network_mode") in ("private", "hybrid", "public"),
                           "explicit-factory-network-mode-required")
            spec = {"prefix": factory["prefix"], "region": factory["region"],
                    "region_short": factory["region_short_name"], "tenant": scale["tenant_id"],
                    "subscription": scale["subscription_id"], "environment": environment,
                    "scale_set": scale_set, "project": project_number, "cidr": scale["network"]["vnet_cidr"],
                    "version": factory["aifactory_version"], "network_mode": config["factory"]["network_mode"]}
            variables = _default_variables(source_root, spec)
    config["variables"][project["id"]] = copy.deepcopy(variables)
    inputs.validate_register(updated)
    return updated


def projections(document):
    """Render the existing schema-2 projection format from its canonical register."""
    inputs.validate_register(document)
    files = {}
    generation = document["generation"]
    for factory in document["factories"]:
        config = document["configurations"][factory["id"]]
        base = "factories/" + factory["key"]
        files[base + "/factory.json"] = {**factory, "generation": generation, "settings": config["factory"]}
        for suffix in sorted({s["suffix"] for s in factory["scale_sets"]}):
            scales = [s for s in factory["scale_sets"] if s["suffix"] == suffix]
            files[base + "/scalesets/" + suffix + "/scaleset_state.json"] = {
                "generation": generation, "factory_id": factory["id"], "suffix": suffix, "scale_sets": scales,
                "settings": {s["id"]: config["scale_sets"][s["id"]] for s in scales}}
        for project in factory["projects"]:
            destination = inputs.project_path("azurefactory", factory, project).removeprefix("azurefactory/")
            files[destination + "/project_state.json"] = {
                **project, "generation": generation, "factory_id": factory["id"],
                "settings": config["projects"][project["id"]]}
            files[destination + "/variables.json"] = config["variables"][project["id"]]
        for provider, binding in document["bindings"].get(factory["id"], {}).items():
            files[base + "/pipelines/" + provider + ".json"] = {
                "generation": generation, "factory_id": factory["id"], "configuration": binding}
    files["register.json"] = document
    return files


def write_new_root(repository_root, relative, document):
    repository_root = Path(repository_root).absolute()
    destination = inputs.ordinary_path(repository_root, relative)
    inputs.require(destination.name == "azurefactory" and destination.parent.is_dir(), "new-registered-root-required")
    inputs.require(not destination.exists(), "configuration-destination-exists")
    files = projections(document)
    temporary = Path(tempfile.mkdtemp(prefix=".pipeline-config-", dir=destination.parent))
    try:
        for name, value in files.items():
            path = temporary.joinpath(*inputs.relative_path(name).parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(value, stream, indent=2, allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
        # mkdir is the no-clobber reservation; existing roots are never replaced.
        destination.mkdir()
        for path in sorted(temporary.iterdir(), key=lambda p: p.name == "register.json"):
            path.rename(destination / path.name)
    finally:
        shutil.rmtree(temporary)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation", choices=("init", "add-scale", "upsert-project"), default="init")
    parser.add_argument("--repository-root", default=".")
    parser.add_argument("--azurefactory-root", default="azurefactory")
    parser.add_argument("--from-root", help="Existing registered root for a new edited draft; never modified.")
    parser.add_argument("--variables", help="Optional repository-relative complete variables.json; identities must agree.")
    for field in ("factory", "prefix", "region", "region-short", "tenant", "subscription", "provider",
                  "environment", "scale-set", "project", "cidr", "version", "network-mode"):
        parser.add_argument("--" + field)
    parser.add_argument("--max-projects", type=int, default=7)
    args = parser.parse_args(argv)
    try:
        values = inputs.read_json(args.repository_root, args.variables) if args.variables else None
        source_root = Path(__file__).resolve().parents[2]
        if args.operation == "init":
            inputs.require(args.from_root is None, "initial-draft-cannot-import-root")
            spec = {key: value for key, value in vars(args).items()
                    if key not in {"operation", "repository_root", "azurefactory_root", "from_root", "variables"}}
            document = initial_document(source_root, spec, variables=values)
        else:
            inputs.relative_path(args.from_root)
            document = inputs.read_json(args.repository_root, args.from_root + "/register.json")
            if args.operation == "add-scale":
                inputs.require(values is None, "variables-not-applicable-to-scale-definition")
                spec = {key: getattr(args, key) for key in (
                    "environment", "scale_set", "tenant", "subscription", "provider", "cidr", "max_projects")}
                document = add_scale(document, args.factory, spec)
            else:
                document = upsert_project(source_root, document, args.factory, args.environment,
                                          args.scale_set, args.project, variables=values)
        write_new_root(args.repository_root, args.azurefactory_root, document)
    except (inputs.InputError, OSError, ValueError):
        print("Configuration draft rejected; check inputs and use a new destination.", file=sys.stderr)
        return 2
    print("Created registered configuration draft. No deployment, enrollment or execution authorization was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
