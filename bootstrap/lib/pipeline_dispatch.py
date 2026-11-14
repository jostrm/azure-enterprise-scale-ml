"""Provider-only dispatch/wait. No Factory API, local deployment engine or SDK.

The transport writes once, never retries an uncertain dispatch, and follows only
the correlated run/attempt. Provider success is insufficient without the shared
lifecycle runtime's authoritative receipt validation.
"""
import argparse
import base64
import copy
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4
import zipfile

from pipeline_credentials import CredentialError, environment_file_path, load_dispatch_env


GHA_WORKFLOW = ".github/workflows/pipelines-only-gha.yml"
ADO_WORKFLOW = "pipelines-only-ado.yml"
MAX_BYTES = 4 * 1024 * 1024


class DispatchError(Exception):
    pass


def require(condition, code):
    if not condition:
        raise DispatchError(code)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def operation_selection(*, parent_operation_id=None, parent_plan_hash=None,
                        recovery_operation_id=None, recovery_plan_hash=None):
    """Closed selectors for separate native continuation or recovery preparation."""
    from pipeline_lifecycle import identifier
    require(bool(parent_operation_id) == bool(parent_plan_hash), "continuation-parent-pair-required")
    require(bool(recovery_operation_id) == bool(recovery_plan_hash), "recovery-operation-pair-required")
    require(not (parent_operation_id and recovery_operation_id), "continuation-and-recovery-mutually-exclusive")
    selected = {}
    for prefix, operation_id, plan_hash in (
        ("parent", parent_operation_id, parent_plan_hash),
        ("recovery", recovery_operation_id, recovery_plan_hash),
    ):
        if operation_id:
            identifier(operation_id)
            require(isinstance(plan_hash, str) and re.fullmatch(r"[a-f0-9]{64}", plan_hash),
                    "reviewed-plan-hash-required")
            selected[prefix + "_operation_id"] = operation_id
            selected[prefix + "_plan_hash"] = plan_hash
    return selected


def relative_path(value):
    require(isinstance(value, str) and value and "\\" not in value and ":" not in value
            and not value.startswith("/") and not any(part in ("", ".", "..") for part in value.split("/"))
            and not any(ord(char) < 32 for char in value), "repository-relative-path-required")
    require(not environment_file_path(value), "environment-file-transport-forbidden")
    return value


def local_file(root, value):
    path = (root / relative_path(value)).resolve()
    require(path.is_relative_to(root.resolve()) and path.is_file(), "repository-file-required")
    return path


def validate_binding(canonical, binding):
    require(isinstance(binding, dict), "provider-binding-required")
    common = {"schema", "provider", "repository", "consumer_commit"}
    request = canonical.get("request", canonical)
    provider = request.get("provider")
    require(provider in ("gha", "ado") and binding.get("provider") == provider, "provider-route-mismatch")
    allowed = common | {"consumer_ref"} | ({"pipeline_id"} if provider == "ado" else set())
    require(common <= set(binding) <= allowed
            and type(binding.get("schema")) is int and binding["schema"] == 1,
            "provider-binding-schema-invalid")
    require(re.fullmatch(r"[a-f0-9]{40}", str(binding.get("consumer_commit", ""))) is not None,
            "consumer-commit-required")
    repository = binding["repository"]
    registered = canonical.get("binding")
    if registered is not None:
        require(registered.get("repository") == repository
                and registered.get("orchestrator", provider) == provider,
                "provider-route-mismatch")
    if "consumer_ref" in binding:
        consumer_ref(canonical, binding)
    require(isinstance(repository, str), "repository-invalid")
    if provider == "gha":
        require(re.fullmatch(r"https://github\.com/[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]+",
                             repository) is not None and repository.rsplit("/", 1)[1] not in (".", ".."),
                "repository-invalid")
        base = "https://api.github.com/repos/" + repository.removeprefix("https://github.com/")
    else:
        require(re.fullmatch(r"https://dev\.azure\.com/[A-Za-z0-9_-]+/[A-Za-z0-9_.% -]+/_git/[A-Za-z0-9_.% -]+",
                             repository) is not None, "repository-invalid")
        parts = unquote(urlsplit(repository).path).split("/")
        require(len(parts) == 5 and all(part not in (".", "..") for part in parts), "repository-invalid")
        if "pipeline_id" in binding:
            require(type(binding["pipeline_id"]) is int and binding["pipeline_id"] > 0, "pipeline-id-invalid")
        base = "https://dev.azure.com/" + quote(parts[1], safe="") + "/" + quote(parts[2], safe="") + "/_apis"
    return base


