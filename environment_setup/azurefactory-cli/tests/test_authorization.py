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
ENDPOINT = "/api/v1/operations/authorize-deletion"
FOLDER = r"C:\consumer\azurefactory"
FACTORY = "11d7fc57-56ee-46d6-919c-3a3d4c8cbb4b"
FACTORY_KEY = "ai-aif-130"
CONFIRMATION = "55555555-5555-4555-8555-555555555555"
OTHER = "66666666-6666-4666-8666-666666666666"
REPOSITORY = "https://github.com/org/consumer"
STATE_REF = "refs/heads/aifactory-state/single-writer-v1"
HEAD, NEW_HEAD = "a" * 40, "b" * 40
SCOPES = ["/subscriptions/33333333-3333-4333-8333-333333333333/resourcegroups/rg-common",
          "/subscriptions/33333333-3333-4333-8333-333333333333/resourcegroups/rg-project001"]
PHRASES = {"allow": "ALLOW DELETE " + FACTORY_KEY, "revoke": "REVOKE DELETE " + FACTORY_KEY}


def preview(mode="allow"):
    return {
        "contract_version": 1, "capabilities": ["authorize-deletion-v1"], "operation_mode": "provider-state",
        "azure_writes": False, "can_execute": True, "folder": FOLDER, "factory_id": FACTORY, "mode": mode,
        "repository": REPOSITORY, "state_ref": STATE_REF, "provider_head": HEAD, "scopes": list(SCOPES),
        "enrollment_revision": {"from": 3, "to": 4},
        "coordination_hash": {"from": "d" * 64, "to": "e" * 64},
        "bindings": ["gha"],
        "warnings": ["Deletion permission lets a reviewed delete-aifactory run remove these resource groups."],
        "blockers": [],
        "confirmation_id": CONFIRMATION, "preview_hash": "c" * 64,
        "confirmation_phrase": PHRASES[mode],
        "audit_record": "deletion-authorizations/" + FACTORY + "/" + CONFIRMATION + ".json",
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
    }


def result(mode="allow"):
    return {"contract_version": 1, "status": "authorized" if mode == "allow" else "revoked",
            "folder": FOLDER, "factory_id": FACTORY, "repository": REPOSITORY, "state_ref": STATE_REF,
            "previous_head": HEAD, "head": NEW_HEAD,
            "audit_record": "deletion-authorizations/" + FACTORY + "/" + CONFIRMATION + ".json",
            "bindings_updated": ["gha"], "message": "Deletion permission updated."}


@pytest.fixture
def transport(monkeypatch):
    state = SimpleNamespace(records=[], preview=preview(), result=result(), error=None)

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
        pytest.fail("Deletion authorization must not invoke any local process, az or gh.")

    monkeypatch.setattr("azurefactory.client.build_opener", lambda *args: Opener())
    monkeypatch.setattr("azurefactory.cli.sys.stdin", io.StringIO())
    monkeypatch.setattr(subprocess, "run", no_process)
    monkeypatch.setattr(subprocess, "Popen", no_process)
    monkeypatch.delenv("AIFACTORY_API_KEY", raising=False)
    return state


def invoke(*args):
    return main(["--api-url", BASE, "--api-key", API_KEY, "authorize-deletion", *args])


def prepare(tmp_path, *args, mode="allow"):
    return invoke("prepare", "--folder", FOLDER, "--factory-id", FACTORY, "--mode", mode,
                  "--save-receipt", str(tmp_path / "receipt.json"), *args)


def confirm(tmp_path, *args):
    return invoke("confirm", "--receipt", str(tmp_path / "receipt.json"), *args)


def make_receipt(tmp_path, transport, capsys, mode="allow"):
    transport.preview, transport.result = preview(mode), result(mode)
    assert prepare(tmp_path, mode=mode) == 0
    transport.records.clear()
    capsys.readouterr()


@pytest.mark.parametrize("mode", ["allow", "revoke"])
def test_prepare_saves_a_bound_review_and_never_confirms(tmp_path, transport, capsys, mode):
    transport.preview = preview(mode)
    assert prepare(tmp_path, mode=mode) == 0
    assert len(transport.records) == 1
    record = transport.records[0]
    assert record["url"] == BASE + ENDPOINT + "/prepare" and record["method"] == "POST"
    assert record["headers"]["X-api-key"] == API_KEY
    assert record["body"] == {"contract_version": 1, "folder": FOLDER, "factory_id": FACTORY, "mode": mode}
    receipt = json.loads((tmp_path / "receipt.json").read_text())
    assert receipt["purpose"] == "authorize-deletion-confirm"
    assert receipt["operation"] == "authorize-deletion"
    assert receipt["preview_hash"] == canonical_json_hash(receipt["preview"])
    output = capsys.readouterr()
    assert json.loads(output.out) == transport.preview
    assert "Nothing has been changed" in output.err
    for value in (FACTORY, REPOSITORY, PHRASES[mode], "deletion-authorizations/", SCOPES[0], STATE_REF):
        assert value in output.err


