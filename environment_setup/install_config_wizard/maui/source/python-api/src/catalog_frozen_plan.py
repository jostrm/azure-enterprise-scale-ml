"""Compile catalog settings into the published scoped ARM/ownership protocols."""

import copy
import hashlib
import json
from pathlib import Path
import re
import types
from uuid import uuid4

from src import catalog_protocol as protocol
from src.catalog_storage import CatalogError, ordinary


CATALOG_NETWORK_PARAMETERS = {"common_vnet_cidr", "common_subnet_cidr", "common_subnet_scoring_cidr",
                              "common_pbi_subnet_cidr", "common_bastion_subnet_cidr"}


class FrozenPlanner:
    def __init__(self, runtime, cloud_factory=None):
        self.runtime = runtime
        self.cloud_factory = cloud_factory

    def module(self, root, version):
        cache = ordinary(root / "config-wizard" / "catalog-sources" / version["resolved_ref"])
        source = cache / "source"
        if not source.exists():
            source = ordinary(Path(version["repository"]))
        if not source.is_dir():
            raise CatalogError("Install a clean checkout of the selected published release before scoped preparation; preparation never clones or checks out source.", 409)
        helper = ordinary(source / "bootstrap" / "lib" / "factory_lifecycle.py")
        text = helper.read_text(encoding="utf-8")
        if hashlib.sha256(text.encode()).hexdigest() != version["helper_sha256"]:
            raise CatalogError("Cached published lifecycle helper changed; reinstall the selected release.", 409)
        module = types.ModuleType("catalog_published_lifecycle")
        module.__file__ = str(helper)
        exec(compile(text, str(helper), "exec"), module.__dict__)
        if any(not callable(getattr(module, name, None)) for name in
               ("Cloud", "Blocked", "verify_source", "validate_manifest", "manifest_digest", "unprotect", "capabilities")):
            raise CatalogError("Selected published lifecycle helper is incomplete; publish/fetch a compatible scoped runtime.", 409)
        return module, source

    @staticmethod
    def profile_path(root, factory, scale):
        return ordinary(root / "config-wizard" / "factories" / factory["key"] / "scalesets"
                        / scale["environment"] / scale["suffix"] / "deployment_parameters.dpapi")

    def _profile(self, module, root, factory, scale, version, *, check_version=True, project_id=None):
        path = self.profile_path(root, factory, scale)
        if not path.exists():
            return {"parameters": {}, "resource_groups": {}, "template_spec_ids": {}}
        if path.stat().st_size > 4 * 1024 * 1024:
            raise CatalogError("Protected deployment parameters exceed the supported size.", 409)
        try:
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("Duplicate profile key")
                    result[key] = value
                return result
            def nonfinite(value):
                raise ValueError("Nonfinite profile value")
            value = json.loads(module.unprotect(path.read_bytes()).decode("utf-8"),
                               object_pairs_hook=unique, parse_constant=nonfinite)
            if (not isinstance(value, dict) or set(value) - {"schema", "source_commit", "parameters", "resource_groups", "template_spec_ids", "projects"}
                    or value.get("schema") != 1
                    or check_version and value.get("source_commit", version["resolved_ref"]) != version["resolved_ref"]):
                raise ValueError("Wrong profile schema/version")
            for name in ("parameters", "resource_groups", "template_spec_ids"):
                value.setdefault(name, {})
                if not isinstance(value[name], dict):
                    raise ValueError("Wrong profile section")
                if name == "parameters" and any(not isinstance(item, dict) for item in value[name].values()):
                    raise ValueError("Wrong parameter map")
            projects = value.get("projects", {})
            if not isinstance(projects, dict):
                raise ValueError("Wrong project profile section")
            for project, sections in projects.items():
                if (not isinstance(project, str) or not isinstance(sections, dict)
                        or set(sections) - {"parameters", "resource_groups", "template_spec_ids"}
                        or any(not isinstance(section, dict) for section in sections.values())):
                    raise ValueError("Wrong project parameter profile")
                if any(not isinstance(item, dict) for item in sections.get("parameters", {}).values()):
                    raise ValueError("Wrong project parameter map")
            if project_id:
                value = copy.deepcopy(value)
                for name in ("parameters", "resource_groups", "template_spec_ids"):
                    selected = projects.get(project_id, {}).get(name, {})
                    if name == "parameters":
                        for template, overrides in selected.items():
                            value[name][template] = {**value[name].get(template, {}), **overrides}
                    else:
                        value[name].update(selected)
            return value
        except (ValueError, TypeError, UnicodeError):
            raise CatalogError("Protected deployment parameters are malformed, belong to another OS user, or target another code version.", 409) from None

    @staticmethod
    def _expand(value, variables, stack=()):
        if isinstance(value, dict):
            return {key: FrozenPlanner._expand(item, variables, stack) for key, item in value.items()}
        if isinstance(value, list):
            return [FrozenPlanner._expand(item, variables, stack) for item in value]
        if not isinstance(value, str):
            return copy.deepcopy(value)
        def substitute(match):
            name = match[1]
            if name in stack or name not in variables:
                raise CatalogError("Unresolved published parameter variable: " + name, 409)
            replacement = FrozenPlanner._expand(variables[name], variables, (*stack, name))
            if isinstance(replacement, (dict, list)):
                return json.dumps(replacement)
            return str(replacement)
        value = re.sub(r"\$\(([A-Za-z0-9_.-]+)\)", substitute, value)
        if "<todo>" in value.lower() or "$(" in value or "${{" in value or re.match(r"^\[[A-Za-z][A-Za-z0-9]*\(", value):
            raise CatalogError("Deployment parameters contain unresolved settings; complete the selected configuration first.", 409)
        return value

    @staticmethod
    def parameters(schema, variables, overrides, target, project=None, definitions=None):
        from src.catalog_arm_schema import arm_definition, arm_kind, parameter_schema, validate_values
        if not isinstance(overrides, dict) or set(overrides) - set(schema):
            raise CatalogError("Protected parameter keys do not match the exact published template schema.", 409)
        required = {"env": "test" if target["environment"] == "stage" else target["environment"],
                    "location": target["region"], "commonRGNamePrefix": target["prefix"],
                    "aifactorySuffixRG": "-" + target["suffix"]}
        if project:
            required["projectNumber"] = project
        else:
            required["enableAIFactoryCreatedDefaultProjectForAIFv2"] = False
        for name, key in (("tenantId", "tenant_id"), ("subscriptionId", "subscription_id"),
                          ("subscriptionIdDevTestProd", "subscription_id")):
            if key in target:
                required[name] = target[key]
        for name in CATALOG_NETWORK_PARAMETERS:
            if name in variables:
                required[name] = variables[name]
        ownership_tags = {"aifactory.factory_id": target["factory_id"], "aifactory.scaleset_id": target["scaleset_id"]}
        if project:
            ownership_tags["aifactory.project_id"] = project
        for tag_parameter in ("tags", "tagsProject"):
            if tag_parameter not in schema:
                continue
            source_tags = variables.get("tagsProject" if project else "tags", schema[tag_parameter].get("defaultValue", {}))
            def tag_object(value):
                if value is None or value == "":
                    return {}
                if isinstance(value, str):
                    try:
                        value = json.loads(value)
                    except ValueError:
                        raise CatalogError("Published tags require a resolved JSON object.", 409) from None
                if not isinstance(value, dict):
                    raise CatalogError("Published tags require a resolved JSON object.", 409)
                return copy.deepcopy(value)
            source_tags = tag_object(source_tags)
            if project:
                logical = source_tags.get("aifactory.logical_project_id")
                if logical:
                    ownership_tags["aifactory.logical_project_id"] = logical
            tags = FrozenPlanner._expand({**source_tags, **tag_object(overrides.get(tag_parameter))}, variables)
            if any(not isinstance(name, str) for name in tags):
                raise CatalogError("Published tag names must be strings.", 409)
            for name in list(tags):
                normalized = name.lower()
                if normalized in ownership_tags:
                    if tags[name] != ownership_tags[normalized]:
                        raise CatalogError("A tag conflicts with reviewed physical or logical ownership.", 409)
                    if name != normalized:
                        tags.pop(name)
                if not project and normalized in ("aifactory.project_id", "aifactory.logical_project_id"):
                    raise CatalogError("Common-only tags cannot claim a project identity.", 409)
            required[tag_parameter] = {**tags, **ownership_tags}
        aliases = {"locationSuffix": "admin_locationSuffix", "commonResourceSuffix": "admin_commonResourceSuffix",
                   "containerRegistrySkuName": "acr_SKU", "technicalAdminsObjectID": "technical_admins_ad_object_id",
                   "technicalAdminsEmail": "technical_admins_email", "vnetNameBase": "vnet_name_base",
                   "common_subnet_name": "subnet_common_base", "network_env": "network_env_" + target["environment"]}
        normalize = lambda name: re.sub(r"[^a-z0-9]", "", name.lower())
        result, missing = {}, []
        for name, definition in schema.items():
            definition = arm_definition(definition, definitions or {})
            if name in required:
                value = required[name]
                if name not in ("tags", "tagsProject") and name in overrides and overrides[name] != value:
                    raise CatalogError("A protected parameter conflicts with reviewed target/ownership: " + name, 409)
            elif name in overrides:
                value = overrides[name]
            elif aliases.get(name, name) in variables:
                value = variables[aliases.get(name, name)]
            else:
                matches = [value for key, value in variables.items()
                           if normalize(key.removeprefix("admin_")) == normalize(name)]
                if len(matches) == 1:
                    value = matches[0]
                elif (not arm_kind(definition, definitions or {}).startswith("secure")
                      and "defaultValue" in definition and not (
                        isinstance(definition["defaultValue"], str) and definition["defaultValue"].startswith("["))):
                    value = definition["defaultValue"]
                elif definition.get("nullable") is True and not arm_kind(definition, definitions or {}).startswith("secure"):
                    value = None
                else:
                    missing.append(name)
                    continue
            value = FrozenPlanner._expand(value, variables)
            kind = arm_kind(definition, definitions or {})
            if kind == "bool" and isinstance(value, str) and value.lower() in ("true", "false"):
                value = value.lower() == "true"
            if kind == "int" and isinstance(value, str) and re.fullmatch(r"-?\d+", value):
                value = int(value)
            if kind in ("object", "secureobject", "array") and isinstance(value, str):
                try:
                    value = json.loads(value)
                except ValueError:
                    raise CatalogError("A published structured parameter requires valid JSON: " + name, 409) from None
                value = FrozenPlanner._expand(value, variables)
            validate_values(parameter_schema({name: definition}, definitions), {name: value})
            result[name] = value
        if missing:
            raise CatalogError("Complete selected settings or the reviewed deployment-parameter form. Missing resolved parameters: "
                               + ", ".join(sorted(missing)), 409)
        return result

    def _deployment(self, module, cloud, root, factory, scale, document, source, version, ownership_records=None):
        target = document["target"]
        common = document["operation"] != "deploy-project"
        logical_project = next((project["id"] for project in factory["projects"]
                                if not common and project["number"] == target["project_ids"][0]
                                and any(item["scale_set_id"] == scale["id"] for item in project["placements"])), None)
        profile = self._profile(module, root, factory, scale, version, project_id=logical_project)
        if common:
            paths = [module.COMMON_TEMPLATES[name] for name in ("11-rgCommon", "12-networkCommon", "13-rgLevel")]
        else:
            paths = sorted(module.PROJECT_TEMPLATES, key=lambda path: (0 if Path(path).stem == "31-network" else 1, path))
        known = {Path(path).stem for path in [*module.COMMON_TEMPLATES.values(), *module.PROJECT_TEMPLATES]}
        if any(set(profile[section]) - known for section in ("parameters", "resource_groups", "template_spec_ids")):
            raise CatalogError("Protected deployment profile names an unapproved template.", 409)
        section = "dev" if scale["environment"] == "dev" else "stage_prod"
        variables = document["config"][section]
        variables = {**variables, "dev_test_prod": "test" if scale["environment"] == "stage" else scale["environment"],
                     "dev_test_prod_sub_id": scale["subscription_id"]}
        byo = str(variables.get("BYO_subnets", "false")).lower() == "true"
        if common and byo:
            paths.remove(module.COMMON_TEMPLATES["12-networkCommon"])
        steps = []
        for path in paths:
            template = cloud.compile_template(source, path)
            stem = Path(path).stem
            scope = "subscription" if "subscriptiondeploymenttemplate" in template.get("$schema", "").lower() else "resource-group"
            parameters = self.parameters(template["parameters"], variables, profile["parameters"].get(stem, {}),
                                         target, target["project_ids"][0] if not common else None, template.get("definitions"))
            step = {"id": "step-" + stem, "kind": "common" if common else "project", "template": path,
                    "template_hash": module.digest(template), "parameters": parameters, "scope": scope,
                    "resource_groups": document["locks"]["scopes"], "depends_on": [steps[-1]["id"]] if steps else []}
            if not common:
                step["project_id"] = target["project_ids"][0]
                step["owner"] = {key: target[key] for key in ("factory_id", "scaleset_id")}
                step["owner"]["project_id"] = step["project_id"]
            if scope == "resource-group":
                group = profile["resource_groups"].get(stem)
                if group is None and len(document["locks"]["scopes"]) == 1:
                    group = document["locks"]["scopes"][0]
                if not isinstance(group, str) or group.lower() not in {value.lower() for value in document["locks"]["scopes"]}:
                    raise CatalogError("Specify the exact enrolled resource group for template " + stem + " in the protected profile.", 409)
                step["resource_group"] = group
            if stem in profile["template_spec_ids"]:
                step["template_spec_id"] = profile["template_spec_ids"][stem]
            steps.append(step)
        if common:
            document["config"] = {"environment": scale["environment"],
                                  "common_parameters": {step["id"]: step["parameters"] for step in steps},
                                  **{key: variables[key] for key in (
                                      "useSelfHostedBuildAgent", "selfHostedRunnerLabel", "adminVMBuildAgentPool",
                                      "adminVMBuildAgentName", "BYO_subnets") if key in variables}}
        document["deployment"] = {"contract": 1, "network_mode": "byo" if byo else "managed",
                                  "configuration_hash": module.digest(document["config"]), "steps": steps,
                                  "known_ownership": {resource.lower(): record["ownership_evidence"]
                                                      for resource, record in (ownership_records or {}).items()
                                                      if "/providers/" in resource.lower()
                                                      and record["owner"].get("factory_id") == factory["id"]
                                                      and record["owner"].get("scaleset_id") == scale["id"]},
                                  "changes": [{"resource_id": document["locks"]["scopes"][0], "change_type": "NoChange",
                                               "before_hash": None, "after_hash": None}]}
        module.validate_deployment_plan(document)
        document["deployment"] = module.freeze_deployment_plan(cloud, document, source)

    def prepare(self, root, request, catalog, version, bindings, evidence, config, now, expires):
        from src.factory_catalog import select_factory, select_scale
        factory = select_factory(catalog, request["factory_id"])
        scales = [select_scale(factory, request["scale_set_id"])] if request["scale_set_id"] else factory["scale_sets"]
        module, source = self.module(root, version)
        capabilities = module.capabilities()
        if not isinstance(capabilities, dict) or capabilities.get("contract") != 1:
            raise CatalogError("Selected published lifecycle capabilities are unsupported; install a compatible release.", 409)
        if request["action"].startswith("delete"):
            if capabilities.get("delete_owned_resource_groups") != "arm-provider-closure-v1":
                raise CatalogError("Selected published release lacks complete owned-group deletion capability.", 409)
            if request["action"] == "delete-factory" and (
                    capabilities.get("factory_cohort") != "physical-lease-cohort-v1"
                    or not callable(getattr(module, "execute_cohort", None))):
                raise CatalogError("Whole-factory deletion requires a published physical-lease-cohort-v1 runtime; sequential child execution is not allowed.", 409)
        else:
            if capabilities.get("scoped_group_ownership_receipt") != "resource-group-ownership-v1":
                raise CatalogError("Selected published release lacks verified resource-group ownership receipts; install a compatible lifecycle runtime.", 409)
            keys = ("scoped_worker_os", "scoped_runners", "project_routes")
            if (any(not isinstance(capabilities.get(key), list) for key in keys)
                    or any(binding["route"].get("runner", {}).get("os") not in capabilities["scoped_worker_os"]
                           or binding["route"].get("runner", {}).get("kind") not in capabilities["scoped_runners"]
                           or binding["route"]["kind"] not in capabilities["project_routes"] for binding in bindings)):
                raise CatalogError("Selected published release does not acknowledge the explicit scoped runner and route; publish/fetch a compatible runtime.", 409)
            if any(binding["route"]["shared_remote"] for binding in bindings) and capabilities.get("shared_remote_namespaced_auth") is not True:
                raise CatalogError("Selected published release lacks namespaced shared-remote authentication.", 409)
            if not request["project_id"] and capabilities.get("creation") != "frozen-arm-deployment-plan-v1":
                raise CatalogError("Selected published release lacks true frozen common-only creation.", 409)
        manifests = []
        for scale, binding in zip(scales, bindings):
            document = protocol.manifest(str(uuid4()), factory, scale, request, version, config, binding, evidence,
                                         [], now, expires, frozen=True)
            cloud = self.cloud_factory(module, document) if self.cloud_factory else module.Cloud(document)
            try:
                module.verify_source(cloud, source, document["source"])
                if request["action"].startswith("delete"):
                    if not hasattr(module, "freeze_deletion_inventory"):
                        raise CatalogError("Install a published release with arm-provider-closure-v1 deletion support.", 409)
                    if not {scope.lower() for scope in binding["locks"]["scopes"]} <= {resource.lower() for resource in scale["owned_resource_ids"]}:
                        raise CatalogError("Full deletion requires explicit registered ownership of every resource group; leaf ownership cannot authorize a group cascade.", 409)
                    records = catalog.get("ownership_evidence", {})
                    document["deletion"] = module.freeze_deletion_inventory(cloud, document, records)
                else:
                    if not hasattr(module, "freeze_deployment_plan"):
                        raise CatalogError("Install a published release supporting frozen-arm-deployment-plan-v1.", 409)
                    if not binding.get("_deployment_object_id") or binding["route"].get("scoped_contract") != 1:
                        raise CatalogError("Configure a namespaced scoped route and its deployment principal before frozen ARM execution.", 409)
                    document["identity"]["deployment_object_id"] = binding["_deployment_object_id"]
                    for scope in binding["locks"]["scopes"]:
                        status, _, body = cloud.arm("GET", scope, module.RG_API, allowed=(200, 404))
                        if status == 200:
                            module.verify_ownership(body, {key: document["target"][key] for key in ("factory_id", "scaleset_id")})
                    self._deployment(module, cloud, root, factory, scale, document, source, version,
                                     catalog.get("ownership_evidence", {}))
                document["manifest_hash"] = module.manifest_digest(document)
                module.validate_manifest(document)
            except module.Blocked as exc:
                raise CatalogError("Published scoped preparation blocked: " + exc.code + ". Resolve the configuration, enrollment or complete inventory prerequisite.", 409) from None
            manifests.append(document)
        return manifests

    def refresh(self, root, version, manifests, catalog):
        module, source = self.module(root, version)
        for document in manifests:
            cloud = self.cloud_factory(module, document) if self.cloud_factory else module.Cloud(document)
            try:
                if document["operation"] == "delete":
                    fresh = module.freeze_deletion_inventory(cloud, document, catalog.get("ownership_evidence", {}))
                    expected = document["deletion"]
                else:
                    fresh = module.freeze_deployment_plan(cloud, document, source)
                    expected = document["deployment"]
                if fresh != expected:
                    raise CatalogError("Complete scoped inventory or ARM what-if changed; prepare and review again.", 409)
            except module.Blocked as exc:
                raise CatalogError("Scoped confirmation blocked: " + exc.code, 409) from None
