"""Foundry hosted-agent runtime for example 49: the Playground entry point.

The hosted agent runs the same plan-bound MLRuntime inside the Foundry sandbox with its own Entra
agent identity instead of the operator's Azure CLI. Plans, approvals and AzureMLRollout receipts are
mirrored below the use case's ``agent-state`` prefix in the shared lake, so every Playground
conversation sees the same jobs and a recorded job is never resubmitted.

Approval stays human and per user. ``plan_run`` only proposes a plan. The host approves it when,
and only when, the same platform user's own message is ``approve <approval code>`` for that user's
pending plan within 30 minutes. An approved plan allows writes for 12 hours and only for the user
who approved it. Model output and tool results never approve anything.
"""
from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time

from . import agent as client_tools
from . import factory
from .configuration import TEMPLATE, paths, read_json, validate, write_json
from .plan import approved_plan, build_plan, save_plan
from .runtime import MLRuntime, redact
from .usecases import AIR, CHURN

BUNDLE = TEMPLATE / "bundle"
APPROVE = re.compile(r"\s*approve\s+([0-9a-f]{12,64})\s*[.!]?\s*", re.I)
SKIP = frozenset({"code", "aif49-gold-input", "lake-staging", "work", "__pycache__"})
APPROVALS = "hosted-approvals"
MUTATING = frozenset({"create_usecase_from_template", "start_training", "start_retraining", "run_batch_inference"})
PENDING_SECONDS = 30 * 60
ACTIVE_SECONDS = 12 * 3600
LEASE_SECONDS = 60
WAIT_SECONDS = 20
TURN_SECONDS = 160
MAX_ROUNDS = 10
MAX_HISTORY_ITEMS = 20
MAX_INPUT_CHARS = 60000
TOKEN_SCOPE = "https://ai.azure.com/.default"

INSTRUCTIONS = client_tools.INSTRUCTIONS + (
    " You run as a Foundry hosted agent with your own Entra identity, so the Playground can call your "
    "tools. Every create, train, retrain or inference call needs a plan that this user approved: call "
    "plan_run, show the user the use cases, run ids, data version and Azure writes from its result, and "
    "ask the user to reply exactly 'approve <approval_code>'. Only the user can approve; never say a plan "
    "is approved unless get_approval_status or a host note confirms it. Azure ML jobs take minutes: when "
    "a tool returns state 'running', report the job name and ask the user to check again later instead "
    "of repeating the call in the same turn. Calling a training or inference tool again resumes the same "
    "recorded job and never submits a duplicate. get_usecase_status only reads the shared receipts and "
    "never contacts Azure ML: when it shows training state 'submitted' or a pending_inference, call "
    "start_training, start_retraining or run_batch_inference again to check that job and finish it. A plan "
    "always covers both use cases, but operate only on "
    "the use case the user asked for in this conversation. If a step fails, report the error and stop; "
    "never continue with a step that depends on it (for example, never train before the use case was "
    "created successfully)."
)


