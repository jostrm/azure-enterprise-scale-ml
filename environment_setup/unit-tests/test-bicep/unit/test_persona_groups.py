"""Offline identity bootstrap/resolution contracts. No Azure credentials or writes."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest


ROOT = Path(__file__).resolve().parents[4]
PATH = ROOT / "environment_setup" / "aifactory" / "bicep" / "personas" / "groups.py"
SPEC = importlib.util.spec_from_file_location("persona_groups_under_test", PATH)
GROUPS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GROUPS)
TENANT = "11111111-1111-1111-1111-111111111111"
SUB = "22222222-2222-2222-2222-222222222222"
OTHER = "33333333-3333-3333-3333-333333333333"


@pytest.fixture
def manifest():
    return {
        "schema": "aifactory.persona-access/v1",
        "tenant_id": TENANT, "factory": "factory01", "scaleset": "scale01",
        "environment": "dev", "project": "project001",
        "seeding": {"subscription_id": SUB, "resource_group": "seed-rg", "vault_name": "factory-seed"},
    }


def group(name, object_id):
    return {"id": object_id, "displayName": name, "securityEnabled": True, "mailEnabled": False,
            "groupTypes": [], "isAssignableToRole": False, "deletedDateTime": None}


class FakeCLI:
    def __init__(self, manifest, *, existing=True, seeded=False):
        self.manifest = manifest
        self.calls, self.groups, self.secrets, self.deleted = [], {}, {}, set()
        self.next_id = 100
        for index, (persona, spec) in enumerate(GROUPS.group_specs(manifest).items(), 1):
            object_id = str(UUID(int=index))
            if existing:
                self.groups[object_id] = group(spec["name"], object_id)
            if seeded:
                self.secrets[spec["seed_key"]] = {
                    "value": json.dumps(GROUPS._record(spec, persona, object_id)), "attributes": {"enabled": True},
                }
        self.hook = None

    @property
    def writes(self):
        return [call for call in self.calls if call[:3] == ("keyvault", "secret", "set")
                or (call[:3] == ("rest", "--method", "post"))]

    def __call__(self, *args):
        self.calls.append(args)
        if self.hook:
            result = self.hook(args)
            if result is not None:
                return result
        if args[:2] == ("account", "show"):
            return {"id": SUB if "--subscription" in args else OTHER, "tenantId": TENANT, "state": "Enabled"}
        if args[0] == "keyvault":
            assert args[args.index("--subscription") + 1] == SUB
            assert args[args.index("--vault-name") + 1] == self.manifest["seeding"]["vault_name"]
            key = args[args.index("--name") + 1]
            if args[2] == "show":
                if key not in self.secrets:
                    raise RuntimeError("ERROR: (SecretNotFound) absent")
                return deepcopy(self.secrets[key])
            if args[2] == "show-deleted":
                if key in self.deleted:
                    return {"deletedDate": 123}
                raise RuntimeError('{"error": {"code": "SecretNotFound"}}')
            if args[2] == "set":
                self.secrets[key] = {"value": args[args.index("--value") + 1], "attributes": {"enabled": True}}
                return deepcopy(self.secrets[key])
        if args[0] == "rest":
            method, url = args[2], args[args.index("--url") + 1]
            parts = urlsplit(url)
            if method == "post":
                body = json.loads(args[args.index("--body") + 1])
                assert body["groupTypes"] == [] and body["mailEnabled"] is False and body["securityEnabled"] is True
                assert "isAssignableToRole" not in body
                assert len(body["mailNickname"]) <= 64
                self.next_id += 1
                object_id = str(UUID(int=self.next_id))
                self.groups[object_id] = group(body["displayName"], object_id)
                return deepcopy(self.groups[object_id])
            if parts.path == "/v1.0/groups":
                name = parse_qs(parts.query)["$filter"][0].split("'")[1]
                return {"value": [deepcopy(item) for item in self.groups.values() if item["displayName"] == name]}
            object_id = parts.path.rsplit("/", 1)[1]
            if object_id in self.groups:
                return deepcopy(self.groups[object_id])
            raise RuntimeError("ERROR: (Request_ResourceNotFound) missing/deleted")
        raise AssertionError(f"Unexpected command: {args[:3]}")


def test_exact_names_seed_keys_and_shared_core(manifest):
    project = GROUPS.group_specs(manifest)
    common = GROUPS.group_specs(manifest, "common")
    assert len(project) == 9 and set(common) == {"persona200", "persona201"}
    assert common["persona200"]["name"] == "aif--factory01--dev--persona200"
    assert project["persona213"]["name"] == "aif--factory01--scale01--dev--project001--persona213"
    assert project["persona213"]["seed_key"] == "group-aif--factory01--scale01--dev--project001--persona213"
    assert common["persona200"]["binding"] == {"tenant_id": TENANT, "factory": "factory01", "environment": "dev"}
    for field, value in (("scaleset", "scale02"), ("project", "project002")):
        changed = GROUPS.group_specs({**manifest, field: value})
        assert changed["persona200"] == project["persona200"]
        assert changed["persona210"]["name"] != project["persona210"]["name"]
    for field, value in (("factory", "factory02"), ("environment", "prod")):
        changed = GROUPS.group_specs({**manifest, field: value})
        assert all(changed[p]["name"] != project[p]["name"] for p in project)


def test_hyphenated_components_cannot_collide_across_boundaries(manifest):
    first = GROUPS.group_specs({**manifest, "factory": "a-b", "scaleset": "c"})
    second = GROUPS.group_specs({**manifest, "factory": "a", "scaleset": "b-c"})
    assert first["persona210"]["name"] == "aif--a-b--c--dev--project001--persona210"
    assert second["persona210"]["name"] == "aif--a--b-c--dev--project001--persona210"
    assert not ({item["name"] for item in first.values()} & {item["name"] for item in second.values()})
    assert not ({item["seed_key"] for item in first.values()} & {item["seed_key"] for item in second.values()})
    maximum = GROUPS.group_specs({**manifest, "factory": "a" * 24, "scaleset": "b" * 24,
                                 "environment": "prod", "project": "project999"})
    assert all(len(spec["name"]) <= 120 and len(spec["seed_key"]) <= 127 for spec in maximum.values())


@pytest.mark.parametrize("field,value", [
    ("schema", "unknown"), ("tenant_id", OTHER.replace("-", "")),
    ("tenant_id", "00000000-0000-0000-0000-000000000000"),
    ("tenant_id", "ffffffff-ffff-ffff-ffff-ffffffffffff"),
    ("factory", "<factory>"), ("factory", "your-factory"), ("factory", "../wrong"),
    ("factory", "a" * 25), ("scaleset", "upperCase"), ("scaleset", "a--b"),
    ("environment", "staging"), ("project", "project1"), ("project", "project001-other"),
    ("groups", {"persona001": OTHER}), ("groups", {"persona210": "not-a-guid"}),
    ("groups", {"persona210": OTHER, "persona211": OTHER.upper()}),
])
def test_invalid_manifests_fail_before_calls(manifest, field, value):
    fake = FakeCLI(manifest)
    with pytest.raises(GROUPS.GroupsError):
        GROUPS.reconcile_groups({**manifest, field: value}, cli=fake)
    assert not fake.calls


@pytest.mark.parametrize("field,value", [
    ("subscription_id", "placeholder"), ("vault_name", "-bad"), ("vault_name", "a--b"),
    ("vault_name", "x" * 25), ("resource_group", "bad/path"), ("resource_group", "ends."),
])
def test_invalid_seed_target(manifest, field, value):
    manifest["seeding"][field] = value
    with pytest.raises(GROUPS.GroupsError):
        GROUPS.group_specs(manifest)


def test_runtime_reads_only_bound_keyvault_records(manifest):
    fake = FakeCLI(manifest, seeded=True)
    ids = GROUPS.resolve_seeded_groups(manifest, "project", fake)
    assert len(ids) == 9 and len(set(ids.values())) == 9
    assert len(fake.calls) == 9
    assert all(call[:3] == ("keyvault", "secret", "show") for call in fake.calls)
    assert GROUPS.resolve_seeded_groups(manifest, "common", fake) == {p: ids[p] for p in GROUPS.COMMON_PERSONAS}


@pytest.mark.parametrize("field,value", [
    ("schema", "wrong"), ("tenant_id", OTHER), ("factory", "other"),
    ("scaleset", "wrong"), ("environment", "prod"), ("project", "project002"),
    ("persona", "persona211"), ("display_name", "historical-name"),
    ("object_id", "00000000-0000-0000-0000-000000000000"), ("unexpected_scope", "wrong"),
])
def test_runtime_rejects_misbound_seed_metadata(manifest, field, value):
    fake = FakeCLI(manifest, seeded=True)
    key = GROUPS.group_specs(manifest)["persona210"]["seed_key"]
    record = json.loads(fake.secrets[key]["value"])
    record[field] = value
    fake.secrets[key]["value"] = json.dumps(record)
    with pytest.raises(GROUPS.GroupsError):
        GROUPS.resolve_seeded_groups(manifest, "project", fake)
    assert not fake.writes


def test_common_record_must_not_bind_project_or_scaleset(manifest):
    fake = FakeCLI(manifest, seeded=True)
    key = GROUPS.group_specs(manifest)["persona200"]["seed_key"]
    record = json.loads(fake.secrets[key]["value"])
    record.update(project="project001", scaleset="scale01")
    fake.secrets[key]["value"] = json.dumps(record)
    with pytest.raises(GROUPS.GroupsError, match="binding mismatch"):
        GROUPS.resolve_seeded_groups(manifest, "common", fake)


def test_runtime_rejects_duplicate_ids_and_bare_guid(manifest):
    fake = FakeCLI(manifest, seeded=True)
    key = GROUPS.group_specs(manifest)["persona211"]["seed_key"]
    record = json.loads(fake.secrets[key]["value"])
    record["object_id"] = str(UUID(int=3))
    fake.secrets[key]["value"] = json.dumps(record)
    with pytest.raises(GROUPS.GroupsError, match="multiple personas"):
        GROUPS.resolve_seeded_groups(manifest, "project", fake)
    fake.secrets[key]["value"] = OTHER
    with pytest.raises(GROUPS.GroupsError, match="JSON"):
        GROUPS.resolve_seeded_groups(manifest, "project", fake)


def test_preview_lists_real_changes_without_mutation(manifest):
    fake = FakeCLI(manifest, existing=False)
    preview = GROUPS.reconcile_groups(manifest, "create", cli=fake)
    assert preview["state"] == "preview" and not fake.writes
    assert len(preview["changes"]) == 18 and not preview["blockers"]
    existing = FakeCLI(manifest)
    preview = GROUPS.reconcile_groups(manifest, "discover", cli=existing)
    assert len(preview["changes"]) == 9
    assert all(change["action"] == "publish-seed" for change in preview["changes"])
    assert not existing.writes


def test_discover_missing_never_creates_even_with_execute(manifest):
    fake = FakeCLI(manifest, existing=False)
    result = GROUPS.reconcile_groups(manifest, "discover", execute=True, cli=fake)
    assert len(result["blockers"]) == 9 and "create --execute" in result["blockers"][0]
    assert not fake.writes and not result["changes"]


def test_create_and_publish_idempotent_no_new_secret_versions(manifest):
    fake = FakeCLI(manifest, existing=False)
    result = GROUPS.reconcile_groups(manifest, "create", execute=True, cli=fake)
    assert result["state"] == "executed" and len(fake.writes) == 18
    assert len(fake.groups) == 9 and len(fake.secrets) == 9
    for persona, spec in GROUPS.group_specs(manifest).items():
        assert json.loads(fake.secrets[spec["seed_key"]]["value"]) == {
            "schema": GROUPS.RECORD_SCHEMA, **spec["binding"], "persona": persona,
            "object_id": result["groups"][persona], "display_name": spec["name"],
        }
    fake.calls.clear()
    second = GROUPS.reconcile_groups(manifest, "create", execute=True, cli=fake)
    assert second["changes"] == [] and not fake.writes
    assert GROUPS.resolve_seeded_groups(manifest, "project", fake) == result["groups"]


def test_discover_execute_publishes_existing_groups_only(manifest):
    fake = FakeCLI(manifest)
    GROUPS.reconcile_groups(manifest, "discover", scope="common", execute=True, cli=fake)
    assert len(fake.writes) == 2
    assert all(call[:3] == ("keyvault", "secret", "set") for call in fake.writes)


def test_duplicate_exact_names_fail_before_any_write(manifest):
    fake = FakeCLI(manifest)
    fake.groups[OTHER] = {**fake.groups[str(UUID(int=9))], "id": OTHER}
    with pytest.raises(GROUPS.GroupsError, match="Duplicate"):
        GROUPS.reconcile_groups(manifest, "create", execute=True, cli=fake)
    assert not fake.writes


def test_graph_pagination_finds_duplicate_on_next_page(manifest):
    fake = FakeCLI(manifest)
    spec = GROUPS.group_specs(manifest)["persona200"]
    original = fake.groups[str(UUID(int=1))]
    def hook(args):
        if args[0] == "rest" and urlsplit(args[4]).path == "/v1.0/groups":
            if "$skiptoken" in args[4]:
                return {"value": [{**original, "id": OTHER}]}
            return {"value": [original], "@odata.nextLink": GROUPS.GRAPH_GROUPS + "?$skiptoken=second"}
    fake.hook = hook
    with pytest.raises(GROUPS.GroupsError, match="Duplicate"):
        GROUPS._find_group(spec, fake)
    assert len(fake.calls) == 2


@pytest.mark.parametrize("link", [
    "https://evil.invalid/v1.0/groups", "http://graph.microsoft.com/v1.0/groups",
    "https://graph.microsoft.com/v1.0/users", "https://graph.microsoft.com@evil.invalid/v1.0/groups",
])
def test_graph_rejects_untrusted_pagination_links(manifest, link):
    fake = FakeCLI(manifest)
    fake.hook = lambda args: {"value": [], "@odata.nextLink": link}
    with pytest.raises(GROUPS.GroupsError, match="unsafe"):
        GROUPS._find_group(GROUPS.group_specs(manifest)["persona200"], fake)
    assert len(fake.calls) == 1


@pytest.mark.parametrize("field,value", [
    ("securityEnabled", False), ("mailEnabled", True), ("groupTypes", ["Unified"]),
    ("groupTypes", ["DynamicMembership"]), ("isAssignableToRole", True),
    ("deletedDateTime", "2026-01-01T00:00:00Z"), ("groupTypes", None),
])
def test_invalid_group_properties_rejected(manifest, field, value):
    fake = FakeCLI(manifest)
    fake.groups[str(UUID(int=1))][field] = value
    with pytest.raises(GROUPS.GroupsError, match="Group must"):
        GROUPS.reconcile_groups(manifest, "create", execute=True, cli=fake)
    assert not fake.writes


def test_explicit_guid_adoption_and_historical_name_rejection(manifest):
    fake = FakeCLI(manifest)
    manifest["groups"] = {"persona210": str(UUID(int=3))}
    result = GROUPS.reconcile_groups(manifest, "discover", execute=True, cli=fake)
    assert result["groups"]["persona210"] == str(UUID(int=3))
    fake.calls.clear()
    fake.groups[str(UUID(int=3))]["displayName"] = "aif001sdc_prj001_team_lead_p001"
    with pytest.raises(GROUPS.GroupsError, match="rename historical"):
        GROUPS.reconcile_groups(manifest, "create", execute=True, cli=fake)
    assert not fake.writes


def test_adoption_conflicting_with_seed_never_overwrites(manifest):
    fake = FakeCLI(manifest, seeded=True)
    manifest["groups"] = {"persona210": OTHER}
    with pytest.raises(GROUPS.GroupsError, match="conflicts"):
        GROUPS.reconcile_groups(manifest, "create", execute=True, cli=fake)
    assert not fake.writes


@pytest.mark.parametrize("state", ["disabled", "deleted", "bad-json", "missing"])
def test_seed_failure_does_not_trigger_create(manifest, state):
    fake = FakeCLI(manifest, seeded=True)
    key = GROUPS.group_specs(manifest)["persona200"]["seed_key"]
    if state == "disabled":
        fake.secrets[key]["attributes"]["enabled"] = False
    elif state == "deleted":
        del fake.secrets[key]
        fake.deleted.add(key)
    elif state == "bad-json":
        fake.secrets[key]["value"] = "secret-value-do-not-leak"
    else:
        del fake.secrets[key]
        with pytest.raises(GROUPS.GroupsError, match="Missing seeding record"):
            GROUPS.resolve_seeded_groups(manifest, "common", fake)
        return
    with pytest.raises(GROUPS.GroupsError) as caught:
        GROUPS.reconcile_groups(manifest, "create", execute=True, cli=fake)
    assert "secret-value-do-not-leak" not in str(caught.value) and not fake.writes


@pytest.mark.parametrize("code", ["Forbidden", "Unauthorized", "VaultNotFound", "ResourceNotFound", "Unknown"])
def test_only_secret_not_found_is_absence(manifest, code):
    fake = FakeCLI(manifest)
    def hook(args):
        if args[:3] == ("keyvault", "secret", "show"):
            raise RuntimeError(f"ERROR: ({code}) secret-sensitive-material")
    fake.hook = hook
    with pytest.raises(GROUPS.GroupsError, match="GET authorization") as caught:
        GROUPS.reconcile_groups(manifest, "create", execute=True, cli=fake)
    assert "secret-sensitive-material" not in str(caught.value) and not fake.writes


def test_deleted_lookup_permission_error_fails_closed(manifest):
    fake = FakeCLI(manifest)
    def hook(args):
        if args[:3] == ("keyvault", "secret", "show-deleted"):
            raise RuntimeError("ERROR: (Forbidden) hidden")
    fake.hook = hook
    with pytest.raises(GROUPS.GroupsError, match="deleted.*GET authorization"):
        GROUPS.reconcile_groups(manifest, "create", execute=True, cli=fake)
    assert not fake.writes


def test_graph_privilege_error_never_creates_or_leaks_raw_error(manifest):
    fake = FakeCLI(manifest)
    def hook(args):
        if args[0] == "rest":
            raise RuntimeError("ERROR: (Authorization_RequestDenied) raw-sensitive-text")
    fake.hook = hook
    with pytest.raises(GROUPS.GroupsError, match="Group.Read.All") as caught:
        GROUPS.reconcile_groups(manifest, "create", execute=True, cli=fake)
    assert "raw-sensitive-text" not in str(caught.value) and not fake.writes


@pytest.mark.parametrize("field,value", [("tenantId", OTHER), ("id", OTHER), ("state", "Disabled")])
def test_account_binding_checks_before_graph(manifest, field, value):
    fake = FakeCLI(manifest)
    def hook(args):
        if args[:2] == ("account", "show"):
            account = {"id": SUB, "tenantId": TENANT, "state": "Enabled"}
            account[field] = value
            return account
    fake.hook = hook
    with pytest.raises(GROUPS.GroupsError):
        GROUPS.reconcile_groups(manifest, "create", execute=True, cli=fake)
    assert all(call[:2] == ("account", "show") for call in fake.calls)


def test_prepublication_conflict_is_not_overwritten(manifest):
    fake = FakeCLI(manifest)
    key = GROUPS.group_specs(manifest)["persona200"]["seed_key"]
    spec = GROUPS.group_specs(manifest)["persona200"]
    reads = 0
    def hook(args):
        nonlocal reads
        if args[:3] == ("keyvault", "secret", "show") and args[args.index("--name") + 1] == key:
            reads += 1
            if reads == 2:
                fake.secrets[key] = {"value": json.dumps(GROUPS._record(spec, "persona200", OTHER)),
                                     "attributes": {"enabled": True}}
    fake.hook = hook
    with pytest.raises(GROUPS.GroupsError, match="conflict"):
        GROUPS.reconcile_groups(manifest, "discover", execute=True, cli=fake)
    assert not fake.writes


def test_duplicate_created_in_race_is_detected_and_not_published(manifest):
    fake = FakeCLI(manifest, existing=False)
    def hook(args):
        if args[:3] == ("rest", "--method", "post"):
            body = json.loads(args[args.index("--body") + 1])
            fake.groups[OTHER] = group(body["displayName"], OTHER)
    fake.hook = hook
    with pytest.raises(GROUPS.GroupsError, match="Duplicate"):
        GROUPS.reconcile_groups(manifest, "create", execute=True, cli=fake)
    assert len(fake.groups) == 2 and len(fake.writes) == 1
    assert not fake.secrets


def test_cli_transport_sanitizes_errors_and_forces_utf8(monkeypatch):
    monkeypatch.setattr(GROUPS.shutil, "which", lambda _: "az")
    def run(command, **kwargs):
        assert kwargs["encoding"] == kwargs["env"]["PYTHONIOENCODING"] == "utf-8"
        return SimpleNamespace(returncode=1, stdout="", stderr="ERROR: (Forbidden) SECRET")
    monkeypatch.setattr(GROUPS.subprocess, "run", run)
    with pytest.raises(GROUPS.AzureCLIError) as caught:
        GROUPS.cli("keyvault", "secret", "show")
    assert caught.value.code == "Forbidden" and "SECRET" not in str(caught.value)


@pytest.mark.parametrize("text", [
    "ERROR: (Forbidden) response did not return (SecretNotFound)",
    '{"error":{"code":"Forbidden","message":"(SecretNotFound)"}}',
    "ERROR: access denied, rather than (SecretNotFound)",
    "not found",
])
def test_error_classification_never_turns_denial_into_absence(text):
    assert GROUPS._error_code(RuntimeError(text)) != "SecretNotFound"


def test_shared_cli_transport_prefix_preserves_known_missing_classification():
    error = RuntimeError("Azure CLI keyvault secret show failed: ERROR: (SecretNotFound) missing")
    assert GROUPS._error_code(error) == "SecretNotFound"


def test_shared_cli_typed_error_metadata_is_respected_without_raw_message():
    error = RuntimeError("Azure CLI request failed")
    error.status_code = 404
    error.error_code = "SecretNotFound"
    assert GROUPS._error_code(error) == "SecretNotFound"
    error.error_code = "VaultNotFound"
    assert GROUPS._error_code(error) == "VaultNotFound"


@pytest.mark.parametrize("boundary", ["account", "seed", "deleted", "graph", "publication"])
@pytest.mark.parametrize("error_type", [AssertionError, TypeError, KeyError, AttributeError])
def test_programming_errors_are_not_masked(manifest, boundary, error_type):
    fake = FakeCLI(manifest)
    def hook(args):
        matches = {
            "account": args[:2] == ("account", "show"),
            "seed": args[:3] == ("keyvault", "secret", "show"),
            "deleted": args[:3] == ("keyvault", "secret", "show-deleted"),
            "graph": args[0] == "rest",
            "publication": args[:3] == ("keyvault", "secret", "set"),
        }
        if matches[boundary]:
            raise error_type("programming fault")
    fake.hook = hook
    with pytest.raises(error_type, match="programming fault"):
        GROUPS.reconcile_groups(manifest, "discover", execute=True, cli=fake)


def test_disappeared_seed_never_recreated(manifest):
    fake = FakeCLI(manifest, seeded=True)
    key = GROUPS.group_specs(manifest)["persona200"]["seed_key"]
    reads = 0
    def hook(args):
        nonlocal reads
        if args[:3] == ("keyvault", "secret", "show") and args[args.index("--name") + 1] == key:
            reads += 1
            if reads == 2:
                del fake.secrets[key]
    fake.hook = hook
    with pytest.raises(GROUPS.GroupsError, match="disappeared"):
        GROUPS.reconcile_groups(manifest, "create", execute=True, cli=fake)
    assert not fake.writes


def test_creation_privilege_failure_is_actionable(manifest):
    fake = FakeCLI(manifest, existing=False)
    def hook(args):
        if args[:3] == ("rest", "--method", "post"):
            raise RuntimeError("ERROR: (Authorization_RequestDenied) confidential")
    fake.hook = hook
    with pytest.raises(GROUPS.GroupsError, match="Group.ReadWrite.All.*directory rights") as caught:
        GROUPS.reconcile_groups(manifest, "create", execute=True, cli=fake)
    assert "confidential" not in str(caught.value) and not fake.secrets


def test_secret_set_privilege_failure_is_actionable(manifest):
    fake = FakeCLI(manifest)
    def hook(args):
        if args[:3] == ("keyvault", "secret", "set"):
            raise RuntimeError("ERROR: (Forbidden) confidential")
    fake.hook = hook
    with pytest.raises(GROUPS.GroupsError, match="SET authorization") as caught:
        GROUPS.reconcile_groups(manifest, "discover", execute=True, cli=fake)
    assert "confidential" not in str(caught.value) and not fake.secrets


def test_wrapper_keeps_noarg_legacy_and_rejects_unknown_flags():
    script = ROOT / "environment_setup" / "aifactory" / "bicep" / "esml-util" / "32-create-azure-groups.sh"
    text = script.read_text(encoding="utf-8")
    assert text.index('if [ "$#" -gt 0 ]') < text.index('read -p "Enter project type')
    assert 'Invalid persona option:' in text
    assert 'exec python3 "$script_dir/../personas/groups.py"' in text
    bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    if bash.is_file():
        checked = subprocess.run([str(bash), "-n", str(script)], text=True, capture_output=True)
        assert checked.returncode == 0, checked.stderr
        for args in (["--bad"], ["--persona-manifest"], ["--persona-manifest", "unused", "--manifest", "other"],
                     ["--persona-manifest", "unused", "--scope"]):
            checked = subprocess.run([str(bash), str(script), *args], text=True, capture_output=True)
            assert checked.returncode == 2 and checked.stderr
