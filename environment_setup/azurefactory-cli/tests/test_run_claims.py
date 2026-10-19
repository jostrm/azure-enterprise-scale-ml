from __future__ import annotations

import io
import json
import subprocess
from datetime import datetime, timedelta, timezone
from email.message import Message
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from azurefactory.cli import build_parser, main
from azurefactory.client import canonical_json_hash


API_KEY = "private-api-key"
BASE = "http://127.0.0.1:8765"
ENDPOINT = "/api/v1/operations/reconcile-run-claim"
FOLDER = r"C:\consumer\azurefactory"
FACTORY = "11d7fc57-56ee-46d6-919c-3a3d4c8cbb4b"
RUN = "dfc24ea3-3a0d-4dc4-b0e6-d2d6fb5304ff"
JOB = "71f481b0-846f-4ee8-96c5-ec006d1468bc"
CONFIRMATION = "55555555-5555-4555-8555-555555555555"
REPOSITORY = "https://github.com/org/consumer"
PHRASE = "RELEASE " + RUN
HEAD, NEW_HEAD = "a" * 40, "b" * 40
SCOPES = ["/subscriptions/33333333-3333-4333-8333-333333333333/resourcegroups/rg-common",
          "/subscriptions/33333333-3333-4333-8333-333333333333/resourcegroups/rg-project001"]


def preview():
    return {
        "contract_version": 1, "capabilities": ["reconcile-run-claim-v1"], "operation_mode": "provider-state",
        "can_execute": True, "blockers": [], "azure_writes": False,
        "confirmation_id": CONFIRMATION, "preview_hash": "c" * 64,
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        "confirmation_phrase": PHRASE, "folder": FOLDER, "factory_id": FACTORY, "job_id": JOB, "run_id": RUN,
        "operation": "create-scaleset", "repository": REPOSITORY,
        "state_ref": "refs/heads/aifactory-state/single-writer-v1", "provider_head": HEAD,
        "active_claim": {"kind": "run", "run_id": RUN, "manifest_hash": "d" * 64, "scopes": list(SCOPES)},
        "run_receipt": {"status": "reconciliation-required", "error_code": "scoped-github-run-failed",
                        "mutation_started": True},
        "worker_receipt": {"status": "reconciliation-required", "error_code": "remote-request-unverified",
                           "mutation_started": True},
        "remote_run": {"kind": "gha", "run_id": 36489088021, "pipeline_id": None, "status": "completed",
                       "conclusion": "failure", "url": REPOSITORY + "/actions/runs/36489088021"},
        "other_runs_in_progress": 0, "records_preserved": 4,
        "audit_record": "claim-reconciliations/" + RUN + "/" + CONFIRMATION + ".json",
        "effects": ["One compare-and-swap sets active to null; it is never retried or forced."],
        "warnings": ["Review what the failed run changed in Azure first."],
    }


def released():
    return {"contract_version": 1, "status": "released", "folder": FOLDER, "factory_id": FACTORY, "run_id": RUN,
            "repository": REPOSITORY, "state_ref": "refs/heads/aifactory-state/single-writer-v1",
            "previous_head": HEAD, "head": NEW_HEAD,
            "audit_record": "claim-reconciliations/" + RUN + "/" + CONFIRMATION + ".json",
            "records_preserved": 4, "message": "Released."}


@pytest.fixture
def transport(monkeypatch):
    state = SimpleNamespace(records=[], preview=preview(), result=released(), error=None)

    class Response(io.BytesIO):
        def __init__(self, value):
            super().__init__(json.dumps(value).encode())
            self.headers = Message()
            self.headers["Content-Type"] = "application/json"

    class Opener:
        def open(self, req, timeout):
            state.records.append({"url": req.full_url, "method": req.method,
                                  "body": json.loads(req.data) if req.data else None,
                                  "headers": dict(req.header_items())})
            if state.error:
                raise state.error
            return Response(state.preview if req.full_url.endswith("/prepare") else state.result)

    def no_process(*args, **kwargs):
        pytest.fail("Run claim reconciliation must not invoke any local process, az or gh.")

    monkeypatch.setattr("azurefactory.client.build_opener", lambda *args: Opener())
    monkeypatch.setattr("azurefactory.cli.sys.stdin", io.StringIO())
    monkeypatch.setattr(subprocess, "run", no_process)
    monkeypatch.setattr(subprocess, "Popen", no_process)
    monkeypatch.delenv("AIFACTORY_API_KEY", raising=False)
    return state


def invoke(*args):
    return main(["--api-url", BASE, "--api-key", API_KEY, "reconcile-run-claim", *args])


def prepare(tmp_path, *args):
    return invoke("prepare", "--folder", FOLDER, "--factory-id", FACTORY, "--run-id", RUN,
                  "--save-receipt", str(tmp_path / "receipt.json"), *args)


def confirm(tmp_path, *args):
    return invoke("confirm", "--receipt", str(tmp_path / "receipt.json"), *args)