@pytest.mark.parametrize(("flag", "value"), [("--factory-id", "x"), ("--folder", " "), ("--mode", "Allow"),
                                             ("--mode", "delete")])
def test_invalid_request_never_reaches_the_api(tmp_path, transport, flag, value):
    args = {"--folder": FOLDER, "--factory-id": FACTORY, "--mode": "allow"}
    args[flag] = value
    assert invoke("prepare", *[item for pair in args.items() for item in pair],
                  "--save-receipt", str(tmp_path / "receipt.json")) == 2
    assert not transport.records and not (tmp_path / "receipt.json").exists()


def change(field, value):
    def apply(p):
        if value is KeyError:
            del p[field]
        else:
            p[field] = value
    return apply


@pytest.mark.parametrize("unsafe", [
    change("capabilities", []), change("capabilities", ["reconcile-run-claim-v1"]),
    change("operation_mode", "runtime"), change("contract_version", True), change("contract_version", 2),
    change("azure_writes", True), change("azure_writes", None), change("azure_writes", KeyError),
    change("folder", r"C:\another\azurefactory"), change("factory_id", OTHER), change("mode", "revoke"),
    change("confirmation_id", "not-a-uuid"), change("preview_hash", "x"),
    change("confirmation_phrase", "yes"), change("confirmation_phrase", "REVOKE DELETE " + FACTORY_KEY),
    change("confirmation_phrase", "ALLOW DELETE"), change("confirmation_phrase", "ALLOW DELETE " + FACTORY),
    change("confirmation_phrase", "allow delete " + FACTORY_KEY),
    change("confirmation_phrase", "ALLOW DELETE " + FACTORY_KEY + " "),
    change("audit_record", "deletion-authorizations/" + OTHER + "/" + CONFIRMATION + ".json"),
    change("state_ref", "refs/heads/main"), change("provider_head", "head"), change("repository", ""),
    change("scopes", None), change("scopes", [""]),
    change("enrollment_revision", None), change("enrollment_revision", {"to": 4}),
    change("coordination_hash", {"from": "d" * 64}),
    change("bindings", None), change("bindings", {"gha": 1}), change("bindings", ["github"]),
    change("bindings", ["gha", "gha"]), change("can_execute", KeyError), change("can_execute", "true"),
    change("enrollment_revision", {"from": 3, "to": 3}), change("coordination_hash", {"from": "d" * 64, "to": "d" * 64}),
    change("repository", None), change("provider_head", None), change("warnings", None), change("warnings", [""]),
    change("blockers", None), change("expires_at", ""),
])
def test_unsafe_or_changed_preview_never_saves_an_approvable_receipt(tmp_path, transport, capsys, unsafe):
    unsafe(transport.preview)
    assert prepare(tmp_path) == 2
    assert not (tmp_path / "receipt.json").exists()
    assert len(transport.records) == 1
    assert "Nothing was authorized" in capsys.readouterr().err


def test_a_preview_with_blockers_is_reported_and_not_saved(tmp_path, transport, capsys):
    transport.preview.update(can_execute=False,
                             blockers=["The enrollment has an active run claim; reconcile it first."])
    assert prepare(tmp_path) == 3
    assert not (tmp_path / "receipt.json").exists()
    assert "active run claim" in capsys.readouterr().err


@pytest.mark.parametrize("can_execute,blockers", [(False, []), (True, ["Nothing to change."])])
def test_can_execute_that_disagrees_with_blockers_is_never_saved(tmp_path, transport, capsys, can_execute, blockers):
    transport.preview.update(can_execute=can_execute, blockers=blockers)
    assert prepare(tmp_path) == 2
    assert not (tmp_path / "receipt.json").exists()


def test_a_preview_blocked_before_reading_the_provider_is_reported_not_rejected(tmp_path, transport, capsys):
    # Pink 68d5e8e: Blob coordination (or no binding) blocks before any provider read, so the
    # repository, head and every {from,to} value are null.
    transport.preview.update(
        can_execute=False, repository=None, provider_head=None, scopes=[], bindings=[],
        enrollment_revision={"from": None, "to": None}, coordination_hash={"from": None, "to": None},
        blockers=["Blob-coordinated factories are not supported yet; nothing was changed."])
    assert prepare(tmp_path) == 3
    assert not (tmp_path / "receipt.json").exists()
    assert "Blob-coordinated" in capsys.readouterr().err