class Busy(RuntimeError):
    """Another conversation holds the shared receipt lease."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _age(stamp: str | None, now: datetime) -> float:
    return (now - datetime.fromisoformat(stamp)).total_seconds() if stamp else float("inf")


def caller(user_key: str | None, conversation: str | None = None) -> dict:
    """Hashed platform user partition key (x-agent-user-id) and conversation chain; never raw ids."""
    def digest(value):
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32] if value else "local"

    return {"user": digest(user_key), "conversation": digest(conversation)}


# ---- configuration and sandbox layout ---------------------------------------------------------
def home() -> Path:
    """Writable state outside the deployed package; $HOME persists for the session."""
    candidates = [Path(os.environ["AIF49_HOME"])] if os.environ.get("AIF49_HOME") else []
    candidates += [Path.home() / ".aif49", Path(tempfile.gettempdir()) / "aif49"]
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved != TEMPLATE and not resolved.is_relative_to(TEMPLATE):
            return resolved
    raise RuntimeError("No writable folder outside the hosted package")


def hosted_config(bundle: Path = BUNDLE, root: Path | None = None) -> dict:
    """The bundled consumer configuration with sandbox paths; plans bind to it independently of where
    the sandbox places its home folder and package."""
    root = Path(root) if root is not None else home()
    bundle = Path(bundle)
    config = read_json(bundle / "config.json")
    config.update(ml_factory_root=str(root / "ml-factory"), evidence_root=str(root / "evidence"),
                  state_root=str(root / "state"), reviewed_rollout=str(bundle / "reviewed-rollout.json"),
                  factory_config=str(bundle / "factory-config.json"),
                  hosted_paths={"home": str(root), "bundle": str(bundle)})
    config["usecases"][AIR]["champion_receipts"] = str(bundle / "champion")
    return validate(config)


def install_bundle(bundle: Path, location) -> None:
    """Copy the reviewed scenarios and selection policy into the sandbox ML factory root."""
    source = bundle / "ml-factory"
    for path in sorted(item for item in source.rglob("*") if item.is_file()):
        target = location.ml_root / path.relative_to(source)
        if not target.is_file() or target.read_bytes() != path.read_bytes():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)


def state_prefix(config: dict) -> str:
    """agent-state below the M49 use-case root of the shared lake (the only lake area it rewrites)."""
    from azure_esml.domain_layer.shared_lake import SharedLake

    lake = SharedLake(config["aifactory"], config["environment"], config["shared_lake"]["prefix"])
    root = lake.use_case(f"{config['project_number']:03d}", CHURN)
    return f"{root.rstrip('/')}/agent-state/{config['owner']}/{config['version']}"


def mappings(location) -> dict[str, Path]:
    return {"state": location.state, f"esml/{CHURN}": location.esml(CHURN), f"esml/{AIR}": location.esml(AIR)}


def _skipped(relative: str) -> bool:
    parts = relative.split("/")
    return any(part in SKIP for part in parts[:-1]) or parts[-1].endswith(".tmp") or relative.startswith("../")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---- durable shared state -----------------------------------------------------------------------
class StateConflict(RuntimeError):
    """Another session changed a shared receipt that this session also changed; nothing was overwritten."""


class BlobState:
    """Mirror plans, approvals and receipts between the sandbox and the shared lake.

    Uploads are conditional on the ETag seen at pull (or create-only for new files), so a stale
    session can never overwrite another session's newer receipt. A local change that failed to upload
    stays dirty (journaled with its base ETag and intended digest): pull keeps it and the next push
    retries it. The runtime calls `barrier` before every Azure ML or lake mutation and wait: it renews
    the lease synchronously and makes the intents durable before the call, or blocks the call.
    """

    def __init__(self, container, prefix: str, roots: dict[str, Path], journal: Path | None = None):
        self.container = container
        self.prefix = prefix.strip("/") + "/"
        self.roots = {name: Path(root) for name, root in roots.items()}
        self.journal = Path(journal) if journal is not None else None
        self.remote: dict[str, tuple[str | None, str | None]] = {}
        self.dirty: dict[str, dict] = (read_json(self.journal).get("dirty", {})
                                       if self.journal is not None and self.journal.is_file() else {})
        self.lost = threading.Event()
        self._pushing = threading.Lock()
        self._renewing = threading.Lock()
        self._lease = None

    def _save(self) -> None:
        if self.journal is not None:
            write_json(self.journal, {"dirty": self.dirty})

    def _local(self):
        for name, root in self.roots.items():
            if not root.is_dir():
                continue
            for path in sorted(item for item in root.rglob("*") if item.is_file()):
                relative = path.relative_to(root).as_posix()
                if not _skipped(relative):
                    yield f"{name}/{relative}", path

    def pull(self) -> int:
        changed, remote = 0, {}
        for name, root in self.roots.items():
            base = f"{self.prefix}{name}/"
            for blob in self.container.list_blobs(name_starts_with=base, include=["metadata"]):
                relative = blob.name[len(base):]
                if not relative or _skipped(relative) or any(part in ("", ".", "..") for part in relative.split("/")):
                    continue
                if (getattr(blob, "metadata", None) or {}).get("hdi_isfolder") == "true" or (root / relative).is_dir():
                    continue  # a hierarchical-namespace (ADLS Gen2) directory entry, not a receipt
                key, etag = f"{name}/{relative}", getattr(blob, "etag", None)
                pending = self.dirty.get(key)
                if pending is not None and _etag(pending.get("base")) == _etag(etag):
                    remote[key] = (etag, None)  # remote unchanged: keep the local change; push retries it
                    continue
                data = self.container.download_blob(blob.name).readall()
                if pending is not None:
                    if _sha256(data) != pending.get("digest"):
                        raise StateConflict(f"{key} changed in the shared state while a local update was pending")
                    del self.dirty[key]  # the earlier upload landed before the journal was cleared
                    self._save()
                remote[key] = (etag, _sha256(data))
                target = root / relative
                if not target.is_file() or target.read_bytes() != data:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                    changed += 1
        self.remote = remote
        return changed

    def renew(self) -> None:
        """Synchronously renew the held lease; a failure marks the state lost."""
        if self._lease is None:
            return
        try:
            with self._renewing:
                self._lease.renew()
        except Exception as error:
            self.lost.set()
            raise StateConflict("The shared state lease was lost; no further Azure writes in this turn") from error

    def barrier(self) -> int:
        """Before an Azure write or wait: hold a fresh lease and make every local receipt durable."""
        if self.lost.is_set():
            raise StateConflict("The shared state lease was lost; no further Azure writes in this turn")
        self.renew()
        return self.push()

    def push(self) -> int:
        from azure.core import MatchConditions
        from azure.core.exceptions import ResourceExistsError, ResourceModifiedError

        with self._pushing:
            changed = 0
            for key, path in self._local():
                data = path.read_bytes()
                digest = _sha256(data)
                etag, known = self.remote.get(key, (None, None))
                if known == digest:
                    continue
                self.dirty[key] = {"base": etag, "digest": digest}
                self._save()
                blob = self.container.get_blob_client(self.prefix + key)
                try:
                    if etag is None:
                        result = blob.upload_blob(data, overwrite=False)
                    else:
                        result = blob.upload_blob(data, overwrite=True, etag=etag,
                                                  match_condition=MatchConditions.IfNotModified)
                except (ResourceExistsError, ResourceModifiedError) as error:
                    raise StateConflict(f"{key} was changed by another session; nothing was overwritten") from error
                self.remote[key] = ((result or {}).get("etag"), digest)
                del self.dirty[key]
                self._save()
                changed += 1
            return changed

    @contextlib.contextmanager
    def lock(self):
        from azure.core.exceptions import HttpResponseError

        blob = self.container.get_blob_client(self.prefix + "lock")
        with contextlib.suppress(HttpResponseError):
            blob.upload_blob(b"", overwrite=False)  # the lease blob is created once and never deleted
        try:
            lease = blob.acquire_lease(lease_duration=LEASE_SECONDS)
        except HttpResponseError as error:
            if getattr(error, "status_code", None) == 409:
                raise Busy("Another conversation is running an ML operation for these use cases; "
                           "ask again in a minute.") from None
            raise
        self.lost.clear()
        self._lease = lease
        stop = threading.Event()

        def renew():
            while not stop.wait(LEASE_SECONDS / 3):
                try:
                    self.renew()
                except StateConflict:  # an expired lease stops further Azure writes in this turn
                    return

        thread = threading.Thread(target=renew, name="aif49-lease", daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join(timeout=10)
            self._lease = None
            with contextlib.suppress(Exception):
                lease.release()


def _etag(value: str | None) -> str | None:
    return value.strip('"') if isinstance(value, str) else value


class Approvals:
    """Per-user pending and approved plans; approval comes only from the user's literal message."""

    def __init__(self, config: dict, clock=_now):
        self.config = config
        self.state = paths(config).state
        self.root = self.state / APPROVALS
        self.clock = clock

    def propose(self, plan_path: Path, digest: str, who: dict) -> dict:
        pending = {"plan": Path(plan_path).relative_to(self.state).as_posix(), "sha256": digest,
                   "approval_code": digest[:12], "proposed_at": self.clock().isoformat(), "caller": who}
        write_json(self.root / f"pending-{who['user']}.json", pending)
        return pending

    def approve(self, text: str, who: dict) -> str | None:
        """Return a host note when the user's message is an approval attempt, else None."""
        match = APPROVE.fullmatch(text or "")
        if not match:
            return None
        code = match.group(1).lower()
        pending_path = self.root / f"pending-{who['user']}.json"
        pending = read_json(pending_path) if pending_path.is_file() else None
        if pending is None or pending.get("approved_at"):
            return "The user tried to approve a plan, but this user has no pending plan. Offer plan_run."
        if _age(pending.get("proposed_at"), self.clock()) > PENDING_SECONDS:
            return "The user's pending plan expired after 30 minutes; nothing was approved. Offer plan_run."
        if not pending["sha256"].startswith(code):
            return "The user's approval code does not match their pending plan; nothing was approved."
        try:
            approved_plan(self.state / pending["plan"], pending["sha256"], self.config)
        except (ValueError, FileNotFoundError) as error:
            return f"The pending plan cannot be approved ({error}); create a new plan with plan_run."
        approved = {**pending, "approved_at": self.clock().isoformat(), "approved_by": "user-message",
                    "approved_in": who}
        write_json(self.root / "approved.json", approved)
        write_json(pending_path, approved)  # consumed; it can never be approved twice
        return (f"The user approved plan {pending['approval_code']} in their own message. It is now the active "
                "plan for 12 hours; continue with the request it covers.")

    def active(self, who: dict) -> tuple[dict | None, bool]:
        """The latest approved plan (readable by everyone) and whether this user may write with it."""
        record = self.root / "approved.json"
        if not record.is_file():
            return None, False
        approved = read_json(record)
        try:
            plan = approved_plan(self.state / approved["plan"], approved["sha256"], self.config)
        except (ValueError, FileNotFoundError):
            return None, False
        writable = (approved.get("caller", {}).get("user") == who["user"]
                    and _age(approved.get("approved_at"), self.clock()) <= ACTIVE_SECONDS)
        return plan, writable

    def status(self, who: dict) -> dict:
        now, result = self.clock(), {}
        pending_path = self.root / f"pending-{who['user']}.json"
        if pending_path.is_file():
            pending = read_json(pending_path)
            if not pending.get("approved_at") and _age(pending.get("proposed_at"), now) <= PENDING_SECONDS:
                result["pending"] = {"approval_code": pending["approval_code"], "proposed_at": pending["proposed_at"]}
        plan, writable = self.active(who)
        if plan is not None:
            approved = read_json(self.root / "approved.json")
            expires = datetime.fromisoformat(approved["approved_at"]) + timedelta(seconds=ACTIVE_SECONDS)
            result["approved"] = {"approval_code": approved["approval_code"], "approved_at": approved["approved_at"],
                                  "writes_allowed_for_this_user": writable, "writes_expire_at": expires.isoformat()}
            result["active_plan"] = {
                name: {key: entry[key] for key in ("model_name", "data_version", "train_run_id", "inference_run_id")}
                for name, entry in plan["usecases"].items()}
        return result