def consumer_ref(canonical, binding):
    """The accelerator source ref is never a selector for the consumer pipeline."""
    registered = canonical.get("binding", {})
    native_ref = registered.get("ref")
    explicit_ref = binding.get("consumer_ref", registered.get("consumer_ref"))
    require(not native_ref or not explicit_ref or native_ref == explicit_ref,
            "consumer-ref-native-binding-mismatch")
    selected = native_ref or explicit_ref
    require(isinstance(selected, str) and re.fullmatch(r"refs/(heads|tags)/[A-Za-z0-9_./-]+", selected)
            and ".." not in selected and "//" not in selected and not selected.endswith("/"),
            "explicit-consumer-ref-required")
    return selected


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ProviderTransport:
    """Credentials stay in the environment and HTTP headers, never artifacts/argv."""
    def __init__(self, provider, base, *, opener=None, max_bytes=MAX_BYTES):
        self.provider, self.base = provider, base
        require(type(max_bytes) is int and 1 <= max_bytes <= 65 * 1024 * 1024, "response-limit-invalid")
        self.max_bytes = max_bytes
        self.opener = opener or build_opener(_NoRedirect())

    def request(self, method, url, body=None, raw=False):
        require(method in ("GET", "POST") and (url == self.base or url.startswith(self.base + "/")),
                "provider-url-outside-binding")
        if self.provider == "gha":
            token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
            require(bool(token), "GH_TOKEN-or-GITHUB_TOKEN-required")
            authorization = "Bearer " + token
        else:
            token = os.environ.get("SYSTEM_ACCESSTOKEN")
            if token:
                authorization = "Bearer " + token
            else:
                token = os.environ.get("AZURE_DEVOPS_EXT_PAT")
                require(bool(token), "SYSTEM_ACCESSTOKEN-or-AZURE_DEVOPS_EXT_PAT-required")
                authorization = "Basic " + base64.b64encode((":" + token).encode()).decode()
        headers = {"Authorization": authorization, "Accept": "application/json",
                   "Content-Type": "application/json", "User-Agent": "ESAF-pipelines/1"}
        if self.provider == "gha":
            headers["X-GitHub-Api-Version"] = "2022-11-28"
        payload = json.dumps(body).encode() if body is not None else None
        for redirect in range(4):
            try:
                response = self.opener.open(Request(url, data=payload, headers=headers, method=method), timeout=30)
            except HTTPError as error:
                if raw and method == "GET" and error.code in (301, 302, 303, 307, 308):
                    target = error.headers.get("Location", "")
                    parsed = urlsplit(target)
                    require(parsed.scheme == "https" and not parsed.username and not parsed.password
                            and parsed.port in (None, 443) and parsed.hostname is not None
                            and any(parsed.hostname.endswith(suffix) for suffix in
                                    (".blob.core.windows.net", ".githubusercontent.com", ".vsassets.io")),
                            "artifact-redirect-outside-provider")
                    url, headers = target, {"Accept": "application/octet-stream"}
                    continue
                raise DispatchError("provider-http-error-" + str(error.code)) from None
            except (URLError, OSError):
                raise DispatchError("provider-transport-failed-no-write-retry") from None
            with response:
                data = response.read(self.max_bytes + 1)
                require(len(data) <= self.max_bytes, "provider-response-too-large")
                response_headers = {key.lower(): value for key, value in response.headers.items()}
                try:
                    value = data if raw else (json.loads(data) if data else None)
                except (ValueError, UnicodeError):
                    raise DispatchError("provider-response-invalid") from None
                return response.status, response_headers, value
        raise DispatchError("artifact-redirect-limit")


def _pages(transport, url, collection, *, max_pages=10):
    rows = []
    for page in range(1, max_pages + 1):
        _, headers, data = transport.request("GET", url + ("&" if "?" in url else "?")
                                             + f"per_page=100&page={page}")
        require(isinstance(data, dict) and isinstance(data.get(collection), list), "provider-page-invalid")
        rows.extend(data[collection])
        if 'rel="next"' not in headers.get("link", ""):
            return rows
    raise DispatchError("provider-pagination-limit")


def _gha_identity(run, *, binding, workflow, correlation, run_id=None):
    require(isinstance(run, dict) and type(run.get("id")) is int and run["id"] > 0
            and (run_id is None or run["id"] == run_id) and run.get("workflow_id") == workflow
            and run.get("event") == "workflow_dispatch"
            and run.get("display_title") == f"pipelines-only [{correlation}]"
            and run.get("head_sha") == binding["consumer_commit"] and run.get("run_attempt") == 1
            and run.get("repository", {}).get("full_name", "").lower() ==
            binding["repository"].removeprefix("https://github.com/").lower(), "provider-run-identity-mismatch")


def _ado_identity(run, *, binding, correlation, request_digest, run_id=None):
    require(isinstance(run, dict) and type(run.get("id")) is int and run["id"] > 0
            and (run_id is None or run["id"] == run_id)
            and run.get("pipeline", {}).get("id") == binding["pipeline_id"]
            and run.get("resources", {}).get("repositories", {}).get("self", {}).get("version")
            == binding["consumer_commit"]
            and run.get("templateParameters", {}).get("correlation_id") == correlation
            and run.get("templateParameters", {}).get("request_digest") == request_digest,
            "provider-run-identity-mismatch")


def _ado_definition(transport, base, binding):
    pipeline_id = binding.get("pipeline_id")
    if pipeline_id is None:
        continuation, matches = "", []
        for _ in range(10):
            url = f"{base}/build/definitions?includeAllProperties=true&%24top=100&api-version=7.1"
            if continuation:
                url += "&continuationToken=" + quote(continuation, safe="")
            _, headers, data = transport.request("GET", url)
            require(isinstance(data, dict) and isinstance(data.get("value"), list), "provider-page-invalid")
            matches.extend(row for row in data["value"]
                           if row.get("process", {}).get("yamlFilename", "").lstrip("/") == ADO_WORKFLOW
                           and row.get("repository", {}).get("url", "").rstrip("/").lower()
                           == binding["repository"].lower())
            token = headers.get("x-ms-continuationtoken", "")
            if not token:
                break
            require(token != continuation, "provider-pagination-stalled")
            continuation = token
        else:
            raise DispatchError("provider-pagination-limit")
        require(len(matches) == 1 and type(matches[0].get("id")) is int
                and matches[0]["id"] > 0, "fixed-provider-workflow-ambiguous-or-missing")
        pipeline_id = matches[0]["id"]
    _, _, definition = transport.request("GET", f"{base}/build/definitions/{pipeline_id}?api-version=7.1")
    require(definition.get("id") == pipeline_id
            and definition.get("process", {}).get("yamlFilename", "").lstrip("/") == ADO_WORKFLOW
            and definition.get("repository", {}).get("url", "").rstrip("/").lower()
            == binding["repository"].lower(), "fixed-provider-workflow-required")
    return pipeline_id


def _ado_artifact_content_url(base, run_id, name):
    # Metadata may use a project GUID instead of its name. Never follow its
    # downloadUrl: the validated project, build and exact artifact are sufficient.
    return f"{base}/build/builds/{run_id}/artifacts?" + urlencode({
        "artifactName": name, "$format": "zip", "api-version": "7.1"})