def repair(p):
    # Pink 68d5e8e: only the local binding save failed; the next prepare repairs just the binding.
    p.update(scopes=[], enrollment_revision={"from": 4, "to": 4}, coordination_hash={"from": "e" * 64, "to": "e" * 64},
             audit_record="deletion-authorizations/" + FACTORY + "/" + OTHER + ".json")
    return p


def test_a_binding_repair_review_reuses_its_audit_record_and_keeps_the_head(tmp_path, transport, capsys):
    repair(transport.preview)
    transport.result.update(head=HEAD, audit_record=transport.preview["audit_record"])
    assert prepare(tmp_path) == 0
    transport.records.clear()
    capsys.readouterr()
    assert confirm(tmp_path, "--yes", "--confirmation-phrase", PHRASES["allow"]) == 0
    assert json.loads(capsys.readouterr().out)["head"] == HEAD


@pytest.mark.parametrize("unsafe", [
    change("bindings", []), change("audit_record", "deletion-authorizations/" + OTHER + "/" + OTHER + ".json"),
    change("enrollment_revision", {"from": 4, "to": 5}),
])
def test_a_binding_repair_review_must_name_bindings_and_its_own_factory_record(tmp_path, transport, capsys, unsafe):
    unsafe(repair(transport.preview))
    assert prepare(tmp_path) == 2
    assert not (tmp_path / "receipt.json").exists()


def test_a_binding_repair_result_that_moves_the_head_is_a_failure(tmp_path, transport, capsys):
    repair(transport.preview)
    transport.result.update(audit_record=transport.preview["audit_record"])
    assert prepare(tmp_path) == 0
    capsys.readouterr()
    assert confirm(tmp_path, "--yes", "--confirmation-phrase", PHRASES["allow"]) == 5


@pytest.mark.parametrize("mode", ["allow", "revoke"])
def test_nontty_exact_phrase_and_yes_sends_one_bound_confirmation(tmp_path, transport, capsys, mode):
    make_receipt(tmp_path, transport, capsys, mode)
    assert confirm(tmp_path, "--yes", "--confirmation-phrase", PHRASES[mode]) == 0
    assert len(transport.records) == 1
    assert transport.records[0]["url"] == BASE + ENDPOINT + "/confirm"
    assert transport.records[0]["body"] == {"contract_version": 1, "folder": FOLDER, "confirmation_id": CONFIRMATION,
                                            "preview_hash": "c" * 64, "confirmation_phrase": PHRASES[mode]}
    assert json.loads(capsys.readouterr().out)["status"] == ("authorized" if mode == "allow" else "revoked")


@pytest.mark.parametrize("flags", [
    (), ("--yes",), ("--confirmation-phrase", PHRASES["allow"]), ("--yes", "--confirmation-phrase", "yes"),
    ("--yes", "--confirmation-phrase", PHRASES["revoke"]),
    ("--yes", "--confirmation-phrase", PHRASES["allow"].lower()),
    ("--yes", "--confirmation-phrase", PHRASES["allow"] + " "),
])
def test_nontty_missing_or_wrong_approval_never_sends(tmp_path, transport, capsys, flags):
    make_receipt(tmp_path, transport, capsys)
    assert confirm(tmp_path, *flags) == 2
    assert not transport.records


@pytest.mark.parametrize(("answers", "expected"), [
    (["no"], 3), ([""], 3), ([], 3), (["yes"], 3), (["yes", "yes"], 2), (["yes", PHRASES["allow"]], 0),
])
def test_interactive_review_comes_before_the_questions(tmp_path, transport, capsys, monkeypatch, answers, expected):
    make_receipt(tmp_path, transport, capsys)
    monkeypatch.setattr("azurefactory.cli.sys.stdin", SimpleNamespace(isatty=lambda: True))
    responses, prompts = iter(answers), []

    def answer():
        output = capsys.readouterr()
        prompts.append(output.err)
        if len(prompts) == 1:
            assert FACTORY in output.err and REPOSITORY in output.err and not transport.records
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
    ("status", "revoked"), ("status", "uncertain"), ("factory_id", OTHER), ("contract_version", 2),
    ("head", HEAD), ("previous_head", NEW_HEAD), ("state_ref", "refs/heads/main"),
    ("audit_record", "deletion-authorizations/other.json"), ("folder", r"C:\another\azurefactory"),
    ("repository", "https://github.com/org/other"), ("bindings_updated", ["ado"]), ("bindings_updated", None),
])
def test_an_unexpected_confirmation_result_is_a_failure_not_success(tmp_path, transport, capsys, field, value):
    make_receipt(tmp_path, transport, capsys)
    transport.result[field] = value
    assert confirm(tmp_path, "--yes", "--confirmation-phrase", PHRASES["allow"]) == 5
    assert len(transport.records) == 1


