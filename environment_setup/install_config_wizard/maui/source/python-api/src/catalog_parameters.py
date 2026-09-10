"""Schema-driven, protected, revision-bound local deployment parameter editing."""

import base64
import copy
import json
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

from pydantic import ValidationError

from src import catalog_arm_schema, catalog_settings, factory_catalog as catalog, operations, simple_mode
from src.catalog_frozen_plan import CATALOG_NETWORK_PARAMETERS, FrozenPlanner
from src.catalog_parameter_models import CatalogParameterPrepare
from src.catalog_protocol import fingerprint
from src.catalog_storage import CatalogError, atomic_write, catalog_lock, database, encode, ordinary, read_json, root_folder
from src.factory_catalog_models import RuntimeBinding
from src.ticket_connectors import TicketError


SECTIONS = ("parameters", "resource_groups", "template_spec_ids")
KIND = "catalog-parameters-v1"
IMMUTABLE = {"env", "location", "commonRGNamePrefix", "aifactorySuffixRG", "projectNumber",
             "tenantId", "subscriptionId", "subscriptionIdDevTestProd",
             "enableAIFactoryCreatedDefaultProjectForAIFv2"} | CATALOG_NETWORK_PARAMETERS


class ParameterService:
    def __init__(self, service, compiler=None):
        self.service, self.runtime = service, service.runtime
        self.planner = FrozenPlanner(self.runtime)
        self.compiler = compiler or self._compile

    def _protect(self, data):
        try:
            return self.runtime.protector(data)
        except ValueError:
            raise CatalogError("Current-user DPAPI protection is unavailable; no plaintext parameter artifact was written.", 409) from None

    def _compile_template(self, source, path):
        cli = self.runtime.cli
        tools = cli.tools()
        if "az" not in tools:
            raise CatalogError("Install Azure CLI and the selected release's Bicep compiler before editing parameters.", 409)
        prefix = [tools["az"]]
        if sys.platform == "win32" and not cli.injected:
            prefix = operations._azure_cli_command(tools["az"])
        try:
            result = cli.runner([*prefix, "bicep", "build", "--file", str(path), "--stdout"],
                                cwd=str(source), stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, encoding="utf-8", timeout=120, shell=False,
                                env=simple_mode.launch_environment({}, tools))
        except (OSError, subprocess.SubprocessError):
            raise CatalogError("Local Bicep compilation is unavailable or timed out; verify the installed compiler/modules.", 409) from None
        if result.returncode != 0:
            raise CatalogError("Local Bicep compilation failed; install or restore the selected release's compiler/modules.", 409)
        # Real Foundry templates exceed the general CLI reader's 2 MB bound.
        if len(result.stdout.encode("utf-8")) > 8 * 1024 * 1024:
            raise CatalogError("The compiled template exceeds the published runtime's 8 MiB limit.", 409)
        try:
            return json.loads(result.stdout)
        except ValueError:
            raise CatalogError("The Bicep compiler returned malformed template JSON.", 409) from None

    def _compile(self, root, version, project, variables):
        module, source = self.planner.module(root, version)
        cli = self.runtime.cli

        def command(argv, cwd=None):
            if argv[0] != "git":
                raise CatalogError("Source verification requested an unsupported command.", 409)
            return cli.read("git", ["-c", "core.hooksPath=NUL", "-c", "core.fsmonitor=false",
                                   "-C", str(cwd), *argv[1:]], raw=True, allow_empty=True).strip()

        try:
            module.verify_source(SimpleNamespace(command=command), source,
                                 {"commit": version["resolved_ref"], "ref": "refs/heads/" + version["branch"]})
            try:
                cli.read("az", ["bicep", "version"], raw=True)
            except TicketError:
                raise CatalogError("Install the selected release's Bicep compiler on the API host before editing parameters; schema compilation requires no Azure sign-in.", 409) from None
            if project:
                paths = sorted(module.PROJECT_TEMPLATES)
            else:
                paths = [module.COMMON_TEMPLATES[name] for name in ("11-rgCommon", "12-networkCommon", "13-rgLevel")
                         if name != "12-networkCommon" or str(variables.get("BYO_subnets", "false")).lower() != "true"]
            result = {}
            for relative in paths:
                path = ordinary(source / Path(relative))
                if not path.is_relative_to(source) or not path.is_file():
                    raise CatalogError("The exact published parameter template is not installed.", 409)
                command(["git", "ls-files", "--error-unmatch", "--", str(path.relative_to(source))], cwd=str(source))
                compiled = self._compile_template(source, path)
                if not isinstance(compiled, dict) or not isinstance(compiled.get("parameters"), dict):
                    raise CatalogError("The selected Bicep compiler returned an invalid parameter schema.", 409)
                stem = path.stem
                if stem in result:
                    raise CatalogError("Published parameter template names are ambiguous.", 409)
                result[stem] = compiled
            module.verify_source(SimpleNamespace(command=command), source,
                                 {"commit": version["resolved_ref"], "ref": "refs/heads/" + version["branch"]})
            return result
        except module.Blocked:
            raise CatalogError("Install a clean, published source checkout and its Bicep compiler before editing parameters; no authentication or deployment is started.", 409) from None

    @staticmethod
    def _binding(root, factory, scale):
        path = ordinary(root / "config-wizard" / "factories" / factory["key"] / "orchestrators"
                        / (scale["orchestrator"] + ".json"))
        if not path.exists():
            return [], []
        try:
            binding = RuntimeBinding.model_validate(read_json(path)).model_dump(mode="json")
        except ValidationError:
            raise CatalogError("The selected local binding is invalid; configure it before choosing resource groups.", 409) from None
        catalog._validate_local_binding(root, catalog.load_document(root), factory, binding)
        target = next((item for item in binding["targets"] if item["scale_set_id"] == scale["id"]), None)
        return (target["resource_group_ids"], target["common_dependency_ids"]) if target else ([], [])

    @staticmethod
    def _effective(profile, project_id):
        result = {name: copy.deepcopy(profile.get(name, {})) for name in SECTIONS}
        if project_id:
            overrides = profile.get("projects", {}).get(project_id, {})
            for name in SECTIONS:
                for template, value in overrides.get(name, {}).items():
                    result[name][template] = ({**result[name].get(template, {}), **value}
                                              if name == "parameters" else copy.deepcopy(value))
        return result

    def _context(self, root, factory_id, scale_set_id, project_id=None, version_ref=None):
        revision = catalog.source_revision(root)
        document = catalog.load_document(root)
        factory, scale, project = catalog_settings.selection(document, factory_id, scale_set_id, project_id)
        if version_ref is None and factory.get("aifactory_version") is None:
            raise CatalogError("This factory's code version is unknown; explicitly select a published version before editing parameters.", 409)
        version = self.runtime.resolver(root, version_ref or factory.get("aifactory_version"))
        request = {"project_id": project_id}
        config = self.runtime._configuration(factory, [scale], document, request, version.get("template_variables"))
        variables = config["targets"][scale["id"]]["dev" if scale["environment"] == "dev" else "stage_prod"]
        variables = {**variables, "dev_test_prod": "test" if scale["environment"] == "stage" else scale["environment"],
                     "dev_test_prod_sub_id": scale["subscription_id"]}
        templates = self.compiler(root, version, project, variables)
        if not templates:
            raise CatalogError("The selected published release has no compatible parameter schemas.", 409)
        schemas = {name: catalog_arm_schema.parameter_schema(template["parameters"], template.get("definitions"))
                   for name, template in templates.items()}
        for schema in schemas.values():
            for name in IMMUTABLE & set(schema["properties"]):
                schema["properties"][name]["readOnly"] = True
        profile = self.planner._profile(SimpleNamespace(unprotect=self.runtime.unprotector), root, factory, scale,
                                        version, check_version=False)
        reset = profile.get("source_commit", version["resolved_ref"]) != version["resolved_ref"]
        effective = self._effective({} if reset else profile, project_id)
        groups, dependencies = self._binding(root, factory, scale)
        target = {"factory_id": factory["id"], "scaleset_id": scale["id"], "prefix": factory["prefix"],
                  "region": factory["region"], "suffix": scale["suffix"], "environment": scale["environment"],
                  "tenant_id": scale["tenant_id"], "subscription_id": scale["subscription_id"]}
        views = []
        for name, template in templates.items():
            fields = []
            for parameter, definition in template["parameters"].items():
                configured = parameter in effective["parameters"].get(name, {})
                overrides = {parameter: effective["parameters"][name][parameter]} if configured else {}
                try:
                    self.planner.parameters({parameter: definition}, variables, overrides, target,
                                            project["number"] if project else None, template.get("definitions"))
                    resolved = True
                except CatalogError:
                    resolved = False
                resolved_definition = catalog_arm_schema.arm_definition(definition, template.get("definitions", {}))
                fields.append({"name": parameter, "required": catalog_arm_schema.arm_kind(resolved_definition, {}).startswith("secure")
                               or ("defaultValue" not in resolved_definition and resolved_definition.get("nullable") is not True),
                               "resolved": resolved, "configured": configured,
                               "sensitive": catalog_arm_schema.sensitive(schemas[name]["properties"][parameter], schemas[name]["definitions"])
                               or catalog_settings.secret_field(parameter)})
            scope = "subscription" if "subscriptiondeploymenttemplate" in template.get("$schema", "").lower() else "resource-group"
            views.append({"template": name, "scope": scope, "parameter_schema": schemas[name], "fields": fields,
                          "resource_group_ids": groups if scope == "resource-group" else [],
                          "common_dependency_ids": dependencies})
        schema_revision = fingerprint({"version": version["resolved_ref"], "templates": templates,
                                       "factory": factory_id, "scale": scale_set_id, "project": project_id})
        if catalog.source_revision(root) != revision:
            raise CatalogError("Catalog settings changed during schema compilation; refresh.", 409)
        public = {"contract_version": 1, "source_revision": revision, "schema_revision": schema_revision,
                  "factory_id": factory_id, "scale_set_id": scale_set_id, "project_id": project_id,
                  "source_version": {"aifactory_version": version_ref, **{key: version[key] for key in
                                     ("requested_version", "branch", "resolved_ref")}},
                  "templates": views, "requires_profile_reset": reset,
                  "warnings": ["Values are never returned. Leave unchanged values untouched; supply only reviewed replacements.",
                               "Saving is local only. Deployment separately verifies complete parameters, source, live enrollment and ownership."]
                              + (["The existing protected profile targets another source commit; explicitly reset it to discard all old contexts."]
                                 if reset else [])}
        return public, {"factory": factory, "scale": scale, "project": project, "version": version, "profile": profile,
                        "effective": effective, "schemas": schemas, "templates": templates, "variables": variables,
                        "target": target, "groups": groups, "dependencies": dependencies}

    def read(self, folder, factory_id, scale_set_id, project_id=None, version_ref=None):
        root = root_folder(folder)
        with catalog_lock(root):
            return self._context(root, factory_id, scale_set_id, project_id, version_ref)[0]

    def _apply(self, request, public, context):
        if public["source_revision"] != request["expected_revision"] or public["schema_revision"] != request["schema_revision"]:
            raise CatalogError("The reviewed settings, source or parameter schema changed; refresh the form.", 409)
        if public["requires_profile_reset"] and not request["reset_profile"]:
            raise CatalogError("Explicitly review resetting the old version's complete protected profile before saving.", 409)
        profile = {} if request["reset_profile"] else copy.deepcopy(context["profile"])
        profile.update(schema=1, source_commit=context["version"]["resolved_ref"])
        for section in SECTIONS:
            profile.setdefault(section, {})
        destination = profile
        if request["project_id"]:
            destination = profile.setdefault("projects", {}).setdefault(request["project_id"], {})
            for section in SECTIONS:
                destination.setdefault(section, {})
        effects = []
        if request["reset_profile"]:
            effects.append("Discard every old parameter profile context in this scale set before saving the reviewed replacements.")
        for patch in request["templates"]:
            stem = patch["template"]
            if stem not in context["templates"]:
                raise CatalogError("Choose only templates from the selected published context.", 409)
            schema = context["schemas"][stem]
            if set(patch["unset"]) - set(schema["properties"]):
                raise CatalogError("Only published parameter names can be unset.", 409)
            catalog_arm_schema.validate_values(schema, patch["parameters"])
            if set(patch["parameters"]) & IMMUTABLE:
                raise CatalogError("Factory, scale-set, project and creation-only parameters are fixed by the selected identity.", 409)
            if patch["parameters"]:
                try:
                    definitions = context["templates"][stem]
                    subset = {name: definitions["parameters"][name] for name in patch["parameters"]}
                    self.planner.parameters(subset, context["variables"], patch["parameters"], context["target"],
                                            context["project"]["number"] if context["project"] else None,
                                            definitions.get("definitions"))
                except CatalogError:
                    raise CatalogError("A reviewed value is unresolved or conflicts with the selected target/ownership.", 409) from None
            values = destination["parameters"].setdefault(stem, {})
            for name in patch["unset"]:
                values.pop(name, None)
            values.update(copy.deepcopy(patch["parameters"]))
            if patch["resource_group_id"] is not None:
                group = patch["resource_group_id"]
                scope = next(item["scope"] for item in public["templates"] if item["template"] == stem)
                if scope != "resource-group" or group.lower() not in {item.lower() for item in context["groups"]}:
                    raise CatalogError("Choose an exact writable resource group from the selected local binding.", 409)
                destination["resource_groups"][stem] = group
            if patch["template_spec_id"] is not None:
                spec = patch["template_spec_id"]
                match = re.fullmatch(r"(/subscriptions/[a-f0-9-]{36}/resourceGroups/[^/]+)/providers/Microsoft.Resources/templateSpecs/([A-Za-z0-9_.()-]{1,90})/versions/([A-Za-z0-9_.-]{1,90})", spec, re.I)
                if (not match or match[1].lower() not in {item.lower() for item in context["dependencies"]}
                        or match[2] in (".", "..") or match[3] in (".", "..")):
                    raise CatalogError("An immutable template-spec version must belong to an explicit shared dependency group.", 409)
                destination["template_spec_ids"][stem] = spec
            effects.append(f"{stem}: replace {len(patch['parameters'])} parameter(s), unset {len(patch['unset'])}; preserve unedited settings.")
        if len(encode(profile)) > 4 * 1024 * 1024 - 4096:
            raise CatalogError("The protected parameter profile exceeds its supported size.", 409)
        return profile, effects

    def prepare(self, body, owner):
        request = CatalogParameterPrepare.model_validate(body).model_dump(mode="json")
        root = root_folder(request["folder"])
        with catalog_lock(root):
            public, context = self._context(root, **{key: request[key] for key in
                                                     ("factory_id", "scale_set_id", "project_id", "version_ref")})
            profile, effects = self._apply(request, public, context)
            identifier, expires = str(uuid4()), self.service.clock() + 600
            sealed = base64.b64encode(self._protect(encode({"request": request, "profile": profile}))).decode("ascii")
            preview = {"contract_version": 1, "confirmation_id": identifier, "can_execute": True,
                       "summary": "configure-parameters: " + context["factory"]["key"], "effects": effects,
                       "warnings": public["warnings"], "blockers": [], "expires_at": catalog.utc(expires),
                       "source_revision": public["source_revision"], "operation_mode": "configuration",
                       "target": context["factory"], "inventory": [], "source_version": public["source_version"], "binding": None}
            payload = {"kind": KIND, "preview": preview, "sealed": sealed}
            with database(root) as db:
                db.execute("INSERT INTO confirmations(id,owner,expires,revision,payload) VALUES (?,?,?,?,?)",
                           (identifier, owner, expires, public["source_revision"], json.dumps(payload)))
            return preview

    def confirm(self, folder, confirmation_id, owner):
        root = root_folder(folder)
        with catalog_lock(root), database(root) as db:
            row = db.execute("SELECT * FROM confirmations WHERE id=? AND owner=?", (str(confirmation_id), owner)).fetchone()
            if not row:
                raise CatalogError("Confirmation not found for this authenticated caller.", 404)
            payload = json.loads(row["payload"])
            if payload.get("kind") != KIND:
                raise CatalogError("This is not a parameter configuration confirmation.", 409)
            if row["consumed"] or row["expires"] <= self.service.clock() or catalog.source_revision(root) != row["revision"]:
                raise CatalogError("Parameter confirmation is expired, used or stale; prepare again.", 409)
            try:
                protected = json.loads(self.runtime.unprotector(base64.b64decode(payload["sealed"], validate=True)))
                request = CatalogParameterPrepare.model_validate(protected["request"]).model_dump(mode="json")
            except (ValueError, TypeError, KeyError):
                raise CatalogError("Protected parameter consent is unavailable; prepare again.", 409) from None
            public, context = self._context(root, **{key: request[key] for key in
                                                     ("factory_id", "scale_set_id", "project_id", "version_ref")})
            profile, _ = self._apply(request, public, context)
            if profile != protected["profile"] or self.service.clock() >= row["expires"]:
                raise CatalogError("Reviewed parameter configuration changed or expired; prepare again.", 409)
            destination = self.planner.profile_path(root, context["factory"], context["scale"])
            atomic_write(destination, self._protect(encode(profile)))
            payload["sealed"] = None
            db.execute("UPDATE confirmations SET consumed=1,payload=? WHERE id=?", (json.dumps(payload), str(confirmation_id)))
            return {"contract_version": 1, "catalog": catalog.summary(root), "job": None}
