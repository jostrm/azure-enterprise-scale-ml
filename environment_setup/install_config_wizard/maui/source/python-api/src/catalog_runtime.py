"""Owner-bound lifecycle jobs using immutable inputs and an isolated published runtime."""

from __future__ import annotations

import copy
import ast
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import threading
import time
from uuid import UUID, uuid4

import yaml

from src import release_version, simple_mode, wizard, catalog_protocol as protocol
from src.catalog_storage import CatalogError, atomic_write, catalog_lock, database, digest, encode, ordinary, read_json
from src.deployment_config import protect
from src.deployment_terminal import OwnedPty, TerminalSessions
from src.ticket_connectors import TicketError
from src.catalog_secrets import unprotect


CONTRACT = "AIFACTORY_LIFECYCLE_CONTRACT=1"
HELPER = "bootstrap/lib/factory_lifecycle.py"
TEMPLATE = "environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/variables/variables.yaml"
RESOURCE_ID = re.compile(r"^/subscriptions/([0-9a-f-]{36})/resourceGroups/([^/]+)(?:/providers/[^/]+(?:/[^/]+/[^/]+)+)?$", re.I)
ACTIVE = {"queued", "running"}


def _public(job):
    return {key: value for key, value in job.items() if not key.startswith("_")}


def _run_path(root, job_id):
    try:
        if str(UUID(job_id)) != job_id:
            raise ValueError("Noncanonical UUID")
    except (ValueError, TypeError, AttributeError):
        raise CatalogError("Stored lifecycle job identity is invalid.", 409) from None
    return ordinary(root / "config-wizard" / "catalog-runs" / job_id)