def make_receipt(tmp_path, transport, capsys):
    assert prepare(tmp_path) == 0
    transport.records.clear()
    capsys.readouterr()


def test_prepare_saves_a_bound_review_and_never_confirms(tmp_path, transport, capsys):
    assert prepare(tmp_path) == 0
    assert len(transport.records) == 1
    record = transport.records[0]
    assert record["url"] == BASE + ENDPOINT + "/prepare" and record["method"] == "POST"
    assert record["headers"]["X-api-key"] == API_KEY
    assert record["body"] == {"contract_version": 1, "folder": FOLDER, "factory_id": FACTORY, "run_id": RUN}
    receipt = json.loads((tmp_path / "receipt.json").read_text())
    assert receipt["purpose"] == "reconcile-run-claim-confirm"
    assert receipt["operation"] == "reconcile-run-claim"
    assert receipt["preview_hash"] == canonical_json_hash(receipt["preview"])
    output = capsys.readouterr()
    assert json.loads(output.out) == transport.preview
    assert "Nothing has been changed" in output.err
    for value in (RUN, REPOSITORY, "36489088021", "reconciliation-required", "claim-reconciliations/", SCOPES[0]):
        assert value in output.err


@pytest.mark.parametrize(("flag", "value"), [("--run-id", "not-a-uuid"), ("--factory-id", "x"), ("--folder", " ")])
def test_invalid_request_never_reaches_the_api(tmp_path, transport, flag, value):
    args = {"--folder": FOLDER, "--factory-id": FACTORY, "--run-id": RUN}
    args[flag] = value
    assert invoke("prepare", *[item for pair in args.items() for item in pair],
                  "--save-receipt", str(tmp_path / "receipt.json")) == 2
    assert not transport.records and not (tmp_path / "receipt.json").exists()


def nested(path, value):
    def change(p):
        target = p
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
    return change


@pytest.mark.parametrize("change", [
    nested(["capabilities"], []), nested(["operation_mode"], "runtime"), nested(["contract_version"], True),
    nested(["folder"], r"C:\another\azurefactory"), nested(["factory_id"], CONFIRMATION),
    nested(["run_id"], CONFIRMATION), nested(["confirmation_id"], "not-a-uuid"), nested(["preview_hash"], "x"),
    nested(["confirmation_phrase"], "yes"), nested(["confirmation_phrase"], "RELEASE " + CONFIRMATION),
    nested(["azure_writes"], True), nested(["active_claim", "kind"], "enrollment"),
    nested(["active_claim", "run_id"], CONFIRMATION), nested(["active_claim", "scopes"], []),
    nested(["run_receipt", "status"], "running"), nested(["worker_receipt", "status"], "running"),
    nested(["remote_run", "status"], "in_progress"), nested(["remote_run", "kind"], "jenkins"),
    nested(["other_runs_in_progress"], 1), nested(["audit_record"], "runs/" + RUN + ".json"),
    nested(["state_ref"], "refs/heads/main"), nested(["provider_head"], "head"),
    nested(["effects"], None), nested(["warnings"], [""]), nested(["repository"], ""),
])
def test_unsafe_or_changed_preview_never_saves_an_approvable_receipt(tmp_path, transport, change):
    change(transport.preview)
    assert prepare(tmp_path) == 2
    assert not (tmp_path / "receipt.json").exists()
    assert len(transport.records) == 1


def test_blocked_server_review_is_reported_and_not_saved(tmp_path, transport, capsys):
    transport.error = HTTPError(BASE + ENDPOINT + "/prepare", 409, "Conflict", {}, io.BytesIO(json.dumps(
        {"detail": "Run claim reconciliation blocked: the GitHub Actions run is in_progress"}).encode()))
    assert prepare(tmp_path) != 0
    assert "in_progress" in capsys.readouterr().err
    assert not (tmp_path / "receipt.json").exists()


def test_nontty_exact_phrase_and_yes_sends_one_bound_confirmation(tmp_path, transport, capsys):
    make_receipt(tmp_path, transport, capsys)
    assert confirm(tmp_path, "--yes", "--confirmation-phrase", PHRASE) == 0
    assert len(transport.records) == 1
    assert transport.records[0]["url"] == BASE + ENDPOINT + "/confirm"
    assert transport.records[0]["body"] == {"contract_version": 1, "folder": FOLDER, "confirmation_id": CONFIRMATION,
                                            "preview_hash": "c" * 64, "confirmation_phrase": PHRASE}
    assert json.loads(capsys.readouterr().out)["status"] == "released"


@pytest.mark.parametrize("flags", [
    (), ("--yes",), ("--confirmation-phrase", PHRASE), ("--yes", "--confirmation-phrase", "yes"),
    ("--yes", "--confirmation-phrase", PHRASE.lower()), ("--yes", "--confirmation-phrase", PHRASE + " "),
])
def test_nontty_missing_or_wrong_approval_never_sends(tmp_path, transport, capsys, flags):
    make_receipt(tmp_path, transport, capsys)
    assert confirm(tmp_path, *flags) == 2
    assert not transport.records