# ---- conversation ---------------------------------------------------------------------------------
def conversation(current: str, history: list) -> list[dict]:
    """Platform-provided text history only; historical content never becomes instructions."""
    if len(current) > MAX_INPUT_CHARS:
        raise ValueError(f"Input exceeds {MAX_INPUT_CHARS} characters.")
    result = []
    for item in (history or [])[-MAX_HISTORY_ITEMS:]:
        content = item.get("content") if isinstance(item, dict) else getattr(item, "content", None)
        for part in content or []:
            kind = part.get("type") if isinstance(part, dict) else getattr(part, "type", None)
            text = part.get("text") if isinstance(part, dict) else getattr(part, "text", None)
            role = {"input_text": "user", "output_text": "assistant"}.get(kind)
            if role and isinstance(text, str) and text:
                result.append({"role": role, "content": text})
    result.append({"role": "user", "content": current})
    total = sum(len(item["content"]) for item in result)
    while len(result) > 1 and total > MAX_INPUT_CHARS:
        total -= len(result.pop(0)["content"])
    return result


def tool_definitions() -> list[dict]:
    return client_tools.tool_definitions() + [
        {"type": "function", "name": "plan_run", "strict": True,
         "description": ("Propose a new plan (model names, lake paths, run ids and Azure writes) for the two use "
                         "cases. Writes nothing to Azure ML; the user must approve it before any operation."),
         "parameters": {"type": "object", "additionalProperties": False, "required": ["fresh_data"],
                        "properties": {"fresh_data": {
                            "type": "boolean",
                            "description": "True publishes the next synthetic churn data version (from scratch)."}}}},
        {"type": "function", "name": "get_approval_status", "strict": True,
         "description": "Show this user's pending plan and the approved plan with its run ids and expiry.",
         "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}},
    ]


def sync_credential():
    """The sandbox's agent identity (workload/managed identity); developer credentials are excluded."""
    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential(
        exclude_environment_credential=True, exclude_interactive_browser_credential=True,
        exclude_shared_token_cache_credential=True, exclude_visual_studio_code_credential=True,
        exclude_cli_credential=True, exclude_powershell_credential=True, exclude_developer_cli_credential=True,
    )


class HostedAgent:
    """One sandbox process: guarded tools, shared receipts and the model's function-call loop."""

    def __init__(self, *, config: dict, credential, container, client, bundle: Path = BUNDLE,
                 runtime_factory=MLRuntime, clock=time.monotonic, approvals_clock=_now):
        self.config = config
        self.location = paths(config)
        self.credential = credential
        self.client = client
        self.bundle = Path(bundle)
        self.runtime_factory = runtime_factory
        self.clock = clock
        self.approvals = Approvals(config, clock=approvals_clock)
        self.state = BlobState(container, state_prefix(config), mappings(self.location),
                               journal=Path(config["state_root"]) / "sync-journal.json")
        install_bundle(self.bundle, self.location)

    @classmethod
    def from_environment(cls) -> "HostedAgent":
        from azure.identity import get_bearer_token_provider
        from azure.storage.blob import ContainerClient
        from openai import OpenAI

        config = hosted_config()
        endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "").rstrip("/")
        if endpoint != config["project_endpoint"]:
            raise ValueError("FOUNDRY_PROJECT_ENDPOINT differs from the bundled project endpoint")
        credential = sync_credential()
        lake = config["shared_lake"]
        container = ContainerClient(lake["account_url"], lake["container"], credential=credential)
        client = OpenAI(base_url=endpoint + "/openai/v1", timeout=90, max_retries=1,
                        api_key=get_bearer_token_provider(credential, TOKEN_SCOPE))
        return cls(config=config, credential=credential, container=container, client=client)

    def runtime(self, plan: dict | None, writable: bool):
        if plan is not None:
            factory.write_rollout(self.config, self.location, plan)
        return self.runtime_factory(self.config, plan=plan, apply=writable, allow_paid=writable,
                                    credential=self.credential, wait_seconds=WAIT_SECONDS, hosted=True,
                                    barrier=self.state.barrier)

    def turn(self, text: str, history: list | None = None, *, user: str | None = None,
             conversation_id: str | None = None) -> str:
        """One user turn under the shared lease; receipts are pulled first and pushed at every barrier."""
        deadline = self.clock() + TURN_SECONDS
        who = caller(user, conversation_id)
        try:
            with self.state.lock():
                self.state.pull()
                answer = None
                try:
                    note = self.approvals.approve(text, who)
                    plan, writable = self.approvals.active(who)
                    runtime = self.runtime(plan, writable)
                    answer = self._converse(runtime, conversation(text, history or []), note, deadline, who, writable)
                finally:
                    try:
                        self.state.push()
                    except Exception as error:
                        if answer is not None:
                            answer += ("\n\nWarning: the shared receipts could not be saved "
                                       f"({redact(f'{type(error).__name__}: {error}')[:300]}); ask me again before "
                                       "starting anything new.")
                return answer
        except (Busy, StateConflict) as error:
            return str(error)

    def dispatch(self, runtime, name: str, arguments: dict, who: dict, writable: bool) -> dict:
        try:
            if name == "plan_run":
                if set(arguments) != {"fresh_data"} or type(arguments["fresh_data"]) is not bool:
                    raise ValueError("plan_run needs only the boolean fresh_data")
                plan = build_plan(self.config, fresh=arguments["fresh_data"])
                path, digest = save_plan(self.config, plan, unique=True)
                pending = self.approvals.propose(path, digest, who)
                return {"ok": True, "result": redact({
                    "approval_code": pending["approval_code"],
                    "ask_user_to_reply": f"approve {pending['approval_code']}",
                    "approval_expires_after_minutes": PENDING_SECONDS // 60,
                    "data_date_utc": plan["data_date_utc"], "azure_writes": plan["azure_writes"],
                    "never": plan["never"],
                    "usecases": {usecase: {key: entry[key] for key in ("model_name", "data_version", "train_run_id",
                                                                       "inference_run_id", "compute")}
                                 for usecase, entry in plan["usecases"].items()}})}
            if name == "get_approval_status":
                if arguments:
                    raise ValueError("get_approval_status takes no arguments")
                return {"ok": True, "result": redact(self.approvals.status(who))}
            if name in MUTATING and not writable:
                return {"ok": False, "error": ("No plan approved by this user is active (missing, expired after 12 "
                                               "hours, or approved by another user). Call plan_run and ask the "
                                               "user to approve it.")}
            return client_tools.dispatch(runtime, name, arguments)
        except StateConflict as error:
            self.state.lost.set()  # stop: another session owns newer receipts
            return {"ok": False, "error": redact(str(error))[:2000]}
        except Exception as error:  # report every failure to the model as data, never crash the turn
            return {"ok": False, "error": redact(f"{type(error).__name__}: {error}")[:2000]}

    def _converse(self, runtime, messages: list[dict], note: str | None, deadline: float, who: dict,
                  writable: bool) -> str:
        instructions = INSTRUCTIONS + (f"\nHost note (from the platform, not from the user): {note}" if note else "")
        items, seen = list(messages), set()
        for _ in range(MAX_ROUNDS):
            response = self.client.responses.create(
                model=self.config["model_deployment"], instructions=instructions, input=items,
                tools=tool_definitions(), store=False, include=["reasoning.encrypted_content"])
            output = [client_tools._object(item) for item in response.output]
            calls = [item for item in output if item.get("type") == "function_call"]
            if not calls:
                return response.output_text or "I have no answer for that."
            items.extend(output)
            for call in calls:
                call_id = call.get("call_id")
                if not isinstance(call_id, str) or not call_id or call_id in seen:
                    raise RuntimeError("Invalid or repeated tool call identifier")
                seen.add(call_id)
                if self.state.lost.is_set():
                    result = {"ok": False, "error": ("The shared state lease was lost or another session changed the "
                                                     "receipts; ask the user to try again.")}
                elif self.clock() > deadline:
                    result = {"ok": False, "error": "This turn's time budget is used up; ask the user to continue."}
                else:
                    try:
                        arguments = client_tools._arguments(call.get("arguments"))
                    except ValueError as error:
                        arguments, result = {}, {"ok": False, "error": str(error)}
                    else:
                        result = self.dispatch(runtime, call.get("name"), arguments, who, writable)
                    try:
                        self.state.push()  # write-through after every tool call
                    except StateConflict:
                        self.state.lost.set()
                    except Exception:  # retried at the next barrier, which blocks any Azure write until it succeeds
                        pass
                items.append({"type": "function_call_output", "call_id": call_id,
                              "output": json.dumps(result, sort_keys=True, default=str)})
        return "I reached this turn's tool-call budget; ask me to continue."
