"""Modern create routing and opt-in real loopback API checks; never cloud operations."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[4]
LIB = ROOT / "bootstrap" / "lib"
sys.path.insert(0, str(LIB))
SPEC = importlib.util.spec_from_file_location("registered_creation", LIB / "registered_creation.py")
CREATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CREATION)
BASH = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
if not BASH.is_file():
    BASH = shutil.which("bash")


def clean_env(**values):
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("AIF_", "AIFACTORY_", "ADO_", "GHA_", "GITHUB_"))
                   and key not in ("BASH_ENV", "ENV", "SHELLOPTS")}
    return {**environment, "AIFACTORY_PYTHON": sys.executable, **values}


def input_env(provider="gha", simple=False, **values):
    route = ({"GITHUB_REPOSITORY": "org/consumer"} if provider == "gha" else {
        "ADO_ORGANIZATION": "https://dev.azure.com/org", "ADO_PROJECT": "project",
        "ADO_REPOSITORY_NAME": "consumer", "ADO_SERVICE_CONNECTION_NAME": "sc-aif",
    })
    return {
        "AIF_SIMPLE_MODE": str(simple).lower(),
        "AIF_TENANT_ID": "11111111-1111-1111-1111-111111111111",
        "AIF_DEV_SUBSCRIPTION_ID": "22222222-2222-2222-2222-222222222222",
        "AIF_PREFIX": "dc-batman-", "AIF_LOCATION": "denmarkeast",
        "AIF_TEAM_MEMBER_EMAIL": "owner@example.org", "AIF_TEAM_GROUP_NAME": "aif-team",
        **route, **values,
    }


@pytest.mark.parametrize("provider,simple", [("gha", True), ("gha", False), ("ado", False)])
@pytest.mark.parametrize("project", [None, "007"])
def test_form_mapping_preserves_identity_and_only_selected_project(tmp_path, provider, simple, project):
    args = CREATION.parser().parse_args([provider, "--non-interactive"])
    env = input_env(provider, simple)
    if project:
        env["AIF_PROJECT_NUMBER"] = project
    body = CREATION.creation_input(args, tmp_path, "main", env)
    assert body["contract_version"] == 1
    assert body["folder"] == str(tmp_path)
    assert body["mode"] == ("simple" if simple else "full-bootstrap")
    assert body["config"]["subscription_id"] == env["AIF_DEV_SUBSCRIPTION_ID"]
    assert body["config"]["tenant_id"] == env["AIF_TENANT_ID"]
    if simple:
        assert "project_number" not in body["config"] and "scale_set_number" not in body["config"]
        assert body.get("initial_project", {}).get("number") == project
    else:
        assert body["config"].get("project_number") == project
        assert body["config"]["scale_set_number"] == "001"
    assert body["config"]["aifactory_version"] == "main"
    assert "settings" not in body  # canonical API owns preset/settings projection


@pytest.mark.skipif(not BASH, reason="Git Bash unavailable")
@pytest.mark.parametrize("hub", [None, "false"])
@pytest.mark.parametrize("provider,simple", [("GHA", True), ("GHA", False), ("ADO", False)])
def test_real_launcher_modern_dry_run_has_no_cloud_or_file_writes(tmp_path, provider, simple, hub):
    # Only inspect this nonexistent sibling: a consumer inside the source is forbidden.
    target = ROOT.parent / (".aif-offline-input-" + str(uuid4()))
    result = subprocess.run(
        [str(BASH), str(ROOT / "bootstrap" / f"{provider}-create-new-aifactory-scaleset.sh"),
         "--repo-root", str(target), "--aifactory-version", "main",
         "--non-interactive", "--yes", "--dry-run"],
        env=clean_env(**input_env(provider.lower(), simple, AIF_PROJECT_NUMBER="007",
                                 **({"AIF_SETUP_HUB_ACCESS": hub} if hub is not None else {}))),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["status"] == "offline-input-only"
    assert (output["request"]["initial_project"] if simple else output["request"]["config"])["number" if simple else "project_number"] == "007"
    config = output["request"]["config"]
    assert ("setup_hub_access" in config) == (hub is not None)
    if hub is not None:
        assert config["setup_hub_access"] is False
    assert not target.exists()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("simple", [True, False])
@pytest.mark.parametrize("value,expected", [(None, None), ("true", True), ("y", True), ("false", False), ("n", False)])
def test_modern_hub_topology_maps_explicit_boolean_only(tmp_path, simple, value, expected):
    args = CREATION.parser().parse_args(["gha", "--non-interactive"])
    env = input_env(simple=simple, **({"AIF_SETUP_HUB_ACCESS": value} if value is not None else {}))
    config = CREATION.creation_input(args, tmp_path, "125", env)["config"]
    assert ("setup_hub_access" in config) == (value is not None)
    if value is not None:
        assert config["setup_hub_access"] is expected


@pytest.mark.parametrize("simple", [True, False])
@pytest.mark.parametrize("value", ["", "0", "1", "False", "standalone", False, None])
def test_modern_hub_topology_rejects_invalid_environment_values(tmp_path, simple, value):
    args = CREATION.parser().parse_args(["gha", "--non-interactive"])
    with pytest.raises(ValueError, match="AIF_SETUP_HUB_ACCESS must"):
        CREATION.creation_input(args, tmp_path, "main", input_env(simple=simple, AIF_SETUP_HUB_ACCESS=value))


@pytest.mark.parametrize("simple", [True, False])
@pytest.mark.parametrize("access", ["true", "false"])
def test_external_hub_coordinates_are_independent_from_optional_access(tmp_path, simple, access):
    args = CREATION.parser().parse_args(["gha", "--non-interactive"])
    config = CREATION.creation_input(args, tmp_path, "main", input_env(
        simple=simple, AIF_ACCESS_HUB_MODE="e", AIF_SETUP_HUB_ACCESS=access,
        AIF_ACCESS_HUB_SUBSCRIPTION_ID="33333333-3333-3333-3333-333333333333",
        AIF_ACCESS_HUB_RESOURCE_GROUP="shared-hub", AIF_ACCESS_HUB_VNET_NAME="existing-hub",
        AIF_ACCESS_HUB_VNET_CIDR="10.40.0.0/24", AIF_VPN_CLIENT_CIDR="172.30.0.0/24"))["config"]
    assert config["access_hub_mode"] == "external"
    assert config["setup_hub_access"] is (access == "true")
    assert config["access_hub_vnet_name"] == "existing-hub"
    assert config["access_hub_subscription_id"] == "33333333-3333-3333-3333-333333333333"
    assert config["vpn_client_cidr"] == "172.30.0.0/24"


def test_external_hub_coordinates_are_not_ignored_or_guessed(tmp_path):
    args = CREATION.parser().parse_args(["gha", "--non-interactive"])
    with pytest.raises(ValueError, match="explicit reviewed coordinates"):
        CREATION.creation_input(args, tmp_path, "main", input_env(AIF_ACCESS_HUB_MODE="external"))
    with pytest.raises(ValueError, match="never silently ignored"):
        CREATION.creation_input(args, tmp_path, "main", input_env(AIF_ACCESS_HUB_RESOURCE_GROUP="shared"))


@pytest.mark.skipif(not BASH, reason="Git Bash unavailable")
@pytest.mark.parametrize("simple", [False, True])
def test_raw_library_rejects_unmapped_options_before_legacy_or_api(tmp_path, simple):
    root = tmp_path / "consumer"
    result = subprocess.run(
        [str(BASH), "--noprofile", "--norc", "-c",
         'source bootstrap/lib/create-new-aifactory-scaleset.sh; '
         'aif_scaleset_main gha "$PWD/bootstrap/GHA-create-new-aifactory-scaleset.sh" "$@"',
         "raw-create", "--repo-root", str(root), "--non-interactive", "--dry-run"],
        cwd=ROOT, env=clean_env(**input_env(simple=simple, AIF_RUNNER_VM_OS="linux")),
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 2
    assert "Unmapped modern bootstrap settings" in result.stderr
    assert "AIF_RUNNER_VM_OS" in result.stderr
    assert not root.exists()


def api_result(root, project="001"):
    scale_id = str(uuid4())
    return {
        "contract_version": 1, "folder": str(root / "azurefactory"),
        "capabilities": ["initial-project-v1", "draft-scale-identity-v1"],
        "operation_mode": "configuration",
        "target": {
            "id": str(uuid4()), "kind": "ai", "default_orchestrator": "gha",
            "aifactory_version": "main", "version_ref": "main", "prefix": "dc-batman-", "region": "denmarkeast",
            "projects": [{"id": str(uuid4()), "number": project,
                          "placements": [{"environment": "dev", "scale_set_id": scale_id}]}],
            "scale_sets": [{
                "id": scale_id,
                "environment": "dev", "orchestrator": "gha", "suffix": "001",
                "tenant_id": "11111111-1111-1111-1111-111111111111",
                "subscription_id": "22222222-2222-2222-2222-222222222222",
            }],
        },
        "can_execute": True, "mapped_settings": {}, "deferred_fields": [],
        "blockers": [], "confirmation_id": str(uuid4()), "expires_at": "2099-01-01T00:00:00Z",
    }


@pytest.mark.parametrize("project", ["001", "007"])
def test_review_uses_shared_sdk_receipt_and_never_confirms(tmp_path, monkeypatch, capsys, project):
    root = tmp_path / "consumer"
    root.mkdir()
    receipt = tmp_path / "review.json"
    args = CREATION.parser().parse_args(["gha", "--non-interactive", "--yes", "--save-receipt", str(receipt)])
    calls = []
    _, write_receipt = CREATION.load_sdk()

    class Client:
        canonical_base_url = "http://127.0.0.1:8765"

        def request(self, method, endpoint, *, body):
            calls.append((method, endpoint, body))
            return api_result(root, project)

    monkeypatch.setattr(CREATION, "load_sdk", lambda: (Client, write_receipt))
    monkeypatch.setattr(CREATION.os, "environ", input_env(AIF_PROJECT_NUMBER=project))
    assert CREATION.prepare(args, root, "main") == 0
    saved = json.loads(receipt.read_text(encoding="utf-8"))
    assert saved["purpose"] == "catalog-confirm"
    assert saved["operation"] == "factory-create"
    assert saved["request"]["config"]["project_number"] == project
    assert saved["request"]["action"] == "create-factory"
    assert saved["folder"] == str(root / "azurefactory")
    assert saved["preview"]["target"]["projects"][0]["number"] == project
    assert len(calls) == 1
    assert calls[0][:2] == ("POST", "/api/v1/creation/prepare")
    assert not list(root.iterdir())
    output = capsys.readouterr().out
    assert "NOT DEPLOYED" in output and "runtime prepare/review/confirm" in output


@pytest.mark.parametrize("changed", [
    "runtime", "contract", "folder", "relative-folder", "version", "version-ref", "project", "extra-project",
    "subscription", "tenant", "prefix", "region", "kind", "provider", "extra-scale",
    "suffix", "environment", "placement", "missing-target", "obsolete-response",
    "missing-capabilities", "missing-initial-project", "missing-draft-scale", "malformed-capabilities",
])
def test_stale_or_changed_api_contract_fails_closed(tmp_path, monkeypatch, changed):
    root = tmp_path / "consumer"
    root.mkdir()
    receipt = tmp_path / "review.json"
    args = CREATION.parser().parse_args(["gha", "--non-interactive", "--save-receipt", str(receipt)])
    result = api_result(root)
    if changed == "runtime":
        result["operation_mode"] = "runtime"
    elif changed == "contract":
        result["contract_version"] = True
    elif changed == "folder":
        result["folder"] = str(root / "aifactory")
    elif changed == "relative-folder":
        result["folder"] = "azurefactory"
    elif changed in {"subscription", "tenant", "suffix", "environment"}:
        key = {"subscription": "subscription_id", "tenant": "tenant_id"}.get(changed, changed)
        result["target"]["scale_sets"][0][key] = "002" if changed == "suffix" else str(uuid4())
    elif changed in {"project", "placement"}:
        result["target"]["projects"][0]["number" if changed == "project" else "placements"] = (
            "002" if changed == "project" else [{"environment": "dev", "scale_set_id": str(uuid4())}])
    elif changed == "extra-project":
        result["target"]["projects"].append({"number": "002"})
    elif changed == "extra-scale":
        result["target"]["scale_sets"].append({})
    elif changed == "missing-target":
        result["target"] = None
    elif changed == "obsolete-response":
        result = {"operation_mode": "configuration", "catalog_request": {}, "catalog_preview": result}
    elif changed == "missing-capabilities":
        result.pop("capabilities")
    elif changed == "missing-initial-project":
        result["capabilities"] = ["draft-scale-identity-v1"]
    elif changed == "missing-draft-scale":
        result["capabilities"] = ["initial-project-v1"]
    elif changed == "malformed-capabilities":
        result["capabilities"] = [{"initial-project-v1": True}, "draft-scale-identity-v1"]
    else:
        key, value = {
            "version": ("aifactory_version", "124"), "version-ref": ("version_ref", "124"),
            "prefix": ("prefix", "changed-"), "region": ("region", "swedencentral"),
            "kind": ("kind", "robot"), "provider": ("default_orchestrator", "ado"),
        }[changed]
        result["target"][key] = value

    class Client:
        def request(self, *args, **kwargs):
            return result

    monkeypatch.setattr(CREATION, "load_sdk", lambda: (Client, None))
    monkeypatch.setattr(CREATION.os, "environ", input_env())
    with pytest.raises(ValueError):
        CREATION.prepare(args, root, "main")
    assert not receipt.exists() and not list(root.iterdir())


def test_prepare_requires_existing_consumer_before_api(tmp_path, monkeypatch):
    args = CREATION.parser().parse_args(["gha", "--non-interactive", "--save-receipt", str(tmp_path / "review.json")])
    monkeypatch.setattr(CREATION.os, "environ", input_env())
    monkeypatch.setattr(CREATION, "load_sdk", lambda: pytest.fail("No API call for a missing consumer"))
    with pytest.raises(ValueError, match="Create the consumer repository directory"):
        CREATION.prepare(args, tmp_path / "missing", "main")
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("version,expected", [
    ("124", False), ("1.24", False), ("125", True), ("1.25", True),
    ("main", True), ("1.100", True), ("10.2", True),
])
def test_layout_uses_normalized_version(version, expected):
    assert CREATION.modern(version) is expected


def test_layout_defaults_main_preserves_explicit_legacy_and_rejects_conflicts(tmp_path):
    args = CREATION.parser().parse_args(["gha", "--repo-root", str(tmp_path)])
    assert CREATION.selected_version(args, {}) == "main"
    assert CREATION.selected_version(args, {"AIFACTORY_VERSION": "124"}) == "124"
    assert CREATION.selected_version(args, {"AIF_SUBMODULE_BRANCH": "release/v1.24"}) == "124"
    assert CREATION.release_version.DEFAULT_VERSION == "124"
    args.aifactory_version = "main"
    with pytest.raises(ValueError, match="Conflicting"):
        CREATION.selected_version(args, {"AIFACTORY_VERSION": "124"})


def test_layout_preserves_saved_legacy(tmp_path):
    state = tmp_path / "aifactory"
    state.mkdir()
    (state / "variables.json").write_text('{"aifactory_version": "124"}', encoding="utf-8")
    args = CREATION.parser().parse_args(["gha", "--repo-root", str(tmp_path)])
    assert CREATION.selected_version(args, {}) == "124"


@pytest.mark.parametrize("simple,name,value", [
    (True, "AIF_SCALESET_SUFFIX", "003"), (True, "AIF_RUNNER_MODE", "self-hosted"),
    (True, "AIF_TEAM_GROUP_ID", str(uuid4())), (False, "AIF_RUNNER_VM_OS", "linux"),
    (False, "ADO_RUNNER_MODE", "s"), (False, "GHA_UNMAPPED_OPTION", "yes"),
    (False, "GITHUB_UNMAPPED_OPTION", "yes"), (False, "AIF_NETWORK_MODE", "pub"),
])
def test_unmapped_modern_shell_settings_fail_closed(tmp_path, simple, name, value):
    args = CREATION.parser().parse_args(["gha", "--non-interactive"])
    with pytest.raises(ValueError, match=name):
        CREATION.creation_input(args, tmp_path, "main", input_env(simple=simple, **{name: value}))


@pytest.mark.parametrize("provider,selector", [("gha", "GITHUB-ACTIONS"), ("ado", "azuredevops")])
def test_dispatcher_environment_matches_selected_provider(tmp_path, provider, selector):
    args = CREATION.parser().parse_args([provider, "--non-interactive"])
    body = CREATION.creation_input(args, tmp_path, "main", input_env(provider, AIF_ORCHESTRATOR=selector))
    assert body["orchestrator"] == provider
    with pytest.raises(ValueError, match="AIF_ORCHESTRATOR"):
        CREATION.creation_input(args, tmp_path, "main", input_env(
            provider, AIF_ORCHESTRATOR="ado" if provider == "gha" else "gha"))


@pytest.mark.parametrize("kind", ["legacy", "register", "partial", "source"])
def test_modern_rejects_existing_or_source_data_without_writes(tmp_path, kind):
    if kind == "legacy":
        (tmp_path / "aifactory").mkdir()
    elif kind == "register":
        (tmp_path / "azurefactory").mkdir()
        (tmp_path / "azurefactory" / "register.json").write_text("{}", encoding="utf-8")
    elif kind == "partial":
        (tmp_path / "azurefactory").mkdir()
        (tmp_path / "azurefactory" / "orphan.json").write_text("{}", encoding="utf-8")
    else:
        (tmp_path / "environment_setup" / "aifactory").mkdir(parents=True)
        (tmp_path / "bootstrap").mkdir()
    before = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    with pytest.raises(ValueError):
        CREATION.consumer_root(tmp_path)
    assert before == sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))


def test_pending_catalog_metadata_can_be_reprepared(tmp_path):
    internal = tmp_path / "azurefactory" / ".azurefactory"
    internal.mkdir(parents=True)
    for name in (".catalog.lock", "catalog-operations.sqlite", "catalog-operations.sqlite-wal"):
        (internal / name).write_bytes(b"")
    assert CREATION.consumer_root(tmp_path) == tmp_path


def test_unrelated_legacy_sibling_does_not_block_pending_consumer(tmp_path):
    (tmp_path / "aifactory").mkdir()
    consumer = tmp_path / "separate-consumer"
    internal = consumer / "azurefactory" / ".azurefactory"
    internal.mkdir(parents=True)
    for name in (".catalog.lock", "catalog-operations.sqlite", "catalog-operations.sqlite-journal",
                 "catalog-operations.sqlite-wal", "catalog-operations.sqlite-shm"):
        (internal / name).write_bytes(b"")
    before = {path: path.read_bytes() for path in internal.iterdir()}
    assert CREATION.consumer_root(consumer) == consumer
    assert before == {path: path.read_bytes() for path in internal.iterdir()}


@pytest.mark.parametrize("git_marker", ["directory", "file", None])
def test_nested_legacy_repository_or_legacy_tree_remains_blocked(tmp_path, git_marker):
    legacy = tmp_path / "aifactory"
    legacy.mkdir()
    if git_marker == "directory":
        (tmp_path / ".git").mkdir()
    elif git_marker == "file":
        (tmp_path / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    consumer = (tmp_path if git_marker else legacy) / "nested-consumer"
    with pytest.raises(ValueError, match="legacy aifactory"):
        CREATION.consumer_root(consumer)
    assert not consumer.exists()


@pytest.mark.parametrize("kind", ["unrelated", "directory", "hardlink"])
def test_pending_metadata_never_allows_unrelated_or_linked_files(tmp_path, kind):
    internal = tmp_path / "azurefactory" / ".azurefactory"
    internal.mkdir(parents=True)
    path = internal / "catalog-operations.sqlite"
    if kind == "unrelated":
        (internal / "unexpected.json").write_text("{}", encoding="utf-8")
    elif kind == "directory":
        path.mkdir()
    else:
        source = tmp_path / "source.sqlite"
        source.write_bytes(b"")
        path.hardlink_to(source)
    with pytest.raises(ValueError, match="Unrecognized pending"):
        CREATION.consumer_root(tmp_path)


@pytest.mark.skipif(not BASH, reason="Git Bash unavailable")
@pytest.mark.parametrize("provider", ["GHA", "ADO"])
def test_modern_wrapper_intercepts_before_legacy_library(tmp_path, provider):
    library = tmp_path / "lib"
    library.mkdir()
    shutil.copyfile(ROOT / "bootstrap" / f"{provider}-create-new-aifactory-scaleset.sh",
                    tmp_path / "create.sh")
    shutil.copyfile(LIB / "layout_router.sh", library / "layout_router.sh")
    (library / "registered_creation.py").write_text(
        "import sys\n"
        "if '--select-layout' in sys.argv: print('registered')\n"
        "else: print('REGISTERED_ONLY:' + sys.argv[1]); sys.exit(17)\n", encoding="utf-8")
    (library / "create-new-aifactory-scaleset.sh").write_text(
        "printf 'FORBIDDEN_LEGACY\\n'; exit 99\n", encoding="utf-8")
    result = subprocess.run(
        [str(BASH), str(tmp_path / "create.sh"), "--repo-root", str(tmp_path / "consumer"),
         "--aifactory-version", "main", "--non-interactive", "--yes"],
        env=clean_env(), capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 17, result.stderr
    assert "REGISTERED_ONLY:" + provider.lower() in result.stdout
    assert "FORBIDDEN_LEGACY" not in result.stdout


@pytest.mark.skipif(not BASH, reason="Git Bash unavailable")
@pytest.mark.parametrize("provider", ["GHA", "ADO"])
def test_explicit_124_wrapper_retains_legacy_route(tmp_path, provider):
    library = tmp_path / "lib"
    library.mkdir()
    shutil.copyfile(ROOT / "bootstrap" / f"{provider}-create-new-aifactory-scaleset.sh",
                    tmp_path / "create.sh")
    for name in ("layout_router.sh", "registered_creation.py", "release_version.py"):
        shutil.copyfile(LIB / name, library / name)
    (library / "create-new-aifactory-scaleset.sh").write_text(
        'aif_scaleset_main() { printf "LEGACY_ONLY:%s\\n" "$1"; return 17; }\n', encoding="utf-8")
    result = subprocess.run(
        [str(BASH), str(tmp_path / "create.sh"), "--repo-root", str(tmp_path / "consumer"),
         "--aifactory-version", "124", "--non-interactive", "--yes"],
        env=clean_env(), capture_output=True, text=True, timeout=30)
    assert result.returncode == 17, result.stderr
    assert result.stdout.strip() == "LEGACY_ONLY:" + provider.lower()
    assert not (tmp_path / "consumer").exists()


@pytest.fixture(scope="module")
def live_creation_api(tmp_path_factory):
    repository = os.environ.get("AZUREFACTORY_TEST_API_REPO")
    if not repository:
        pytest.skip("Set AZUREFACTORY_TEST_API_REPO for real authenticated sidecar integration.")
    repository = Path(repository)
    python = repository / ".venv" / "Scripts" / "python.exe"
    assert python.is_file() and (repository / "src" / "api_sidecar.py").is_file()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    key = str(uuid4())
    folder = tmp_path_factory.mktemp("live-creation-api")
    assert not folder.is_relative_to(ROOT), "Use --basetemp outside the source checkout."
    environment = clean_env(AIFACTORY_API_KEY=key, AIFACTORY_API_URL=base_url)
    log_path = folder / "sidecar.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [str(python), "-B", "-m", "src.api_sidecar", "--port", str(port)],
            cwd=repository, env=environment, stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(120):
                assert process.poll() is None, log_path.read_text(encoding="utf-8")
                try:
                    with urlopen(Request(base_url + "/openapi.json", headers={"X-API-Key": key}), timeout=1) as response:
                        assert "/api/v1/creation/prepare" in json.load(response)["paths"]
                    break
                except (URLError, TimeoutError):
                    time.sleep(0.25)
            else:
                pytest.fail("Sidecar was not responsive: " + log_path.read_text(encoding="utf-8"))
            with pytest.raises(HTTPError) as denied:
                urlopen(Request(base_url + "/api/v1/creation/prepare", data=b"{}",
                                headers={"Content-Type": "application/json"}), timeout=5)
            assert denied.value.code in (401, 403)
            yield environment
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.mark.skipif(not BASH, reason="Git Bash unavailable")
@pytest.mark.parametrize("provider,simple,project,version,entrypoint,hub", [
    ("gha", True, None, None, "wrapper", None),
    ("gha", True, "003", "main", "wrapper", None),
    ("gha", False, None, "1.25", "wrapper", None),
    ("gha", False, "003", "main", "wrapper", None),
    ("ado", False, None, None, "wrapper", None),
    ("ado", False, "003", "1.25", "wrapper", None),
    ("gha", True, None, None, "raw", None),
    ("gha", True, "003", "main", "raw", None),
    ("gha", False, None, "1.25", "raw", None),
    ("gha", False, "003", "main", "raw", None),
    ("ado", False, None, None, "raw", None),
    ("ado", False, "003", "1.25", "raw", None),
    ("gha", False, "003", "1.25", "dispatcher", None),
    ("ado", False, None, "1.25", "dispatcher-env", None),
    ("gha", True, None, "main", "wrapper", "false"),
    ("gha", True, None, "1.25", "wrapper", "false"),
    ("gha", True, "003", "main", "raw", "false"),
    ("gha", True, "003", "1.25", "raw", "false"),
])
def test_live_bash_prepare_then_separate_cli_confirmation(
        tmp_path, live_creation_api, provider, simple, project, version, entrypoint, hub):
    root = tmp_path / "consumer"
    root.mkdir()
    receipt = tmp_path / "creation-review.json"
    environment = {**live_creation_api, **input_env(provider, simple)}
    if hub is not None:
        environment["AIF_SETUP_HUB_ACCESS"] = hub
    if project:
        environment["AIF_PROJECT_NUMBER"] = project
    arguments = ["--repo-root", str(root), "--non-interactive", "--yes", "--save-receipt", str(receipt)]
    if version:
        arguments += ["--aifactory-version", version]
    if entrypoint == "raw":
        command = [str(BASH), "--noprofile", "--norc", "-c",
                   'source bootstrap/lib/create-new-aifactory-scaleset.sh; '
                   f'aif_scaleset_main {provider} "$PWD/bootstrap/{provider.upper()}-create-new-aifactory-scaleset.sh" "$@"',
                   "raw-create", *arguments]
    else:
        name = f"{provider.upper()}-create-new-aifactory-scaleset.sh"
        if entrypoint.startswith("dispatcher"):
            name = "ALL-create-new-aifactory-scaleset.sh"
            if entrypoint == "dispatcher-env":
                environment["AIF_ORCHESTRATOR"] = provider
            else:
                arguments = ["--orchestrator", provider, *arguments]
        command = [str(BASH), str(ROOT / "bootstrap" / name), *arguments]
    prepared = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=60)
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    saved = json.loads(receipt.read_text(encoding="utf-8"))
    expected = project or "001"
    assert saved["purpose"] == "catalog-confirm" and saved["operation"] == "factory-create"
    assert saved["request"]["mode"] == ("simple" if simple else "full-bootstrap")
    assert ("setup_hub_access" in saved["request"]["config"]) == (hub is not None)
    if hub is not None:
        assert saved["request"]["config"]["setup_hub_access"] is False
    if simple:
        assert "project_number" not in saved["request"]["config"]
        assert saved["request"].get("initial_project", {}).get("number") == project
    else:
        assert saved["request"]["config"].get("project_number") == project
    assert saved["preview"]["target"]["projects"][0]["number"] == expected
    assert saved["preview"]["target"]["version_ref"] == ("125" if version == "1.25" else "main")
    assert saved["preview"]["deferred_fields"]
    assert not (root / "azurefactory" / "register.json").exists()
    assert not list(root.rglob("variables.json")), "--yes must never auto-confirm preparation"
    assert environment["AIFACTORY_API_KEY"] not in receipt.read_text(encoding="utf-8")
    if entrypoint == "raw":
        retry = tmp_path / "creation-review-retry.json"
        retried = subprocess.run(
            [str(retry) if argument == str(receipt) else argument for argument in command],
            cwd=ROOT, env=environment, capture_output=True, text=True, timeout=60)
        assert retried.returncode == 0, retried.stdout + retried.stderr
        reviewed = json.loads(retry.read_text(encoding="utf-8"))
        assert reviewed["preview"]["confirmation_id"] != saved["preview"]["confirmation_id"]
        assert [item["number"] for item in reviewed["preview"]["target"]["projects"]] == [expected]
        assert not list(root.rglob("variables.json"))
        receipt = retry

    def cli(*arguments):
        result = subprocess.run(
            [str(BASH), str(ROOT / "bootstrap" / "azurefactory.sh"), *arguments],
            env=environment, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)

    confirmed = cli("catalog", "confirm", "--receipt", str(receipt), "--yes")
    assert confirmed["job"] is None
    register = json.loads((root / "azurefactory" / "register.json").read_text(encoding="utf-8"))
    factory = register["factories"][0]
    assert len(register["factories"]) == 1
    assert [item["number"] for item in factory["projects"]] == [expected]
    assert factory["aifactory_version"] == ("125" if version == "1.25" else "main")
    assert factory["scale_sets"][0]["orchestrator"] == provider
    assert factory["scale_sets"][0]["tenant_id"] == environment["AIF_TENANT_ID"]
    assert factory["scale_sets"][0]["subscription_id"] == environment["AIF_DEV_SUBSCRIPTION_ID"]
    variables = list(root.rglob("variables.json"))
    assert len(variables) == 1
    assert variables[0].parent.name == "project" + expected
    assert variables[0].relative_to(root).parts[:2] == ("azurefactory", "factories")
    sections = json.loads(variables[0].read_text(encoding="utf-8"))
    assert len(sections) == 2
    for section in sections.values():
        assert section["enableAIFactoryHub"] is (hub is None)
        assert section["centralDnsZoneByPolicyInHub"] is False
    dev = sections["dev"]
    assert dev["project_number_000"] == expected
    assert dev["tenantId"] == environment["AIF_TENANT_ID"]
    assert dev["dev_sub_id"] == environment["AIF_DEV_SUBSCRIPTION_ID"]
    assert dev["admin_aifactoryPrefixRG"] == environment["AIF_PREFIX"]
    assert dev["admin_location"] == environment["AIF_LOCATION"]
    assert dev["aifactory_branch_chosen"] == ("release/v1.25" if version == "1.25" else "main")
    if version == "1.25":
        assert (dev["aifactory_version_major"], dev["aifactory_version_minor"]) == ("1", "25")
    if simple:
        assert dev["enableAIFoundry"] == "true"
        assert dev["enableAdminVM"] == "false"
    assert not (root / "aifactory").exists()
    jobs = cli("catalog", "jobs", "--folder", str(root / "azurefactory"))["jobs"]
    assert jobs == []
    (tmp_path / "verified-result.json").write_text(json.dumps({
        "provider": provider, "mode": saved["request"]["mode"], "entrypoint": entrypoint,
        "project": expected, "version": factory["aifactory_version"], "job": confirmed["job"],
        "jobs": jobs, "variables": str(variables[0]), "pending_retry": entrypoint == "raw",
    }, indent=2), encoding="utf-8")
    print(f"LIVE {provider} {'simple' if simple else 'full'} {entrypoint}: "
          f"project{expected}, {factory['aifactory_version']}, job=null, jobs=[], {variables[0]}")