@pytest.mark.parametrize(("answers", "expected"), [
    (["no"], 3), ([""], 3), ([], 3), (["yes"], 3), (["yes", "yes"], 2), (["yes", PHRASE], 0),
])
def test_interactive_review_comes_before_the_questions(tmp_path, transport, capsys, monkeypatch, answers, expected):
    make_receipt(tmp_path, transport, capsys)
    monkeypatch.setattr("azurefactory.cli.sys.stdin", SimpleNamespace(isatty=lambda: True))
    responses, prompts = iter(answers), []

    def answer():
        output = capsys.readouterr()
        prompts.append(output.err)
        if len(prompts) == 1:
            assert RUN in output.err and REPOSITORY in output.err and not transport.records
        else:
            assert "Type the exact confirmation phrase" in output.err
        try:
            return next(responses)
        except StopIteration:
            raise EOFError()

    monkeypatch.setattr("builtins.input", answer)
    assert confirm(tmp_path, "--yes") == expected
    assert len(transport.records) == (1 if expected == 0 else 0)


@pytest.mark.parametrize(("field", "value"), [
    ("status", "uncertain"), ("run_id", CONFIRMATION), ("contract_version", 2), ("head", HEAD),
    ("audit_record", "claim-reconciliations/other.json"), ("folder", r"C:\another\azurefactory"),
])
def test_an_unexpected_confirmation_result_is_a_failure_not_success(tmp_path, transport, capsys, field, value):
    make_receipt(tmp_path, transport, capsys)
    transport.result[field] = value
    assert confirm(tmp_path, "--yes", "--confirmation-phrase", PHRASE) == 5
    assert len(transport.records) == 1


@pytest.mark.parametrize("status", [401, 403, 404, 405, 409, 422, 500])
@pytest.mark.parametrize("action", ["prepare", "confirm"])
def test_http_errors_never_fallback_or_retry(tmp_path, transport, capsys, status, action):
    if action == "confirm":
        make_receipt(tmp_path, transport, capsys)
    transport.error = HTTPError(BASE + ENDPOINT + "/" + action, status, "failed", {},
                                io.BytesIO(json.dumps({"detail": API_KEY}).encode()))
    code = prepare(tmp_path) if action == "prepare" else confirm(tmp_path, "--yes", "--confirmation-phrase", PHRASE)
    assert code != 0
    assert len(transport.records) == 1
    output = capsys.readouterr()
    assert API_KEY not in output.out + output.err
    if status in (404, 405):
        assert "reconcile-run-claim" in output.err and "no fallback" in output.err


def test_the_operations_own_not_found_is_not_mistaken_for_a_missing_route(tmp_path, transport, capsys):
    detail = "Run claim reconciliation blocked: no lifecycle job of this authenticated caller dispatched that run."
    transport.error = HTTPError(BASE + ENDPOINT + "/prepare", 404, "Not Found", {},
                                io.BytesIO(json.dumps({"detail": detail}).encode()))
    assert prepare(tmp_path) != 0
    error = capsys.readouterr().err
    assert "authenticated caller" in error and "no fallback" not in error


def test_timeout_confirmation_is_unknown_and_never_retried(tmp_path, transport, capsys):
    make_receipt(tmp_path, transport, capsys)
    transport.error = TimeoutError()
    assert confirm(tmp_path, "--yes", "--confirmation-phrase", PHRASE) == 4
    assert len(transport.records) == 1
    assert "outcome is unknown" in capsys.readouterr().err


def test_receipt_for_another_operation_is_refused_without_calling_the_api(tmp_path, transport, capsys):
    make_receipt(tmp_path, transport, capsys)
    path = tmp_path / "receipt.json"
    receipt = json.loads(path.read_text())
    receipt["purpose"] = "delete-aifactory-confirm"
    path.write_text(json.dumps(receipt))
    assert confirm(tmp_path, "--yes", "--confirmation-phrase", PHRASE) == 2
    assert not transport.records


def test_existing_receipt_prevents_the_prepare_call(tmp_path, transport):
    (tmp_path / "receipt.json").write_text("{}")
    assert prepare(tmp_path) == 2
    assert not transport.records


def test_sdk_methods_use_only_the_named_routes(transport):
    from azurefactory.client import AzureFactoryClient
    api = AzureFactoryClient(BASE, API_KEY, 5)
    assert api.reconcile_run_claim_prepare({"contract_version": 1, "folder": FOLDER, "factory_id": FACTORY,
                                            "run_id": RUN}) == transport.preview
    assert api.reconcile_run_claim_confirm(folder=FOLDER, confirmation_id=CONFIRMATION, preview_hash="c" * 64,
                                           confirmation_phrase=PHRASE) == transport.result
    assert [record["url"] for record in transport.records] == [BASE + ENDPOINT + "/prepare", BASE + ENDPOINT + "/confirm"]


def test_command_help_uses_plain_language():
    parser = build_parser()
    text = parser._subparsers._group_actions[0].choices["reconcile-run-claim"].format_help()
    assert "claim" in text and "failed run" in text