def test_a_revoke_review_never_accepts_an_authorized_result(tmp_path, transport, capsys):
    make_receipt(tmp_path, transport, capsys, "revoke")
    transport.result["status"] = "authorized"
    assert confirm(tmp_path, "--yes", "--confirmation-phrase", PHRASES["revoke"]) == 5


@pytest.mark.parametrize("status", [401, 403, 404, 405, 409, 422, 500])
@pytest.mark.parametrize("action", ["prepare", "confirm"])
def test_http_errors_never_fallback_or_retry(tmp_path, transport, capsys, status, action):
    if action == "confirm":
        make_receipt(tmp_path, transport, capsys)
    transport.error = HTTPError(BASE + ENDPOINT + "/" + action, status, "failed", {},
                                io.BytesIO(json.dumps({"detail": API_KEY}).encode()))
    code = (prepare(tmp_path) if action == "prepare"
            else confirm(tmp_path, "--yes", "--confirmation-phrase", PHRASES["allow"]))
    assert code != 0
    assert len(transport.records) == 1
    output = capsys.readouterr()
    assert API_KEY not in output.out + output.err
    if status in (404, 405):
        assert "requires an API supporting the authorize-deletion routes" in output.err
        assert "no fallback" in output.err


def test_the_operations_own_not_found_is_not_mistaken_for_a_missing_route(tmp_path, transport, capsys):
    detail = "Deletion authorization blocked: no enrollment of this saved factory exists."
    transport.error = HTTPError(BASE + ENDPOINT + "/prepare", 404, "Not Found", {},
                                io.BytesIO(json.dumps({"detail": detail}).encode()))
    assert prepare(tmp_path) != 0
    error = capsys.readouterr().err
    assert "no enrollment" in error and "no fallback" not in error


def test_timeout_confirmation_is_unknown_and_never_retried(tmp_path, transport, capsys):
    make_receipt(tmp_path, transport, capsys)
    transport.error = TimeoutError()
    assert confirm(tmp_path, "--yes", "--confirmation-phrase", PHRASES["allow"]) == 4
    assert len(transport.records) == 1
    assert "outcome is unknown" in capsys.readouterr().err


def test_receipt_for_another_operation_is_refused_without_calling_the_api(tmp_path, transport, capsys):
    make_receipt(tmp_path, transport, capsys)
    path = tmp_path / "receipt.json"
    receipt = json.loads(path.read_text())
    receipt["purpose"] = "reconcile-run-claim-confirm"
    path.write_text(json.dumps(receipt))
    assert confirm(tmp_path, "--yes", "--confirmation-phrase", PHRASES["allow"]) == 2
    assert not transport.records


def test_a_tampered_receipt_mode_is_refused_without_calling_the_api(tmp_path, transport, capsys):
    make_receipt(tmp_path, transport, capsys)
    path = tmp_path / "receipt.json"
    receipt = json.loads(path.read_text())
    receipt["preview"]["mode"] = "revoke"
    path.write_text(json.dumps(receipt))
    assert confirm(tmp_path, "--yes", "--confirmation-phrase", PHRASES["allow"]) == 2
    assert not transport.records


def test_existing_receipt_prevents_the_prepare_call(tmp_path, transport):
    (tmp_path / "receipt.json").write_text("{}")
    assert prepare(tmp_path) == 2
    assert not transport.records


def test_sdk_methods_use_only_the_named_routes(transport):
    from azurefactory.client import AzureFactoryClient
    from azurefactory.authorization import validate_authorization, validate_preview

    request = {"contract_version": 1, "folder": FOLDER, "factory_id": FACTORY, "mode": "allow"}
    api = AzureFactoryClient(BASE, API_KEY, 5)
    reviewed = api.authorize_deletion_prepare(request)
    assert reviewed == transport.preview
    validate_preview(request, reviewed)
    outcome = api.authorize_deletion_confirm(folder=FOLDER, confirmation_id=CONFIRMATION, preview_hash="c" * 64,
                                             confirmation_phrase=PHRASES["allow"])
    assert outcome == transport.result
    validate_authorization(outcome, {"folder": FOLDER, "preview": reviewed})
    assert [record["url"] for record in transport.records] == [BASE + ENDPOINT + "/prepare", BASE + ENDPOINT + "/confirm"]


def test_sdk_prepare_validates_the_request_before_any_call(transport):
    from azurefactory import ConfigError
    from azurefactory.client import AzureFactoryClient

    api = AzureFactoryClient(BASE, API_KEY, 5)
    with pytest.raises(ConfigError):
        api.authorize_deletion_prepare({"contract_version": 1, "folder": FOLDER, "factory_id": FACTORY,
                                        "mode": "grant"})
    assert not transport.records


def test_command_help_uses_plain_language():
    parser = build_parser()
    text = parser._subparsers._group_actions[0].choices["authorize-deletion"].format_help()
    assert "deletion permission" in text and "revoke" in text and "Azure" in text