def _receipt(transport, base, provider, run_id, correlation):
    name = f"esaf-receipt-{correlation}-1"
    if provider == "gha":
        rows = _pages(transport, f"{base}/actions/runs/{run_id}/artifacts", "artifacts")
        matches = [row for row in rows if row.get("name") == name and row.get("expired") is False]
        require(len(matches) == 1 and type(matches[0].get("id")) is int, "lifecycle-receipt-artifact-missing")
        url = f"{base}/actions/artifacts/{matches[0]['id']}/zip"
    else:
        _, headers, data = transport.request("GET", f"{base}/build/builds/{run_id}/artifacts?api-version=7.1")
        require(not headers.get("x-ms-continuationtoken"), "artifact-list-incomplete")
        matches = [row for row in data.get("value", []) if row.get("name") == name]
        require(len(matches) == 1, "lifecycle-receipt-artifact-missing")
        url = _ado_artifact_content_url(base, run_id, name)
    _, _, raw = transport.request("GET", url, raw=True)
    require(isinstance(raw, bytes) and len(raw) <= MAX_BYTES, "lifecycle-receipt-invalid")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = [member for member in archive.infolist() if not member.is_dir()]
            require(len(members) == 1 and PurePosixPath(members[0].filename).name == "receipt.json"
                    and members[0].file_size <= MAX_BYTES and not members[0].flag_bits & 1,
                    "lifecycle-receipt-invalid")
            value = json.loads(archive.read(members[0]))
        require(isinstance(value, dict), "lifecycle-receipt-invalid")
        return value
    except (ValueError, zipfile.BadZipFile, UnicodeError, OSError):
        raise DispatchError("lifecycle-receipt-invalid") from None


def _validated_operation(operation_id, record):
    from pipeline_lifecycle import bound_plan, digest as lifecycle_digest
    require(isinstance(record, dict) and record.get("schema") == 1
            and record.get("operation_id") == operation_id, "durable-operation-required")
    require(lifecycle_digest(record["snapshot"]) == record["snapshot_hash"]
            and lifecycle_digest(bound_plan(record)) == record["plan_hash"],
            "durable-operation-binding-mismatch")
    return record


class ProviderStateSnapshot:
    """One authenticated state-ref revision; never constructed from a CLI JSON proof."""
    def __init__(self, head, state):
        require(isinstance(head, str) and re.fullmatch(r"[a-f0-9]{40}", head)
                and isinstance(state, dict) and isinstance(state.get("records"), dict),
                "durable-provider-snapshot-required")
        self.head, self.state = head, copy.deepcopy(state)

    def _load(self, operation_id):
        from pipeline_lifecycle_adapters import RepositoryJournal
        record = self.state["records"].get(RepositoryJournal.key(operation_id))
        return self.head, _validated_operation(operation_id, copy.deepcopy(record))

    def read(self):
        return self.head, copy.deepcopy(self.state)

    def replace(self, *args, **kwargs):
        raise DispatchError("provider-snapshot-is-read-only")

    authenticate = observe = replace

    def canonical_configuration(self, factory_id):
        from lifecycle_admission import Admission
        return Admission(self, self).canonical_configuration(factory_id)


class ProviderReceiptReader:
    """Capability-limited CAS reader: never Azure auth, native observation or writes."""
    def __init__(self, expected, *, transport=None):
        from provider_repository_state import ProviderState
        from pipeline_lifecycle_adapters import RepositoryJournal
        self.provider = expected["provider"]
        binding = {"schema": 1, "provider": self.provider, "repository": expected["repository"],
                   "consumer_commit": expected["consumer_commit"]}
        self.base = validate_binding({"provider": self.provider}, binding)
        self.transport = transport or ProviderTransport(self.provider, self.base, max_bytes=65 * 1024 * 1024)
        self.journal = RepositoryJournal(ProviderState(
            self, {"kind": self.provider, "repository": expected["repository"]}, DispatchError))

    def state_request(self, provider, method, path, body=None, allowed=(200,)):
        require(provider == self.provider and method == "GET" and body is None,
                "provider-receipt-reader-is-read-only")
        url = "https://api.github.com/" + path if provider == "gha" else path
        status, headers, value = self.transport.request("GET", url)
        require(status in allowed, "provider-receipt-read-failed")
        return status, headers, value

    def _load(self, operation_id):
        from pipeline_lifecycle import identifier
        revision, record = self.journal.read(identifier(operation_id))
        return revision, _validated_operation(operation_id, record)

    def read_snapshot(self):
        return ProviderStateSnapshot(*self.journal.store.read())

    def observe(self, operation_id):
        raise DispatchError("pipeline-owned-finalizer-required")