def _pid_alive(pid):
    if pid == os.getpid():
        return True
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class CatalogRuntime:
    def __init__(self, cli=None, inventory=None, resolver=None, materialize=None, pty_factory=None,
                 dispatch=None, clock=time.time, protector=protect, timeout=8 * 3600, binding=None, planner=None,
                 unprotector=unprotect):
        self.cli = cli or simple_mode.ReadOnlyCLI()
        self.inventory = inventory or self._inventory
        self.resolver = resolver or self._resolve
        self.binding = binding or (lambda root, factory, scale: protocol.load_binding(root, factory, scale, self.cli))
        self.materialize = materialize or self._materialize
        self.pty_factory = pty_factory or OwnedPty
        self.dispatch = dispatch or self._dispatch
        self.clock, self.protector, self.timeout = clock, protector, timeout
        self.unprotector = unprotector
        from src.catalog_frozen_plan import FrozenPlanner
        self.planner = planner or FrozenPlanner(self)
        self.terminals = TerminalSessions()
        self.running = {}
        self.lock = threading.RLock()

    def _resolve(self, root, version):
        repository = ordinary(root.parent / "azure-enterprise-scale-ml")
        try:
            selected = release_version.published_source(
                version, self.cli, repository,
                saved=release_version.saved_version(root.parent) if version is None else None,
                required_paths={HELPER: CONTRACT})
            text = self.cli.read("git", ["-C", str(repository), "show", selected["resolved_ref"] + ":" + HELPER], raw=True)
            template = self.cli.read("git", ["-C", str(repository), "show", selected["resolved_ref"] + ":" + TEMPLATE], raw=True)
        except TicketError:
            raise CatalogError("Selected published version has no locally cached lifecycle helper. Fetch/install a release containing lifecycle contract 1; no fallback is allowed.", 409) from None
        if CONTRACT not in text:
            raise CatalogError("Selected published release lacks lifecycle contract 1. Publish and fetch a compatible release; no old-release fallback is allowed.", 409)
        try:
            functions = {node.name for node in ast.parse(text).body if isinstance(node, ast.FunctionDef)}
        except SyntaxError:
            raise CatalogError("Selected lifecycle helper requires a compatible installed Python backend.", 409) from None
        if not {"execute", "unprotect", "validate_manifest", "manifest_digest"} <= functions:
            raise CatalogError("Selected published helper lacks the protected in-memory lifecycle API; publish/fetch a compatible contract-1 release.", 409)
        try:
            variables = yaml.safe_load(template)["variables"]
            if not isinstance(variables, dict):
                raise ValueError("Invalid template variables")
        except (yaml.YAMLError, ValueError, TypeError, KeyError):
            raise CatalogError("Selected published release has no usable complete variables template.", 409) from None
        return {**selected, "repository": str(repository), "helper_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "template_variables": variables}

    def _inventory(self, root, factory, scales):
        """Inventory every selected subscription, never infer ownership from names."""
        started = self.clock()
        records, accounts = [], []
        for subscription in sorted({ss["subscription_id"] for ss in scales}):
            account = self.cli.read("az", ["account", "show", "--subscription", subscription, "--output", "json"])
            tenants = {ss["tenant_id"].lower() for ss in scales if ss["subscription_id"] == subscription}
            if (not isinstance(account, dict) or str(account.get("id", "")).lower() != subscription.lower()
                    or tenants != {str(account.get("tenantId", "")).lower()}):
                raise CatalogError("Selected subscription is not authenticated in its configured tenant. Sign in explicitly before preparation.", 409)
            user = account.get("user") or {}
            accounts.append({"subscription_id": subscription, "tenant_id": account["tenantId"],
                             "identity": str(user.get("name") or ""),
                             "object_id": protocol.token_identity(self.cli, next(ss for ss in scales if ss["subscription_id"] == subscription), self.clock)})
            if not accounts[-1]["identity"]:
                raise CatalogError("Current Azure CLI identity cannot be bound to this confirmation.", 409)
            resources = self.cli.read("az", ["resource", "list", "--subscription", subscription, "--output", "json"])
            groups = self.cli.read("az", ["group", "list", "--subscription", subscription, "--output", "json"])
            if not isinstance(resources, list) or not isinstance(groups, list):
                raise CatalogError("A complete fresh subscription inventory is required.", 409)
            registered_groups = {"/".join(resource.split("/")[:5]).lower()
                                 for ss in scales for resource in ss["owned_resource_ids"]}
            for item in [*groups, *resources]:
                if not isinstance(item, dict) or not RESOURCE_ID.fullmatch(str(item.get("id", ""))):
                    raise CatalogError("Azure inventory contains an unrecognized resource identity; no partial inventory is accepted.", 409)
                tags = item.get("tags") or {}
                if not isinstance(tags, dict):
                    raise CatalogError("Azure ownership tags are malformed.", 409)
                record = {"resource_id": item["id"], "dependencies": [],
                          "factory_id": tags.get("aifactory.factory_id"),
                          "scale_set_id": tags.get("aifactory.scaleset_id"),
                          "project_id": tags.get("aifactory.project_id"),
                          "shared": str(tags.get("aifactory.shared", "")).lower() == "true",
                          "type": item.get("type", "")}
                group = "/".join(item["id"].split("/")[:5]).lower()
                resource_type = str(item.get("type") or "").lower()
                api_version = "2022-09-01" if item["id"].lower() == group else protocol.LEAF_TYPES.get(resource_type)
                if group in registered_groups and api_version:
                    full = self.cli.read("az", ["rest", "--method", "GET", "--url",
                        "https://management.azure.com" + item["id"] + "?api-version=" + api_version, "--output", "json"])
                    if not isinstance(full, dict) or str(full.get("id", "")).lower() != item["id"].lower():
                        raise CatalogError("Fresh ARM fingerprint did not match the selected resource ID.", 409)
                    record.update(body_hash=protocol.fingerprint(full), etag=full.get("etag"))
                    properties = full.get("properties") or {}
                    for reference in (full.get("managedBy"), properties.get("ipConfiguration")):
                        value = reference.get("id") if isinstance(reference, dict) else reference
                        if value:
                            record["dependencies"].append(str(value))
                records.append(record)
        return {"complete": True, "observed_at": started, "records": records, "accounts": accounts}

    def _checked_inventory(self, root, factory, scales, deleting, full=False):
        evidence = self.inventory(root, factory, scales)
        if (evidence.get("complete") is not True or not isinstance(evidence.get("records"), list)
                or not isinstance(evidence.get("observed_at"), (int, float))
                or not 0 <= self.clock() - evidence["observed_at"] <= 60):
            raise CatalogError("Fresh, complete inventory is required; partial or stale evidence cannot authorize execution.", 409)
        evidence = copy.deepcopy(evidence)
        evidence["records"].sort(key=lambda item: str(item.get("resource_id", "")).lower() if isinstance(item, dict) else "")
        if not isinstance(evidence.get("accounts"), list) or not evidence["accounts"]:
            raise CatalogError("Fresh inventory must identify its authenticated Azure principal.", 409)
        try:
            actual_accounts = {(str(UUID(item["subscription_id"])), str(UUID(item["tenant_id"]))) for item in evidence["accounts"]}
            for item in evidence["accounts"]:
                UUID(item["object_id"])
        except (ValueError, TypeError, KeyError, AttributeError):
            raise CatalogError("Fresh inventory must identify exact subscription, tenant and authenticated object IDs.", 409) from None
        if actual_accounts != {(scale["subscription_id"], scale["tenant_id"]) for scale in scales}:
            raise CatalogError("Inventory principal context does not match the selected physical targets.", 409)
        evidence["accounts"].sort(key=lambda item: str(item.get("subscription_id", "")))
        registered = {resource.lower(): ss for ss in scales for resource in ss["owned_resource_ids"]}
        selected_ids = {ss["id"] for ss in scales}
        observed = {}
        for item in evidence["records"]:
            if not isinstance(item, dict):
                raise CatalogError("Inventory must contain concrete typed resource records.", 409)
            resource = str(item.get("resource_id") or "")
            match = RESOURCE_ID.fullmatch(resource)
            if not match or resource.lower() in observed:
                raise CatalogError("Inventory has malformed or duplicate resource IDs.", 409)
            if match.group(1).lower() not in {ss["subscription_id"].lower() for ss in scales}:
                raise CatalogError("Inventory escaped the selected subscriptions.", 409)
            if not isinstance(item.get("dependencies", []), list) or any(
                    not isinstance(value, str) or not RESOURCE_ID.fullmatch(value) for value in item.get("dependencies", [])):
                raise CatalogError("Inventory dependencies must be concrete resource IDs.", 409)
            observed[resource.lower()] = item
        allowlist = []
        for resource, scale in registered.items():
            parsed = RESOURCE_ID.fullmatch(resource)
            if not parsed or parsed[1].lower() != scale["subscription_id"].lower():
                raise CatalogError("Registered resource ownership escaped its physical subscription.", 409)
            item = observed.get(resource)
            if item is None:
                # Absence is evidence, not permission to guess or delete a resource elsewhere.
                continue
            if (item.get("shared") or (item.get("factory_id") != factory["id"]
                    or item.get("scale_set_id") != scale["id"]) and not (
                        full and not item.get("factory_id") and not item.get("scale_set_id"))):
                raise CatalogError("Registered resource ownership is ambiguous, external or shared; execution is blocked.", 409)
            allowlist.append({"resource_id": item["resource_id"], "dependencies": list(item.get("dependencies", []))})
        for item in observed.values():
            if item.get("factory_id") == factory["id"] and item.get("scale_set_id") in selected_ids:
                if item["resource_id"].lower() not in registered:
                    if not full or "/".join(item["resource_id"].split("/")[:5]).lower() not in registered:
                        raise CatalogError("Inventory contains unregistered owned resources. Reconcile ownership before deleting or deploying.", 409)
        if deleting and any(ss["status"] == "configured" and not ss["owned_resource_ids"] for ss in scales):
            raise CatalogError("Legacy ownership has not been registered. Explicit verified ownership reconciliation is required; prefix deletion is never authorized.", 409)
        if full:
            return evidence, sorted(allowlist, key=lambda item: item["resource_id"].lower())
        allowed = {item["resource_id"].lower() for item in allowlist}
        for item in allowlist:
            if any(dep.lower() not in allowed for dep in item["dependencies"]):
                raise CatalogError("Delete dependencies include external or shared resources.", 409)
            if "/providers/" not in item["resource_id"].lower():
                children = [key for key in observed if key.startswith(item["resource_id"].lower() + "/")]
                if any(child not in allowed for child in children):
                    raise CatalogError("Owned resource group contains foreign/shared children; group deletion is blocked.", 409)
                item["dependencies"] = sorted(set([*item["dependencies"], *children]))
        remaining = {item["resource_id"].lower(): {dep.lower() for dep in item["dependencies"]} for item in allowlist}
        while remaining:
            ready = {resource for resource, deps in remaining.items() if not deps}
            if not ready:
                raise CatalogError("Delete dependency graph contains a cycle; no partial delete is authorized.", 409)
            remaining = {resource: deps - ready for resource, deps in remaining.items() if resource not in ready}
        return evidence, sorted(allowlist, key=lambda item: item["resource_id"].lower())

    def prepare(self, root, request, document):
        from src.factory_catalog import select_factory, select_scale, validate_document
        validate_document(document)
        factory = select_factory(document, request["factory_id"])
        scales = ([select_scale(factory, request["scale_set_id"])] if request["scale_set_id"] else factory["scale_sets"])
        if not scales:
            raise CatalogError("The selected factory has no explicit physical targets.", 409)
        if request["action"] == "deploy" and request["project_id"]:
            matches = [project for project in factory["projects"] if project["id"] == request["project_id"]]
            if len(matches) != 1 or not any(p["scale_set_id"] == scales[0]["id"] for p in matches[0]["placements"]):
                raise CatalogError("Project must have an explicit placement in the selected scale set.", 409)
        if request["version_ref"] is None and factory.get("aifactory_version") is None:
            raise CatalogError("This factory's code version is unknown; explicitly select a published version before lifecycle preparation.", 409)
        selected = self.resolver(root, request["version_ref"] or factory.get("aifactory_version"))
        bindings = [self.binding(root, factory, scale) for scale in scales]
        scoped = (len(scales) > 1 or request["action"] == "delete-factory"
                  or request["action"] == "deploy" and (not request["project_id"] or any(
                      binding["route"].get("scoped_contract") == 1 or binding["route"]["kind"] == "gha"
                      or binding["route"]["shared_remote"] for binding in bindings))
                  or request["action"].startswith("delete") and any(
                      "/providers/" not in resource.lower() or "/".join(resource.lower().split("/")[6:8]) not in protocol.LEAF_TYPES
                      for scale in scales for resource in scale["owned_resource_ids"]))
        if scoped and request["action"] == "deploy" and any(
                binding["route"].get("scoped_contract") != 1 or not binding.get("_deployment_object_id") for binding in bindings):
            raise CatalogError("Configure a namespaced scoped route and deployment principal for common-only and scoped project execution.", 409)
        if scoped and request["action"] == "deploy" and any(not binding["route"].get("runner") for binding in bindings):
            raise CatalogError("Configure an explicit hosted or self-hosted Linux runner before scoped deployment.", 409)
        for scale, binding in zip(scales, bindings):
            if scale["suffix"] == "000":
                raise CatalogError("An exact nonzero scale-set suffix is required by the published runtime.", 409)
            if not scoped:
                protocol.operation_blockers(request, scale, binding)
            if request["action"].startswith("delete"):
                if not binding.get("_delete_authorized"):
                    raise CatalogError("Live enrollment has not authorized deletion of this exact physical target.", 409)
                if any("/".join(resource.split("/")[:5]).lower() not in {scope.lower() for scope in binding["locks"]["scopes"]}
                       for resource in scale["owned_resource_ids"]):
                    raise CatalogError("Complete registered ownership is not covered by the enrolled writable lock scopes; shared dependencies are never deletion targets.", 409)
        configuration = self._configuration(factory, scales, document, request, selected.get("template_variables"))
        if self.pty_factory is OwnedPty and not OwnedPty.available():
            raise CatalogError("Install a backend with an owned ConPTY terminal before running catalog lifecycle jobs.", 409)
        evidence, allowlist = self._checked_inventory(root, factory, scales, request["action"].startswith("delete"), full=scoped)
        from src.factory_catalog import utc
        sealed = None
        expires = self.clock() + 600
        if scoped:
            manifests = self.planner.prepare(root, request, document, selected, bindings, evidence, configuration,
                                            utc(self.clock()), utc(expires))
            manifests = self._order_manifests(manifests, deleting=request["action"].startswith("delete"))
            if any(len(protocol.canonical(item)) > 8 * 1024 * 1024 - 4096 for item in manifests):
                raise CatalogError("One frozen manifest exceeds protected-worker capacity; narrow the selected scope.", 409)
            encoded = protocol.canonical(manifests)
            if len(encoded) > 120 * 1024 * 1024:
                raise CatalogError("Frozen factory plan is too large; prepare individual scale-set operations.", 409)
            sealed = base64.b64encode(self.protector(encoded)).decode("ascii")
            allowlist = self._manifest_inventory(manifests)
        else:
            protocol.manifest(str(uuid4()), factory, scales[0], request, selected, configuration, bindings[0], evidence,
                              allowlist, utc(self.clock()), utc(self.clock() + 600))
        if self.clock() >= expires:
            raise CatalogError("Preparation exceeded its freshness window; narrow the scope and prepare again.", 409)
        return {"version": selected, "binding": bindings[0], "bindings": bindings, "scoped": scoped, "sealed_manifests": sealed,
                "expires": expires,
                "inventory": allowlist, "evidence": evidence,
                "evidence_revision": digest({key: value for key, value in evidence.items() if key != "observed_at"}),
                "blockers": [], "effects": [
                    "Execute only the reviewed physical targets using a protected per-run configuration and an isolated published runtime.",
                    "Acquire cross-machine Azure target leases, including shared common targets, before any resource mutation.",
                    "Never delete subscriptions, repositories, external hubs or shared resources.",
                    "Delete removes registered catalog configuration only after verified runtime success; failures retain evidence and configuration.",
                ], "warnings": ["This action may change billable Azure resources. No automatic retries.",
                                "Closing the terminal can interrupt a run after partial changes; reconcile before retrying.",
                                *(["Deleting a managed disk permanently deletes its data."] if any(
                                    str(item.get("type", "")).lower() == "microsoft.compute/disks"
                                    and any(item["resource_id"].lower() == entry["resource_id"].lower() for entry in allowlist)
                                    for item in evidence["records"]) else [])]}

    def confirm(self, root, payload, owner, db):
        from src.factory_catalog import select_factory, select_scale, source_revision, target_revision, utc
        request, prepared = payload["request"], payload["runtime"]
        factory = select_factory(payload["document"], request["factory_id"])
        selected = self.resolver(root, request["version_ref"] or factory.get("aifactory_version"))
        if selected != prepared["version"]:
            raise CatalogError("Selected published code changed since preparation; review the new version.", 409)
        version_acknowledgement = {"aifactory_version": request["version_ref"], **{
            key: selected[key] for key in ("requested_version", "branch", "resolved_ref")}}
        if payload["preview"].get("source_version") != version_acknowledgement:
            raise CatalogError("Reviewed version acknowledgement changed or is incomplete; prepare again.", 409)
        scales = [select_scale(factory, request["scale_set_id"])] if request["scale_set_id"] else factory["scale_sets"]
        bindings = [self.binding(root, factory, scale) for scale in scales]
        if bindings != prepared.get("bindings", [prepared["binding"]]):
            raise CatalogError("Consumer repository or lock enrollment changed; prepare again.", 409)
        if not prepared.get("scoped"):
            protocol.operation_blockers(request, scales[0], bindings[0])
        evidence, allowlist = self._checked_inventory(root, factory, scales, request["action"].startswith("delete"),
                                                    full=prepared.get("scoped", False))
        if digest({key: value for key, value in evidence.items() if key != "observed_at"}) != prepared["evidence_revision"]:
            raise CatalogError("Azure identity or complete inventory changed since preparation; prepare again.", 409)
        if source_revision(root) != payload["preview"]["source_revision"]:
            raise CatalogError("Reviewed catalog source changed during confirmation; prepare again.", 409)
        manifests = None
        if prepared.get("scoped"):
            try:
                manifests = json.loads(self.unprotector(base64.b64decode(prepared["sealed_manifests"])).decode("utf-8"))
            except (ValueError, TypeError):
                raise CatalogError("Prepared scoped inputs cannot be decrypted by this OS user; prepare again.", 409) from None
            self.planner.refresh(root, selected, manifests, payload["document"])
            if self.clock() >= prepared["expires"]:
                raise CatalogError("The frozen plan expired during verification; prepare again.", 409)
            if source_revision(root) != payload["preview"]["source_revision"]:
                raise CatalogError("Catalog inputs changed while verifying the frozen plan; prepare again.", 409)
        for row in db.execute("SELECT payload FROM jobs"):
            existing = json.loads(row["payload"])
            if (existing["status"] in ACTIVE and _pid_alive(existing["_host_pid"])
                    and existing["factory_id"] == factory["id"]):
                raise CatalogError("A lifecycle job already owns this factory; wait or reconcile it.", 409)
        identifier, now = str(uuid4()), utc(self.clock())
        run = _run_path(root, identifier)
        run.mkdir(parents=True)
        config = self._configuration(factory, scales, payload["document"], request, selected.get("template_variables"))
        manifest = (manifests[0] if manifests else protocol.manifest(
            payload["preview"]["confirmation_id"], factory, scales[0], request, selected, config, bindings[0], evidence,
            allowlist, utc(self.clock()), utc(self.clock() + 600)))
        cohort = bool(manifests) and request["action"] == "delete-factory"
        evidence_manifest = ({"job_id": identifier, "manifests": [self._redacted_manifest(item) for item in manifests]}
                             if manifests else self._redacted_manifest(manifest))
        atomic_write(run / "manifest.json", encode(evidence_manifest))
        job = {"id": identifier, "action": request["action"], "status": "queued",
               "message": "Reviewed lifecycle job queued; no completion has been claimed.", "factory_id": factory["id"],
               "scale_set_id": request["scale_set_id"], "created_at": now, "updated_at": now,
               "source_version": {"aifactory_version": request["version_ref"], **{
                   key: selected[key] for key in ("requested_version", "branch", "resolved_ref")}},
               "exit_code": None, "terminal_available": True, "_host_pid": os.getpid(),
               "_revision": payload["preview"]["source_revision"], "_run": str(run), "_owner": owner,
               "_target_revision": target_revision(root, factory["id"]),
               "_manifest_hash": protocol.fingerprint(sorted(item["manifest_hash"] for item in manifests)) if cohort else manifest["manifest_hash"],
               "_evidence_hash": digest(evidence_manifest)}
        session = self.terminals.create(identifier)
        session.update(root=root, owner=owner, job=job)
        try:
            atomic_write(run / "configuration.dpapi", self.protector(protocol.canonical(manifests if cohort else manifest)))
        except (OSError, ValueError):
            session["complete"] = True
            raise
        try:
            consumed_payload = copy.deepcopy(payload)
            consumed_payload["runtime"]["sealed_manifests"] = None
            consumed = db.execute("UPDATE confirmations SET consumed=1,payload=? WHERE id=? AND owner=? AND consumed=0 AND expires>?",
                                  (json.dumps(consumed_payload), payload["preview"]["confirmation_id"], owner, self.clock()))
            if consumed.rowcount != 1:
                raise CatalogError("Confirmation expired before dispatch; prepare again.", 409)
            db.execute("INSERT INTO jobs(id,owner,payload) VALUES (?,?,?)", (identifier, owner, json.dumps(job)))
            db.commit()
        except (sqlite3.Error, CatalogError):
            session["complete"] = True
            (run / "configuration.dpapi").unlink(missing_ok=True)
            raise
        with self.lock:
            self.running[identifier] = (root, owner, session)
        try:
            self.dispatch(lambda: self._run_scoped(root, job, payload, manifests, selected) if manifests
                          else self._run(root, job, payload, manifest, selected))
        except (OSError, RuntimeError):
            job.update(status="failed", message="Worker could not start; no retry was performed.", terminal_available=False)
            db.execute("UPDATE jobs SET payload=? WHERE id=?", (json.dumps(job), identifier))
            (run / "configuration.dpapi").unlink(missing_ok=True)
            session["complete"] = True
            with self.lock:
                self.running.pop(identifier, None)
        return _public(job)

    @staticmethod
    def _redacted_manifest(manifest):
        result = {key: copy.deepcopy(value) for key, value in manifest.items() if key not in ("config", "deployment")}
        if "deployment" in manifest:
            plan = manifest["deployment"]
            result["deployment"] = {key: copy.deepcopy(value) for key, value in plan.items() if key != "steps"}
            result["deployment"]["steps"] = [{key: copy.deepcopy(value) for key, value in step.items() if key != "parameters"}
                                               for step in plan["steps"]]
        return result

    @staticmethod
    def _manifest_inventory(manifests):
        inventory = {}
        for manifest in manifests:
            if "deletion" in manifest:
                for item in [*manifest["deletion"]["resource_groups"], *manifest["deletion"]["resources"]]:
                    if item["delete"]:
                        inventory[item["id"].lower()] = {"resource_id": item["id"], "dependencies": item.get("depends_on", [])}
            else:
                for item in manifest["deployment"]["changes"]:
                    inventory[item["resource_id"].lower()] = {"resource_id": item["resource_id"], "dependencies": []}
        return sorted(inventory.values(), key=lambda item: item["resource_id"].lower())

    @staticmethod
    def _order_manifests(manifests, deleting):
        if not deleting:
            return manifests
        owners = {}
        for manifest in manifests:
            for scope in manifest["locks"]["scopes"]:
                if scope.lower() in owners:
                    raise CatalogError("Factory deletion has overlapping physical writers; resolve ownership before proceeding.", 409)
                owners[scope.lower()] = manifest["run_id"]
        remaining = {manifest["run_id"]: manifest for manifest in manifests}
        ordered = []
        while remaining:
            referenced = set()
            for manifest in remaining.values():
                dependencies = list(manifest["locks"]["common_dependencies"])
                dependencies.extend(dep for item in manifest.get("deletion", {}).get("resources", []) for dep in item.get("depends_on", []))
                for dependency in dependencies:
                    owner = owners.get("/".join(dependency.split("/")[:5]).lower())
                    if owner in remaining and owner != manifest["run_id"]:
                        referenced.add(owner)
            ready = sorted(set(remaining) - referenced)
            if not ready:
                raise CatalogError("Factory deletion has cyclic inter-scale dependencies; no partial delete is authorized.", 409)
            for run_id in ready:
                ordered.append(remaining.pop(run_id))
        return ordered

    def _run_scoped(self, root, job, payload, manifests, selected):
        if job["action"] == "delete-factory":
            self._run(root, job, payload, manifests, selected)
            return
        from src.factory_catalog import commit_document, load_document, source_revision, target_revision
        session = self.terminals.get(job["id"])
        run = _run_path(root, job["id"])
        completed = []
        try:
            for manifest in manifests:
                job["_manifest_hash"] = manifest["manifest_hash"]
                atomic_write(run / "configuration.dpapi", self.protector(protocol.canonical(manifest)))
                result = self._run(root, job, payload, manifest, selected, defer_commit=True)
                if result is None:
                    return
                completed.append((manifest, result))
            with catalog_lock(root, timeout=self.timeout):
                if target_revision(root, job["factory_id"]) != job["_target_revision"]:
                    raise CatalogError("Runtime finished but the selected catalog target changed; reconcile before updating ownership.", 409)
                revision = source_revision(root)
                document = load_document(root)
                for manifest, result in completed:
                    self._apply_result(document, job, manifest, result)
                commit_document(root, document, expected_revision=revision)
            job.update(status="succeeded", message="All reviewed scoped runtimes succeeded; exact registered ownership updated.")
        except (TicketError, OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
            job.update(status="interrupted" if session.get("stopped") else "failed",
                       message=str(exc) if isinstance(exc, TicketError) else "Scoped runtime failed; partial receipts and original catalog configuration are retained.")
        finally:
            session["accepting"] = False
            session["complete"] = True
            try:
                (run / "configuration.dpapi").unlink(missing_ok=True)
            except OSError:
                job.update(status="failed", message="Protected runtime artifact cleanup failed; retain and reconcile the evidence.")
            try:
                self._save_job(root, job)
            finally:
                with self.lock:
                    self.running.pop(job["id"], None)

    @staticmethod
    def _configuration(factory, scales, document, request, template_variables=None):
        config = document["configurations"][factory["id"]]
        outputs = {}
        for scale in scales:
            state = {**wizard.new_configuration_defaults(), **config["factory"],
                     **config["scale_sets"].get(scale["id"], {})}
            if request["project_id"]:
                state.update(config["projects"][request["project_id"]])
            if any(str(value).lower() in ("true", "1", "yes") for key, value in state.items()
                   if key.lower().startswith(("delete", "clean")) or key in ("enableDeleteForDisabledResources", "debugEnableCleaning")):
                raise CatalogError("Destructive project flags are not allowed in deployment configuration.", 409)
            state.update(admin_aifactoryPrefixRG=factory["prefix"], admin_location=factory["region"],
                         admin_locationSuffix=wizard.azure_region_suffixes().get(factory["region"], ""),
                         admin_aifactorySuffixRG="-" + scale["suffix"], tenantId=scale["tenant_id"],
                         orchestrator=scale["orchestrator"])
            # Every generated document is bound to exactly one physical subscription, not root env fallbacks.
            state.update(dev_sub_id=scale["subscription_id"], test_sub_id=scale["subscription_id"], prod_sub_id=scale["subscription_id"])
            network = ipaddress_for_state(scale["network"])
            state.update(network)
            if request["project_id"]:
                project = next(p for p in factory["projects"] if p["id"] == request["project_id"])
                state["project_number_000"] = project["number"]
                try:
                    tags = json.loads(state.get("tagsProject") or (template_variables or {}).get("tagsProject") or "{}")
                except (TypeError, ValueError):
                    raise CatalogError("Project tags must be a JSON object before deployment.", 409) from None
                if not isinstance(tags, dict):
                    raise CatalogError("Project tags must be a JSON object before deployment.", 409)
                tags.update({"aifactory.factory_id": factory["id"], "aifactory.scaleset_id": scale["id"],
                             "aifactory.project_id": project["number"], "aifactory.logical_project_id": project["id"]})
                state["tagsProject"] = json.dumps(tags)
            state = wizard.hub_configuration(state)
            wizard.require_hub_configuration(state)
            # Legacy rendering validates three global environments together. A catalog run
            # instead validates one explicit network/target and cannot fabricate two other environments.
            variables = copy.deepcopy(template_variables or {})
            variables.update({dotpath.removeprefix("variables."): state[key]
                              for key, dotpath in wizard.YAML_MAP.items()
                              if dotpath.startswith("variables.") and key in state and not key.startswith("_")})
            if request["project_id"]:
                variables["tagsProject"] = state["tagsProject"]
            variables.update(wizard.NETWORK_MODE_FLAGS[state.get("network_mode", "public")])
            for key in wizard.HUB_FLAG_KEYS:
                variables[key] = wizard._bool_str(state[key])
            outputs[scale["id"]] = {"dev": variables, "stage_prod": copy.deepcopy(variables)}
        return {"schema_version": 1, "targets": outputs}

    def _materialize(self, root, selected, run):
        repository = Path(selected["repository"])
        commit = selected["resolved_ref"]
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise CatalogError("Reviewed code must be an immutable commit.", 409)
        git = self.cli.tools().get("git")
        if not git:
            raise CatalogError("Install Git to materialize the isolated published runtime.", 409)
        source = run / "source"
        if not source.exists():
            release_version.materialize_source(repository, commit, source, git=git)
        environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        environment.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="Never")
        command = [git, "-c", "core.hooksPath=" + str(source / ".git" / "aifactory-disabled-hooks"),
                   "-c", "core.fsmonitor=false", "-C", str(source)]
        head = subprocess.run([*command, "rev-parse", "HEAD"], capture_output=True, text=True,
                              timeout=30, check=True, env=environment).stdout.strip()
        dirty = subprocess.run([*command, "status", "--porcelain", "--untracked-files=all"],
                               capture_output=True, text=True, timeout=30, check=True, env=environment).stdout
        if head != commit or dirty:
            raise CatalogError("Isolated published source must remain clean and pinned to the reviewed commit.", 409)
        helper = source / Path(HELPER)
        text = helper.read_text(encoding="utf-8")
        if CONTRACT not in text or hashlib.sha256(text.encode()).hexdigest() != selected["helper_sha256"]:
            raise CatalogError("Materialized runtime does not match the reviewed lifecycle contract.", 409)
        return helper, run / "execution"

    @staticmethod
    def _dispatch(callback):
        threading.Thread(target=callback, name="factory-catalog-lifecycle", daemon=True).start()

    def _save_job(self, root, job):
        from src.factory_catalog import utc
        job["updated_at"] = utc(self.clock())
        with database(root) as db:
            db.execute("UPDATE jobs SET payload=? WHERE id=?", (json.dumps(job), job["id"]))

    def _run(self, root, job, payload, manifest, selected, defer_commit=False):
        from src.factory_catalog import commit_document, load_document, source_revision, target_revision
        session = self.terminals.get(job["id"])
        run = _run_path(root, job["id"])
        pty = None
        watchdog = None
        result = None
        cohort = isinstance(manifest, list)
        try:
            if session.get("stopped"):
                raise CatalogError("Lifecycle job was stopped before execution; no retry was started.", 409)
            helper, execution = self.materialize(root, selected, run)
            if defer_commit:
                execution = run / ("execution-" + manifest["run_id"])
            if session.get("stopped"):
                raise CatalogError("Lifecycle job was stopped before execution; no retry was started.", 409)
            if target_revision(root, job["factory_id"]) != job["_target_revision"]:
                raise CatalogError("Catalog changed before runtime start; execution refused.", 409)
            if digest(read_json(run / "manifest.json")) != job["_evidence_hash"]:
                raise CatalogError("Immutable runtime manifest changed.", 409)
            job.update(status="running", message="Scoped lifecycle runtime running; completion is not yet verified.")
            self._save_job(root, job)
            env = simple_mode.launch_environment(release_version.environment(selected), self.cli.tools())
            worker_command = ([sys.executable, "--catalog-worker", "--parent-pid", str(os.getpid())] if getattr(sys, "frozen", False)
                              else [sys.executable, "-B", str(Path(__file__).with_name("catalog_worker.py"))])
            argv = [*worker_command,
                    "--helper", str(helper), "--helper-sha256", selected["helper_sha256"], "--expected-hash", job["_manifest_hash"],
                    "--protected-manifest", str(run / "configuration.dpapi"),
                    "--source-root", str(run / "source"), "--execution-root", str(execution),
                    "--receipt", str(execution / "receipt.json")]
            if cohort:
                argv.append("--cohort")
            with self.lock:
                if session.get("stopped"):
                    raise CatalogError("Lifecycle job was stopped before execution; no retry was started.", 409)
                pty = self.pty_factory(argv, str(run), env)
                session.update(pty=pty, accepting=True)
            def timed_out(process=pty):
                session["timed_out"] = True
                session["accepting"] = False
                process.close()
            watchdog = threading.Timer(self.timeout, timed_out)
            watchdog.daemon = True
            watchdog.start()
            deadline = self.clock() + self.timeout
            while True:
                if self.clock() >= deadline:
                    raise CatalogError("Lifecycle runtime exceeded its time limit; reconcile partial changes.", 409)
                text = pty.read()
                if not text:
                    break
                session["buffer"].append(text)
            code = pty.wait()
            watchdog.cancel()
            job["exit_code"] = code
            if code != 0 or session.get("timed_out") or session.get("stopped"):
                raise CatalogError("Lifecycle runtime failed or was interrupted; configuration and evidence are retained.", 409)
            session["accepting"] = False
            pty.close()
            pty = None
            result = read_json(execution / "receipt.json")
            if cohort:
                self._cohort_children(manifest, result, job, selected, execution)
            elif (result.get("schema") != 1 or result.get("run_id") != manifest["run_id"]
                    or result.get("status") != "succeeded" or result.get("manifest_hash") != job["_manifest_hash"]
                    or result.get("target") != manifest["target"] or result.get("source_commit") != selected["resolved_ref"]):
                raise CatalogError("Runtime did not produce matching verified success evidence; reconcile before retrying.", 409)
            if job["action"] == "deploy" and "deployment" in manifest:
                worker = result.get("worker_receipt")
                if (not isinstance(worker, dict) or worker.get("schema") != 1 or worker.get("status") != "succeeded"
                        or worker.get("manifest_hash") != manifest["manifest_hash"] or worker.get("run_id") != manifest["run_id"]
                        or worker.get("source_commit") != selected["resolved_ref"] or worker.get("target") != manifest["target"]):
                    raise CatalogError("The scoped worker receipt does not match the exact reviewed run.", 409)
                deployments, ownership = worker.get("deployments"), worker.get("ownership")
                if (not isinstance(deployments, list)
                        or [step.get("step_id") for step in deployments] != [step["id"] for step in manifest["deployment"]["steps"]]
                        or any(step.get("status") != "succeeded" for step in deployments)
                        or not isinstance(ownership, list)
                        or not re.fullmatch(r"[a-f0-9]{64}", str(worker.get("inventory_closure_hash", "")))):
                    raise CatalogError("The scoped worker receipt lacks complete ordered deployment and ownership evidence.", 409)
                groups = worker.get("resource_groups")
                expected_groups = {scope.lower() for scope in manifest["locks"]["scopes"]}
                if (not isinstance(groups, list) or len(groups) != len(expected_groups)
                        or any(not isinstance(item, dict) or not isinstance(item.get("resource_id"), str)
                               or item["resource_id"].lower() not in expected_groups
                               or not re.fullmatch(r"[a-f0-9]{64}", str(item.get("body_hash", "")))
                               or not isinstance(item.get("owner"), dict) or any(
                                   item["owner"].get(key) != manifest["target"][key] for key in ("factory_id", "scaleset_id"))
                               for item in groups)
                        or {item["resource_id"].lower() for item in groups} != expected_groups):
                    raise CatalogError("The scoped worker receipt lacks exact verified resource-group ownership.", 409)
                ownership = ownership + groups
                if not set(manifest["target"]["project_ids"]) <= {item["owner"].get("project_id") for item in ownership}:
                    raise CatalogError("The scoped worker receipt is missing the selected project's ownership.", 409)
                result["ownership"] = [{"resource_id": item["resource_id"],
                                        "factory_id": item["owner"]["factory_id"], "scale_set_id": item["owner"]["scaleset_id"]}
                                       for item in ownership]
            elif job["action"] == "deploy":
                from src.factory_catalog import select_factory, select_scale
                factory = select_factory(payload["document"], job["factory_id"])
                scale = select_scale(factory, job["scale_set_id"])
                observed = self.inventory(root, factory, [scale])
                if (observed.get("complete") is not True or not 0 <= self.clock() - observed.get("observed_at", 0) <= 60
                        or observed.get("accounts") != payload["runtime"]["evidence"].get("accounts")):
                    raise CatalogError("Runtime finished but fresh ownership/identity could not be verified.", 409)
                groups = {value.lower() for value in manifest["locks"]["scopes"]}
                ownership = []
                for item in observed["records"]:
                    if item.get("factory_id") == factory["id"] and item.get("scale_set_id") == scale["id"]:
                        if (item.get("shared") or "/".join(item["resource_id"].split("/")[:5]).lower() not in groups):
                            raise CatalogError("Deployment produced ownership outside the approved physical target.", 409)
                        ownership.append({"resource_id": item["resource_id"], "factory_id": factory["id"], "scale_set_id": scale["id"]})
                result["ownership"] = ownership
                atomic_write(run / "verified-ownership.json", encode({"run_id": job["id"], "ownership": ownership}))
            if not cohort:
                ordinary(run / "configuration.dpapi").unlink(missing_ok=True)
            if defer_commit:
                job.update(status="running", message="One exact scoped runtime verified; waiting for the complete operation.")
            else:
                with catalog_lock(root, timeout=self.timeout):
                    if target_revision(root, job["factory_id"]) != job["_target_revision"]:
                        raise CatalogError("Runtime completed but catalog changed. Reconcile ownership before saving completion.", 409)
                    commit_revision = source_revision(root)
                    document = load_document(root)
                    if cohort:
                        self._apply_cohort_result(document, job, manifest, result)
                    else:
                        self._apply_result(document, job, manifest, result)
                    commit_document(root, document, expected_revision=commit_revision)
                job.update(status="succeeded", message="Runtime success verified and registered catalog ownership updated.")
        except (TicketError, OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError) as exc:
            job.update(status="interrupted" if session.get("stopped") else "failed",
                       message=str(exc) if isinstance(exc, TicketError) else
                       "Lifecycle runtime failed; configuration and non-secret evidence are retained. Inspect the local terminal.")
        finally:
            if watchdog is not None:
                watchdog.cancel()
            session["accepting"] = False
            if pty is not None:
                try:
                    pty.close()
                except (OSError, RuntimeError, subprocess.SubprocessError):
                    job.update(status="failed", message="Runtime process-tree cleanup failed; reconcile before retrying.")
            session["complete"] = not defer_commit
            try:
                if not cohort or job["status"] == "succeeded":
                    (run / "configuration.dpapi").unlink(missing_ok=True)
            except OSError:
                job.update(status="failed", message="Protected runtime artifact cleanup failed; remove it after reviewing retained evidence.")
            job["terminal_available"] = True
            try:
                self._save_job(root, job)
            finally:
                if not defer_commit:
                    with self.lock:
                        self.running.pop(job["id"], None)
        return result if job["status"] in ("running", "succeeded") else None

    @staticmethod
    def _cohort_children(manifests, result, job, selected, execution):
        expected_hash = protocol.fingerprint(sorted(item["manifest_hash"] for item in manifests))
        if (result.get("schema") != 1 or result.get("operation") != "delete-factory"
                or result.get("status") != "succeeded" or result.get("cohort_hash") != expected_hash
                or expected_hash != job["_manifest_hash"] or result.get("factory_id") != job["factory_id"]
                or result.get("source_commit") != selected["resolved_ref"]
                or result.get("source_ref") != manifests[0]["source"]["ref"]
                or result.get("lock_retained") is not False or result.get("locks_retained") != []):
            raise CatalogError("Whole-factory runtime lacks matching complete cohort success evidence; retain and reconcile the entire catalog.", 409)
        children = result.get("children")
        if not isinstance(children, list) or len(children) != len(manifests):
            raise CatalogError("Whole-factory runtime has missing child receipts.", 409)
        by_id = {child["run_id"]: child for child in children}
        if len(by_id) != len(children) or set(by_id) != {item["run_id"] for item in manifests}:
            raise CatalogError("Whole-factory runtime has duplicate or unapproved child receipts.", 409)
        for manifest in manifests:
            child = by_id[manifest["run_id"]]
            if (child.get("schema") != 1 or child.get("operation") != "delete"
                    or child.get("status") != "succeeded" or child.get("manifest_hash") != manifest["manifest_hash"]
                    or child.get("manifest_revision") != manifest["manifest_revision"]
                    or child.get("target") != manifest["target"] or child.get("source_commit") != selected["resolved_ref"]
                    or child.get("source_ref") != manifest["source"]["ref"] or child.get("cohort_hash") != expected_hash
                    or child.get("lock_retained") is not False or child.get("locks_retained") != []
                    or read_json(execution / (manifest["run_id"] + ".receipt.json")) != child):
                raise CatalogError("Whole-factory child receipt does not match the reviewed immutable scope.", 409)
        return by_id

    @staticmethod
    def _apply_cohort_result(document, job, manifests, result):
        from src.factory_catalog import select_factory
        children = {child["run_id"]: child for child in result["children"]}
        for manifest in manifests:
            CatalogRuntime._apply_result(document, {**job, "action": "delete-scale-set"},
                                         manifest, children[manifest["run_id"]])
        factory = select_factory(document, job["factory_id"])
        if factory["scale_sets"]:
            raise CatalogError("Whole-factory receipts do not cover every registered scale set.", 409)
        document["factories"].remove(factory)
        document["configurations"].pop(factory["id"])

    @staticmethod
    def _apply_result(document, job, manifest, result):
        from src.factory_catalog import select_factory
        factory = select_factory(document, job["factory_id"])
        selected = {manifest["target"]["scaleset_id"]}
        if job["action"].startswith("delete"):
            expected = {item["id"].lower() for item in [*manifest["deletion"]["resources"], *manifest["deletion"]["resource_groups"]] if item["delete"]}
            if {item.lower() for item in result.get("deleted_resources", [])} != expected:
                raise CatalogError("Delete evidence is incomplete or contains unapproved resource IDs.", 409)
            if job["action"] == "delete-factory":
                document["factories"].remove(factory)
                del document["configurations"][factory["id"]]
            else:
                factory["scale_sets"] = [ss for ss in factory["scale_sets"] if ss["id"] not in selected]
                for project in factory["projects"]:
                    project["placements"] = [p for p in project["placements"] if p["scale_set_id"] not in selected]
                for scale_id in selected:
                    document["configurations"][factory["id"]]["scale_sets"].pop(scale_id, None)
            for resource in list(document.get("ownership_evidence", {})):
                if resource.lower() in expected:
                    document["ownership_evidence"].pop(resource)
        else:
            ownership = result.get("ownership")
            if not isinstance(ownership, list) or not ownership:
                raise CatalogError("Deployment succeeded without concrete resource ownership evidence.", 409)
            for scale in factory["scale_sets"]:
                if scale["id"] not in selected:
                    continue
                ids = []
                for item in ownership:
                    match = RESOURCE_ID.fullmatch(str(item.get("resource_id", "")))
                    if (not match or item.get("scale_set_id") not in selected or item.get("factory_id") != factory["id"]
                            or match.group(1).lower() != scale["subscription_id"].lower()
                            or "/".join(item["resource_id"].split("/")[:5]).lower() not in {
                                scope.lower() for scope in manifest["locks"]["scopes"]}):
                        raise CatalogError("Deployment evidence escaped approved physical ownership.", 409)
                    if item["scale_set_id"] == scale["id"]:
                        ids.append(item["resource_id"])
                if not ids:
                    raise CatalogError("Deployment evidence is missing a selected scale set.", 409)
                merged = {resource.lower(): resource for resource in [*scale["owned_resource_ids"], *ids]}
                scale["owned_resource_ids"] = sorted(merged.values(), key=str.lower)
                scale["status"] = "configured"
            factory["status"] = "configured"
            if "worker_receipt" in result:
                worker = result["worker_receipt"]
                ledger = document.setdefault("ownership_evidence", {})
                for item in worker["ownership"] + worker["resource_groups"]:
                    ledger[item["resource_id"].lower()] = {
                        "owner": item["owner"], "ownership_source": "deployment-receipt",
                        "ownership_evidence": {"run_id": worker["run_id"], "receipt_hash": protocol.fingerprint(worker)}}
            for project in factory["projects"]:
                if project["number"] in manifest["target"]["project_ids"] and any(
                        placement["scale_set_id"] in selected for placement in project["placements"]):
                    project["status"] = "configured"

    def jobs(self, root, owner):
        with database(root) as db:
            values = []
            for row in db.execute("SELECT payload FROM jobs WHERE owner=?", (owner,)):
                job = json.loads(row["payload"])
                if job["status"] in ACTIVE and not _pid_alive(job["_host_pid"]):
                    job.update(status="interrupted", message="API host exited before completion. Reconcile partial changes; no retry was started.",
                               terminal_available=False)
                    ordinary(_run_path(root, job["id"]) / "configuration.dpapi").unlink(missing_ok=True)
                    db.execute("UPDATE jobs SET payload=? WHERE id=?", (json.dumps(job), job["id"]))
                job["terminal_available"] = self.terminals.get(job["id"]) is not None
                values.append(_public(job))
            return sorted(values, key=lambda value: value["created_at"], reverse=True)

    def job(self, root, job_id, owner):
        for job in self.jobs(root, owner):
            if job["id"] == job_id:
                return job
        raise CatalogError("Lifecycle job not found for this authenticated caller.", 404)

    def _session(self, root, job_id, owner, accepting=False):
        session = self.terminals.get(job_id)
        if not session:
            self.job(root, job_id, owner)
            raise CatalogError("Terminal history is no longer available; durable job status is retained.", 410)
        if session["root"] != root or session["owner"] != owner:
            raise CatalogError("Lifecycle job not found for this authenticated caller.", 404)
        if accepting and not session["accepting"]:
            raise CatalogError("This terminal is no longer accepting input.", 409)
        return session

    def terminal(self, root, job_id, owner, cursor=0):
        session = self._session(root, job_id, owner)
        return {"job_id": job_id, **session["buffer"].read(cursor), "status": session["job"]["status"]}

    def input(self, root, job_id, owner, data):
        if not isinstance(data, str) or not 1 <= len(data) <= 8192:
            raise CatalogError("Terminal input must contain 1 through 8192 characters.")
        self._session(root, job_id, owner, accepting=True)["pty"].write(data)
        return {"accepted": True}

    def resize(self, root, job_id, owner, columns, rows):
        if type(columns) is not int or type(rows) is not int or not 20 <= columns <= 500 or not 5 <= rows <= 200:
            raise CatalogError("Unsupported terminal dimensions.")
        self._session(root, job_id, owner, accepting=True)["pty"].resize(columns, rows)
        return {"accepted": True}

    def stop(self, root, job_id, owner):
        session = self._session(root, job_id, owner)
        with self.lock:
            session["stopped"] = True
            session["accepting"] = False
            if session["pty"]:
                session["pty"].close()
        return _public(session["job"])

    def shutdown(self):
        with self.lock:
            items = list(self.running.items())
        for job_id, (root, owner, session) in items:
            self.stop(root, job_id, owner)


def ipaddress_for_state(network):
    import ipaddress
    vnet = ipaddress.IPv4Network(network["vnet_cidr"])
    base = int(vnet.network_address)
    return {"common_vnet_cidr": str(vnet), "dev_cidr_range": "0", "test_cidr_range": "0", "prod_cidr_range": "0",
            **{key: ((network.get("common_subnets") or {}).get(name)
                     or str(ipaddress.IPv4Network((base + index * 64, 26))))
               for index, (name, key) in enumerate(zip(("common", "scoring", "powerbi", "bastion"),
                ("common_subnet_cidr", "common_subnet_scoring_cidr", "common_pbi_subnet_cidr", "common_bastion_subnet_cidr")))}}