def export_configuration(repo_root, request_path, canonical, binding, operation_id, output_root, *, reader=None):
    """Export the current quiescent canonical catalog, not an operation's saved proposal."""
    from pipeline_configuration import projections, write_new_root
    from pipeline_inputs import ordinary_path
    from pipeline_lifecycle import identifier, verify_receipt
    from pipeline_lifecycle_recovery import input_hash
    validate_binding(canonical, binding)
    destination = ordinary_path(Path(repo_root).absolute(), relative_path(output_root))
    require(destination.name == "azurefactory" and not destination.exists(), "new-export-root-required")
    route = {"provider": binding["provider"], "repository": binding["repository"],
             "consumer_commit": binding["consumer_commit"]}
    snapshot = (reader or ProviderReceiptReader(route)).read_snapshot()
    require(snapshot.state.get("repository") == binding["repository"], "export-repository-mismatch")
    _, root = snapshot._load(identifier(operation_id))
    context = root["plan"].get("provider_context", {})
    factory_id, request_digest = canonical["factory"]["id"], digest(canonical)
    require(context.get("request_path") == request_path and context.get("request_digest") == request_digest
            and context.get("provider") == binding["provider"] and context.get("repository") == binding["repository"]
            and context.get("source_commit") == canonical["source"]["commit"]
            and context.get("scenario") == canonical["request"]["scenario"],
            "export-operation-input-mismatch")
    receipt = {"operation_id": operation_id, "plan_hash": root["plan_hash"],
               "provider_context": context, "status": "succeeded"}
    verify_receipt(receipt, context, service=snapshot)
    completed = root
    while True:
        child_context = completed["plan"].get("provider_context", {})
        require({key: value for key, value in child_context.items() if key not in ("run_id", "correlation_id")}
                == {key: value for key, value in context.items() if key not in ("run_id", "correlation_id")}
                and input_hash(completed) == request_digest
                and completed["snapshot"]["factory"]["id"] == factory_id
                and completed["finalization"]["proof"]["proof_kind"] == (
                    "github-rs256-native-finalizer" if binding["provider"] == "gha" else "ado-native-server-finalizer"),
                "export-completion-binding-mismatch")
        if not completed.get("completion"):
            break
        _, completed = snapshot._load(completed["completion"]["operation_id"])
    admission = snapshot.state["records"].get("lifecycle_admission_v1", {})
    require(snapshot.state.get("active") is None and admission.get("claim") is None,
            "export-canonical-operation-still-active")
    current = snapshot.canonical_configuration(factory_id)
    projections(current["document"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination = write_new_root(repo_root, output_root, current["document"])
    return {"outcome": "configuration-exported", "operation_id": operation_id,
            "completed_operation_id": completed["operation_id"], "factory_id": factory_id,
            "factory_present": any(row["id"] == factory_id for row in current["document"]["factories"]),
            "configuration_revision": current["revision"], "provider_state_revision": snapshot.head,
            "source": "current-provider-canonical", "output_root": str(destination)}


def verify_lifecycle_receipt(receipt, expected):
    try:
        from pipeline_lifecycle import verify_receipt
    except ImportError:
        raise DispatchError("lifecycle-status-verifier-unavailable") from None
    reader = ProviderReceiptReader(expected)
    if isinstance(receipt, dict) and receipt.get("status") == "continuation-required":
        from pipeline_lifecycle import identifier
        _, record = reader._load(identifier(receipt.get("operation_id")))
        require(receipt.get("provider_context") == expected
                and record["plan"].get("provider_context") == expected
                and record["plan_hash"] == receipt.get("plan_hash")
                and record["status"] in ("continuation-required", "succeeded"),
                "durable-continuation-binding-mismatch")
        proof = record.get("finalization", {}).get("proof", {})
        require(record.get("admission", {}).get("status") == "released"
                and record.get("finalization", {}).get("status") == "succeeded"
                and proof.get("operation_id") == record["operation_id"]
                and proof.get("plan_hash") == record["plan_hash"]
                and proof.get("proof_kind") == ("github-rs256-native-finalizer" if expected["provider"] == "gha"
                                               else "ado-native-server-finalizer"),
                "continuation-finalization-required")
        continuation = record.get("provider_continuation", {})
        require(continuation == receipt.get("provider_continuation")
                and continuation.get("status") == "dispatched"
                and type(continuation.get("run_id")) is int and continuation["run_id"] > 0
                and continuation["run_id"] != expected["run_id"]
                and re.fullmatch(r"[a-f0-9]{32}", continuation.get("correlation_id", "")),
                "continuation-dispatch-binding-mismatch")
        return {"outcome": "continuation-required", "operation_id": record["operation_id"],
                "plan_hash": record["plan_hash"], "continuation": continuation,
                "continuation_of": record["plan"].get("continuation_of"),
                "recovery_of": record["plan"].get("recovery_of")}
    status = verify_receipt(receipt, expected, service=reader)
    relationships = [key for key in ("continuation_of", "recovery_of") if receipt.get(key) is not None]
    if relationships:
        _, record = reader._load(status["operation_id"])
        for key in relationships:
            require(receipt[key] == record["plan"].get(key), "continuation-parent-binding-mismatch")
            status[key] = record["plan"][key]
    return status


def dispatch_run(parameters, canonical, binding, *, transport=None,
                 max_polls=240, poll_seconds=15, sleep=time.sleep):
    """Queue once and resolve the exact native run; never run Azure or wait for effects."""
    base = validate_binding(canonical, binding)
    correlation, request_digest = parameters["correlation_id"], parameters["request_digest"]
    request = canonical.get("request", canonical)
    provider = request["provider"]
    selected_ref = consumer_ref(canonical, binding)
    transport = transport or ProviderTransport(provider, base)
    workflow_id = None
    if provider == "gha":
        _, _, workflow = transport.request("GET", base + "/actions/workflows/pipelines-only-gha.yml")
        require(workflow.get("path") == GHA_WORKFLOW and workflow.get("state") == "active"
                and type(workflow.get("id")) is int, "fixed-provider-workflow-required")
        workflow_id = workflow["id"]
        _, _, commit = transport.request("GET", base + "/commits/" + quote(selected_ref, safe=""))
        require(commit.get("sha") == binding["consumer_commit"], "consumer-ref-moved")
        runs_url = f"{base}/actions/workflows/{workflow_id}/runs?event=workflow_dispatch"
        existing = {run["id"] for run in _pages(transport, runs_url, "workflow_runs")}
        transport.request("POST", f"{base}/actions/workflows/{workflow_id}/dispatches",
                          {"ref": selected_ref, "inputs": parameters})
        run_id = None
        for _ in range(max_polls):
            matches = [run for run in _pages(transport, runs_url, "workflow_runs")
                       if run.get("display_title") == f"pipelines-only [{correlation}]" and run.get("id") not in existing]
            require(len(matches) <= 1, "provider-correlation-ambiguous")
            if matches:
                _gha_identity(matches[0], binding=binding, workflow=workflow_id, correlation=correlation)
                run_id = matches[0]["id"]
                break
            sleep(poll_seconds)
        require(run_id is not None, "provider-dispatch-unconfirmed-no-retry")
    else:
        pipeline_id = _ado_definition(transport, base, binding)
        binding = dict(binding, pipeline_id=pipeline_id)
        _, _, run = transport.request("POST", f"{base}/pipelines/{pipeline_id}/runs?api-version=7.1", {
            "resources": {"repositories": {"self": {"refName": selected_ref,
                                                    "version": binding["consumer_commit"]}}},
            "templateParameters": parameters})
        _ado_identity(run, binding=binding, correlation=correlation, request_digest=request_digest)
        run_id = run["id"]
    return run_id, binding, workflow_id


def dispatch_and_wait(request_path, canonical, binding, *, transport=None, verify=None,
                      correlation_id=None, max_polls=240, poll_seconds=15, sleep=time.sleep,
                      parent_operation_id=None, parent_plan_hash=None,
                      recovery_operation_id=None, recovery_plan_hash=None):
    relative_path(request_path)
    selection = operation_selection(parent_operation_id=parent_operation_id, parent_plan_hash=parent_plan_hash,
                                    recovery_operation_id=recovery_operation_id, recovery_plan_hash=recovery_plan_hash)
    selected_field = "recovery_of" if recovery_operation_id else "continuation_of"
    selected_relationship = {"operation_id": recovery_operation_id or parent_operation_id,
                             "plan_hash": recovery_plan_hash or parent_plan_hash}
    base = validate_binding(canonical, binding)
    require(type(max_polls) is int and 1 <= max_polls <= 5760
            and type(poll_seconds) in (int, float) and 0 <= poll_seconds <= 300, "poll-bounds-invalid")
    correlation = correlation_id or uuid4().hex
    require(re.fullmatch(r"[a-f0-9]{32}", correlation) is not None, "correlation-invalid")
    request = canonical.get("request", canonical)
    provider, request_digest = request["provider"], digest(canonical)
    transport = transport or ProviderTransport(provider, base)
    verify = verify or verify_lifecycle_receipt
    parameters = {"request_path": request_path, "request_digest": request_digest,
                  "correlation_id": correlation, "consumer_commit": binding["consumer_commit"],
                  "source_commit": request["source_commit"]}
    run_id, binding, workflow_id = dispatch_run(dict(parameters, **selection), canonical, binding, transport=transport,
                                               max_polls=max_polls, poll_seconds=poll_seconds, sleep=sleep)
    root_run, root_correlation = run_id, correlation
    root_receipt, root_expected, relationship = None, None, None
    seen = {run_id}
    completed_runs = []
    for _ in range(max_polls):
        if provider == "gha":
            _, _, run = transport.request("GET", f"{base}/actions/runs/{run_id}")
            _gha_identity(run, binding=binding, workflow=workflow_id, correlation=correlation, run_id=run_id)
            terminal, result = run.get("status") == "completed", run.get("conclusion")
            success = "success"
        else:
            _, _, run = transport.request("GET", f"{base}/pipelines/{binding['pipeline_id']}/runs/{run_id}?api-version=7.1")
            _ado_identity(run, binding=binding, correlation=correlation, request_digest=request_digest, run_id=run_id)
            terminal, result = run.get("state") == "completed", run.get("result")
            success = "succeeded"
        if terminal:
            require(result == success, "provider-run-unsuccessful:" + str(result))
            receipt = _receipt(transport, base, provider, run_id, correlation)
            expected = dict(parameters, correlation_id=correlation, provider=provider, repository=binding["repository"],
                            run_id=run_id, run_attempt=1, scenario=request["scenario"])
            status = verify(receipt, expected)
            require(isinstance(status, dict) and status.get("outcome") in ("completed", "continuation-required"),
                    "lifecycle-not-completed")
            require(not selection or run_id != root_run or status.get(selected_field) == selected_relationship,
                    "selected-predecessor-binding-mismatch")
            require(relationship is None or status.get("continuation_of") == relationship,
                    "continuation-parent-binding-mismatch")
            # A completed GitHub run ID can start a new attempt during artifact reads.
            if provider == "gha":
                _, _, fresh = transport.request("GET", f"{base}/actions/runs/{run_id}")
                _gha_identity(fresh, binding=binding, workflow=workflow_id, correlation=correlation, run_id=run_id)
                require(fresh.get("status") == "completed" and fresh.get("conclusion") == "success",
                        "provider-completion-changed")
            else:
                _, _, fresh = transport.request(
                    "GET", f"{base}/pipelines/{binding['pipeline_id']}/runs/{run_id}?api-version=7.1")
                _ado_identity(fresh, binding=binding, correlation=correlation,
                              request_digest=request_digest, run_id=run_id)
                require(fresh.get("state") == "completed" and fresh.get("result") == "succeeded",
                        "provider-completion-changed")
            completed_runs.append((run_id, correlation))
            if status["outcome"] == "continuation-required":
                if root_receipt is None:
                    root_receipt, root_expected = receipt, expected
                continuation = status.get("continuation", {})
                child = continuation.get("run_id")
                require(type(child) is int and child > 0 and child not in seen and len(seen) < 8
                        and re.fullmatch(r"[a-f0-9]{32}", continuation.get("correlation_id", "")),
                        "continuation-chain-invalid")
                seen.add(child)
                relationship = {"operation_id": status["operation_id"], "plan_hash": status["plan_hash"]}
                run_id, correlation = child, continuation["correlation_id"]
                continue
            if root_receipt is not None:
                # The artifact remains a truthful intermediate receipt. Only a
                # fresh durable read may establish completion of the root.
                status = verify(dict(root_receipt, status="succeeded"), root_expected)
                require(status.get("outcome") == "completed", "root-lifecycle-not-completed")
                require(not selection or status.get(selected_field) == selected_relationship,
                        "selected-predecessor-binding-mismatch")
                for completed_id, completed_correlation in completed_runs:
                    if provider == "gha":
                        _, _, fresh = transport.request("GET", f"{base}/actions/runs/{completed_id}")
                        _gha_identity(fresh, binding=binding, workflow=workflow_id,
                                      correlation=completed_correlation, run_id=completed_id)
                        require(fresh.get("status") == "completed" and fresh.get("conclusion") == "success",
                                "provider-completion-changed")
                    else:
                        _, _, fresh = transport.request(
                            "GET", f"{base}/pipelines/{binding['pipeline_id']}/runs/{completed_id}?api-version=7.1")
                        _ado_identity(fresh, binding=binding, correlation=completed_correlation,
                                      request_digest=request_digest, run_id=completed_id)
                        require(fresh.get("state") == "completed" and fresh.get("result") == "succeeded",
                                "provider-completion-changed")
            return dict(status, provider=provider, run_id=root_run, correlation_id=root_correlation)
        sleep(poll_seconds)
    raise DispatchError("provider-wait-timeout-not-completed")


def load_request(root, request_path):
    from pipeline_inputs import read_json, resolve_request
    raw = read_json(root, relative_path(request_path))
    if isinstance(raw, dict):
        require(not any(environment_file_path(raw[key]) for key in
                        ("azurefactory_root", "variables", "provider_binding", "bundle") if raw.get(key)),
                "environment-file-transport-forbidden")
    return resolve_request(root, raw)


def _git(root, *arguments):
    return subprocess.run(["git", "-C", str(root), *arguments], capture_output=True,
                          text=True, check=True, shell=False).stdout.strip()


def verify_checkout(root, request_path, canonical, binding):
    request = canonical.get("request", canonical)
    require(_git(root, "rev-parse", "HEAD") == binding["consumer_commit"], "local-consumer-commit-mismatch")
    require(not (root / "azure-enterprise-scale-ml").is_symlink(), "ordinary-pinned-submodule-required")
    require(_git(root / "azure-enterprise-scale-ml", "rev-parse", "HEAD") == request["source_commit"],
            "pinned-source-commit-mismatch")
    tree = _git(root, "ls-tree", "HEAD", "--", "azure-enterprise-scale-ml").split()
    require(len(tree) >= 3 and tree[:3] == ["160000", "commit", request["source_commit"]],
            "consumer-submodule-pin-mismatch")
    # Files referenced by the request must exist at the dispatched consumer commit.
    # A ZIP may instead be pre-downloaded by an installed provider artifact step.
    paths = [request_path, request["azurefactory_root"]]
    paths.extend(request[key] for key in ("provider_binding", "variables") if request.get(key))
    if request.get("bundle"):
        paths.extend([request_path + ".artifact.json", ":(exclude)" + request["bundle"]])
    require(not _git(root, "status", "--porcelain", "--untracked-files=all", "--", *paths),
            "dispatch-inputs-not-committed")
    require(bool(_git(root, "ls-files", "--error-unmatch", "--", request_path)), "request-not-committed")


def preflight(root, request_path, canonical, binding, provider, output):
    request = canonical["request"]
    require(provider == request["provider"], "provider-route-mismatch")
    verify_checkout(root, request_path, canonical, binding)
    selected_ref = consumer_ref(canonical, binding)
    expected = {"request_digest": digest(canonical), "consumer_commit": binding["consumer_commit"],
                "source_commit": request["source_commit"]}
    for key, value in expected.items():
        supplied = os.environ.get("ESAF_" + key.upper())
        require(not supplied or supplied == value, "provider-input-mismatch:" + key)
    if provider == "gha":
        require(os.environ.get("GITHUB_SHA") == binding["consumer_commit"]
                and os.environ.get("GITHUB_WORKFLOW_SHA") == binding["consumer_commit"]
                and os.environ.get("GITHUB_REF") == selected_ref
                and os.environ.get("GITHUB_REPOSITORY", "").lower() ==
                binding["repository"].removeprefix("https://github.com/").lower()
                and os.environ.get("GITHUB_RUN_ATTEMPT") == "1", "provider-execution-context-mismatch")
        run_id = os.environ.get("GITHUB_RUN_ID", "")
    else:
        require(os.environ.get("BUILD_SOURCEVERSION") == binding["consumer_commit"]
                and os.environ.get("BUILD_SOURCEBRANCH") == selected_ref
                and os.environ.get("BUILD_REPOSITORY_URI", "").lower() == binding["repository"].lower()
                and os.environ.get("SYSTEM_JOBATTEMPT") == "1", "provider-execution-context-mismatch")
        run_id = os.environ.get("BUILD_BUILDID", "")
    correlation = os.environ.get("ESAF_CORRELATION_ID") or uuid4().hex
    require(re.fullmatch(r"[a-f0-9]{32}", correlation) is not None
            and re.fullmatch(r"[1-9][0-9]*", run_id) is not None, "provider-context-invalid")
    expected.update(correlation_id=correlation, request_path=request_path, provider=provider,
                    run_id=int(run_id), run_attempt=1, scenario=request["scenario"],
                    repository=binding["repository"])
    path = root / relative_path(output)
    require(path.resolve().is_relative_to(root.resolve()) and not path.exists(), "new-context-path-required")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(expected, stream, sort_keys=True)
    return expected


def operational_binding(root, canonical):
    from pipeline_inputs import BundleInputs, RepositoryInputs
    request = canonical["request"]
    if request.get("provider_binding"):
        reader = (BundleInputs(root, request["bundle"], request["azurefactory_root"])
                  if request.get("bundle") else RepositoryInputs(root))
        binding = reader.read(request["provider_binding"])
    else:
        binding = {"schema": 1, "provider": request["provider"],
                   "repository": canonical["binding"].get("repository")}
    require(isinstance(binding, dict) and "consumer_commit" not in binding,
            "consumer-commit-is-derived-not-configured")
    lifecycle_fields = {"bootstrap", "admission"}
    require(all(isinstance(binding[key], dict) for key in lifecycle_fields & binding.keys()),
            "provider-lifecycle-binding-object-required")
    # Lifecycle metadata stays in the canonical snapshot, not the dispatch route.
    result = {key: value for key, value in binding.items() if key not in lifecycle_fields}
    result["consumer_commit"] = _git(root, "rev-parse", "HEAD")
    if "consumer_ref" not in result and canonical["binding"].get("ref"):
        result["consumer_ref"] = canonical["binding"]["ref"]
    return result


def _origin_repository(root):
    origin = _git(root, "remote", "get-url", "origin").removesuffix(".git")
    if origin.startswith("git@github.com:"):
        origin = "https://github.com/" + origin.removeprefix("git@github.com:")
    elif origin.startswith("git@ssh.dev.azure.com:v3/"):
        parts = origin.removeprefix("git@ssh.dev.azure.com:v3/").split("/")
        require(len(parts) == 3, "consumer-origin-required")
        origin = f"https://dev.azure.com/{parts[0]}/{parts[1]}/_git/{parts[2]}"
    return origin


def _producer_run(transport, base, provider, source):
    identifier = source["run_id"]
    if provider == "gha":
        _, _, run = transport.request("GET", f"{base}/actions/runs/{identifier}")
        require(run.get("id") == identifier and run.get("head_sha") == source["producer_commit"]
                and run.get("run_attempt") == 1 and run.get("status") == "completed"
                and run.get("conclusion") == "success"
                and run.get("repository", {}).get("full_name", "").lower() ==
                source["repository"].removeprefix("https://github.com/").lower(),
                "input-artifact-producer-mismatch-or-unsuccessful")
    else:
        _, _, run = transport.request("GET", f"{base}/build/builds/{identifier}?api-version=7.1")
        require(run.get("id") == identifier and run.get("sourceVersion") == source["producer_commit"]
                and run.get("status") == "completed" and run.get("result") == "succeeded"
                and run.get("repository", {}).get("url", "").lower() == source["repository"].lower(),
                "input-artifact-producer-mismatch-or-unsuccessful")


def _input_archive(transport, base, provider, source):
    from pipeline_inputs import MAX_ARCHIVE_BYTES, relative_path as input_path
    identifier, name = source["run_id"], source["artifact_name"]
    if provider == "gha":
        rows = _pages(transport, f"{base}/actions/runs/{identifier}/artifacts", "artifacts")
        selected = [row for row in rows if row.get("name") == name and row.get("expired") is False]
        require(len(selected) == 1 and type(selected[0].get("id")) is int
                and selected[0].get("workflow_run", {}).get("id") == identifier
                and selected[0].get("workflow_run", {}).get("head_sha") == source["producer_commit"],
                "exact-input-artifact-required")
        url = f"{base}/actions/artifacts/{selected[0]['id']}/zip"
    else:
        _, headers, data = transport.request("GET", f"{base}/build/builds/{identifier}/artifacts?api-version=7.1")
        require(not headers.get("x-ms-continuationtoken"), "input-artifact-list-incomplete")
        selected = [row for row in data.get("value", []) if row.get("name") == name]
        require(len(selected) == 1, "exact-input-artifact-required")
        url = _ado_artifact_content_url(base, identifier, name)
    _, _, raw = transport.request("GET", url, raw=True)
    require(isinstance(raw, bytes) and len(raw) <= MAX_ARCHIVE_BYTES + 1024 * 1024,
            "input-artifact-wrapper-size-limit")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            require(1 <= len(members) <= 64, "input-artifact-wrapper-entry-limit")
            names, files = set(), []
            for member in members:
                path = member.filename.rstrip("/") if member.is_dir() else member.filename
                input_path(path)
                require(not environment_file_path(path), "environment-file-transport-forbidden")
                require(path.casefold() not in names and not member.flag_bits & 1
                        and stat.S_IFMT(member.external_attr >> 16) in (0, stat.S_IFREG, stat.S_IFDIR),
                        "unsafe-input-artifact-wrapper")
                names.add(path.casefold())
                if not member.is_dir():
                    files.append(member)
            allowed = {source["archive_path"]}
            if provider == "ado":
                allowed.add(name + "/" + source["archive_path"])
            require(len(files) == 1 and files[0].filename in allowed
                    and files[0].file_size <= MAX_ARCHIVE_BYTES
                    and files[0].file_size <= max(1024 * 1024, files[0].compress_size * 100),
                    "exact-bounded-input-zip-required")
            content = archive.read(files[0])
    except (ValueError, zipfile.BadZipFile, OSError):
        raise DispatchError("invalid-input-artifact-wrapper") from None
    return content


def _artifact_source(root, request_path, request):
    from pipeline_inputs import read_json
    source = read_json(root, request_path + ".artifact.json")
    require(isinstance(source, dict) and set(source) == {
        "schema", "provider", "repository", "run_id", "artifact_name",
        "archive_path", "archive_sha256", "producer_commit"},
        "input-artifact-source-schema-invalid")
    require(type(source["schema"]) is int and source["schema"] == 1
            and source["provider"] == request["provider"] and type(source["run_id"]) is int and source["run_id"] > 0
            and isinstance(source["artifact_name"], str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", source["artifact_name"])
            and isinstance(source["archive_path"], str) and source["archive_path"].endswith(".zip")
            and re.fullmatch(r"[a-f0-9]{64}", str(source["archive_sha256"]))
            and re.fullmatch(r"[a-f0-9]{40}", str(source["producer_commit"])),
            "input-artifact-source-invalid")
    relative_path(source["archive_path"])
    validate_binding(request, {"schema": 1, "provider": source["provider"],
                               "repository": source["repository"], "consumer_commit": "0" * 40})
    return source


def input_evidence(repo_root, request_path):
    """Offline input drift evidence for the actual prepared-operation review."""
    from pipeline_inputs import MAX_ARCHIVE_BYTES, normalize_request, ordinary_path, read_json
    root = Path(repo_root).absolute()
    request = normalize_request(read_json(root, relative_path(request_path)))
    if not request.get("bundle"):
        return None
    source = _artifact_source(root, request_path, request)
    target = ordinary_path(root, request["bundle"])
    require(target.is_file() and target.stat().st_size <= MAX_ARCHIVE_BYTES, "bounded-input-bundle-required")
    actual, expected = hashlib.sha256(target.read_bytes()).hexdigest(), source["archive_sha256"]
    return {key: source[key] for key in ("provider", "repository", "run_id", "artifact_name",
                                        "producer_commit", "archive_path")} | {
        "expected_sha256": expected, "actual_sha256": actual, "drift": expected != actual,
        "warning": "input-archive-digest-drift" if expected != actual else None}


def download_input(repo_root, request_path, *, provider=None, transport=None, environ=None):
    """Fetch a pinned artifact ZIP, never extract it, then use the canonical resolver.

    The committed sidecar is outside the ZIP to avoid embedding a ZIP's own digest
    inside itself. It is an exact transport selector, not consent or configuration.
    """
    from pipeline_inputs import MAX_ARCHIVE_BYTES, normalize_request, ordinary_path, read_json
    root = Path(repo_root).absolute()
    request = normalize_request(read_json(root, relative_path(request_path)))
    require(provider is None or provider == request["provider"], "provider-route-mismatch")
    if not request.get("bundle"):
        return {"downloaded": False}
    require(not environment_file_path(request["bundle"]), "environment-file-transport-forbidden")
    components = {part.casefold() for part in PurePosixPath(request["bundle"]).parts}
    require(request["bundle"].endswith(".zip") and not components & {
        ".git", ".github", ".azure", ".esaf", ".pipeline-lifecycle", "azure-enterprise-scale-ml"}
        and not any(part.startswith(".esaf-azure-") for part in components),
        "safe-input-bundle-target-required")
    provider, sidecar_path = request["provider"], request_path + ".artifact.json"
    source = _artifact_source(root, request_path, request)
    commit = _git(root, "rev-parse", "HEAD")
    binding = {"schema": 1, "provider": provider, "repository": source["repository"], "consumer_commit": commit}
    base = validate_binding(request, binding)
    env = os.environ if environ is None else environ
    if provider == "gha" and env.get("GITHUB_ACTIONS") == "true":
        actual_repository = "https://github.com/" + env.get("GITHUB_REPOSITORY", "")
        require(env.get("GITHUB_SHA") == commit and env.get("GITHUB_WORKFLOW_SHA") == commit
                and env.get("GITHUB_RUN_ATTEMPT") == "1", "input-download-consumer-context-mismatch")
    elif provider == "ado" and env.get("TF_BUILD", "").lower() == "true":
        actual_repository = env.get("BUILD_REPOSITORY_URI", "")
        require(env.get("BUILD_SOURCEVERSION") == commit and env.get("SYSTEM_JOBATTEMPT") == "1",
                "input-download-consumer-context-mismatch")
    else:
        actual_repository = _origin_repository(root)
    require(actual_repository.lower() == source["repository"].lower(), "input-artifact-repository-mismatch")
    verify_checkout(root, request_path, {"request": request}, binding)
    require(bool(_git(root, "ls-files", "--error-unmatch", "--", sidecar_path)),
            "artifact-source-must-be-committed")
    target = ordinary_path(root, request["bundle"])
    if target.exists():
        require(target.is_file() and target.stat().st_size <= MAX_ARCHIVE_BYTES,
                "existing-bundle-must-not-be-overwritten")
    transport = transport or ProviderTransport(provider, base, max_bytes=MAX_ARCHIVE_BYTES + 1024 * 1024)
    _producer_run(transport, base, provider, source)
    content = _input_archive(transport, base, provider, source)
    _producer_run(transport, base, provider, source)
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            require(not any(environment_file_path(member.filename) for member in archive.infolist()),
                    "environment-file-transport-forbidden")
    except zipfile.BadZipFile:
        raise ValueError("invalid-input-bundle") from None
    if target.exists():
        require(target.read_bytes() == content, "existing-bundle-must-not-be-overwritten")
    created = False
    try:
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target = ordinary_path(root, request["bundle"])
            with target.open("xb") as stream:
                created = True
                stream.write(content)
        canonical = load_request(root, request_path)
        validate_binding(canonical, binding)
        require(canonical["binding"].get("repository") == source["repository"],
                "artifact-canonical-repository-mismatch")
    except Exception:
        if created:
            target.unlink()
        raise
    evidence = input_evidence(root, request_path)
    return {"downloaded": True, "bundle": request["bundle"], "archive_sha256": evidence["actual_sha256"],
            "producer_run_id": source["run_id"], "request_digest": digest(canonical), "input_artifact": evidence}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--request", required=True)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--expected-digest")
    parser.add_argument("--max-polls", type=int, default=240)
    parser.add_argument("--job-provider", choices=("gha", "ado"))
    parser.add_argument("--output-context")
    parser.add_argument("--download-input", action="store_true")
    parser.add_argument("--export-configuration", action="store_true",
                        help="Read verified provider authority and export its current canonical catalog; never dispatch")
    parser.add_argument("--operation-id", help="Completed root operation whose continuation chain must be finalized")
    parser.add_argument("--output-root", help="New repository-relative destination ending in azurefactory")
    parser.add_argument("--parent-operation-id")
    parser.add_argument("--parent-plan-hash")
    parser.add_argument("--recovery-operation-id", help="Prior terminal-run operation retaining its admission claim")
    parser.add_argument("--recovery-plan-hash", help="Exact prior plan; recovery still requires a new protected review")
    parser.add_argument("--env-file", type=Path, help="Explicit untracked local dispatch credentials; never uploaded")
    args = parser.parse_args(argv)
    try:
        relative_path(args.request)
        selection = operation_selection(parent_operation_id=args.parent_operation_id, parent_plan_hash=args.parent_plan_hash,
                                        recovery_operation_id=args.recovery_operation_id,
                                        recovery_plan_hash=args.recovery_plan_hash)
        require(not selection or not (args.export_configuration or args.job_provider),
                "operation-selection-is-dispatch-only")
        if args.export_configuration:
            from pipeline_lifecycle import identifier
            require(args.operation_id and args.output_root and not args.job_provider and not args.output_context,
                    "export-operation-and-new-root-required")
            identifier(args.operation_id)
            relative_path(args.output_root)
        else:
            require(args.operation_id is None and args.output_root is None, "export-mode-required")
        if args.env_file is not None:
            require(not args.job_provider and os.environ.get("GITHUB_ACTIONS") != "true"
                    and os.environ.get("TF_BUILD", "").lower() != "true", "local-dispatch-env-file-only")
            load_dispatch_env(args.env_file)
        if args.download_input:
            print(json.dumps(download_input(args.repo_root, args.request, provider=args.job_provider)))
            return 0
        canonical = load_request(args.repo_root, args.request)
        if args.expected_digest:
            require(digest(canonical) == args.expected_digest, "prepared-request-digest-mismatch")
        request = canonical["request"]
        binding = operational_binding(args.repo_root, canonical)
        validate_binding(canonical, binding)
        if args.job_provider:
            require(args.validate_only and args.output_context, "job-preflight-is-validation-only")
            print(json.dumps(preflight(args.repo_root, args.request, canonical, binding,
                                       args.job_provider, args.output_context)))
            return 0
        if args.validate_only:
            print(json.dumps({"valid": True, "request_digest": digest(canonical)}))
            return 0
        if args.export_configuration:
            print(json.dumps(export_configuration(args.repo_root, args.request, canonical, binding,
                                                  args.operation_id, args.output_root)))
            return 0
        verify_checkout(args.repo_root, args.request, canonical, binding)
        correlation = uuid4().hex
        print(json.dumps({"phase": "dispatching", "correlation_id": correlation,
                          "provider": request["provider"]}), file=sys.stderr)
        print(json.dumps(dispatch_and_wait(args.request, canonical, binding, max_polls=args.max_polls,
                                           correlation_id=correlation, **selection)))
        return 0
    except (DispatchError, ValueError, RuntimeError, OSError, ImportError, subprocess.SubprocessError) as error:
        # Provider stderr, token values, remote response bodies and request content are never echoed.
        code = str(error) if isinstance(error, (DispatchError, CredentialError)) else "pipeline-validation-or-runtime-unavailable"
        print(json.dumps({"outcome": "not-completed", "error": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
