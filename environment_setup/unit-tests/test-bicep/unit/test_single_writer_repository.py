"""Single-writer repository initialization uses private, exactly pinned assets."""

import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from unit.test_prefix_bootstrap import repository, workspace, no_live


def scope_of(consumer, provider="gha"):
    path = consumer / "azurefactory" / "register.json"
    document = json.loads(path.read_bytes())
    document["factories"][0]["scale_sets"][0]["orchestrator"] = provider
    path.write_bytes(repository.enrollment.canonical(document))
    return {"factory_id": document["factories"][0]["id"],
            "scale_set_id": document["factories"][0]["scale_sets"][0]["id"]}


@pytest.mark.parametrize("provider", ["gha", "ado"])
@pytest.mark.parametrize("missing", [None, "lib/provider_repository_state.py", "lib/factory_lifecycle.py", "lib/factory_enrollment.py"])
def test_mode_assets_pin_all_native_runtime_dependencies(monkeypatch, provider, missing):
    runtime = object.__new__(repository.Repository)
    runtime.provider, runtime.config = provider, {"coordination_mode": "single-writer"}
    root = Path(repository.__file__).parent.parent
    relatives = ["lib/common_network_preservation.py", "lib/provider_repository_state.py",
                 "lib/factory_enrollment.py", "lib/factory_lifecycle.py",
                 "templates/factory-lifecycle-single-writer-" + provider + ".yml"]
    files = []
    for relative in relatives:
        if relative != missing:
            data = (root / relative).read_bytes()
            files.append({"path": "bootstrap/" + relative, "type": "blob",
                          "sha": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()})
    monkeypatch.setattr(repository, "urlopen", lambda request, timeout:
                        io.BytesIO(repository.enrollment.canonical({"sha": "a" * 40, "truncated": False, "tree": files})))
    if missing:
        with pytest.raises(repository.enrollment.EnrollmentError, match="lacks-prefix-bootstrap"):
            runtime.source_assets("a" * 40)
    else:
        assets = runtime.source_assets("a" * 40)
        assert set(assets) == {"bootstrap/" + name for name in relatives}
        assert not any("hub_private" in name for name in assets)


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_public_repository_or_project_blocks_before_initialization(workspace, provider):
    consumer = workspace[0]
    scope = scope_of(consumer, provider)
    config = ({"github_repository": "example/factory", "github_visibility": "public"} if provider == "gha" else
              {"ado_organization": "https://dev.azure.com/org", "ado_project": "project", "ado_repository": "repo"})
    runtime = SimpleNamespace(discover=lambda: None,
                              private_project=lambda: repository.enrollment.require(False, "single-writer-private-repository-required"))
    before = (consumer / "azurefactory" / "register.json").read_bytes()
    with pytest.raises(repository.enrollment.EnrollmentError, match="private-repository-required"):
        repository.prepare(consumer_root=consumer, scope=scope, expected_revision="reviewed",
                           bootstrap_config=config | {"coordination_mode": "single-writer"}, runtime=runtime)
    assert (consumer / "azurefactory" / "register.json").read_bytes() == before
    assert not (consumer / ".git").exists()


def test_ado_private_project_check_uses_selected_project_and_ado_tenant():
    runtime = object.__new__(repository.Repository)
    runtime.provider = "ado"
    runtime.config = {"ado_organization": "https://dev.azure.com/org", "ado_project": "project", "ado_tenant_id": "ado-tenant"}
    runtime.target = {"tenant_id": "azure-tenant"}
    calls = []
    runtime.cloud = SimpleNamespace(http=lambda *args, **kwargs:
                                    (calls.append((args, kwargs)) or (200, {}, {"id": "selected", "name": "project", "visibility": "private"})))
    assert runtime.private_project()["visibility"] == "private"
    assert calls == [(("GET", "https://dev.azure.com/org/_apis/projects/project?api-version=7.1", repository.enrollment.ADO_AUDIENCE),
                      {"tenant": "ado-tenant"})]


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_single_writer_execute_selects_only_mode_template_and_preserves_register(workspace, provider):
    consumer, state = workspace[0], workspace[1]
    scope = scope_of(consumer, provider)
    saved = (consumer / "azurefactory" / "register.json").read_bytes()
    config = ({"github_repository": "example/factory"} if provider == "gha" else
              {"ado_organization": "https://dev.azure.com/org", "ado_project": "project", "ado_repository": "repo"})
    relative = "bootstrap/templates/factory-lifecycle-single-writer-" + provider + ".yml"
    content = b"# AIFACTORY_SINGLE_WRITER_CONTRACT=provider-repository-cas-v1\nreviewed: true\n"
    assets = {relative: hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()}
    refs, remote, calls = {}, {}, []

    def git(root, *args, **kwargs):
        calls.append(args)
        if args[0] == "ls-remote":
            sha = "b" * 40 if args[1] == repository.SHARED_URL else refs.get(args[2])
            return sha + "\t" + args[2] if sha else ""
        if args[0] == "init":
            (root / ".git").mkdir()
        elif args[0] == "clone":
            Path(args[-1]).mkdir()
        elif args[0] == "rev-parse":
            return "b" * 40
        elif args[0] == "cat-file":
            assert args[2].split(":", 1)[1] == relative
            return content
        elif args[0] in ("hash-object", "write-tree"):
            return "c" * 40
        elif args[0] == "commit-tree":
            return ("e" if "-p" in args else "d") * 40
        elif args[0] == "push":
            sha, ref = args[-1].split(":", 1)
            refs[ref] = sha
        return ""

    runtime = SimpleNamespace(discover=lambda: remote or None, source_assets=lambda sha: assets,
                              private_project=lambda: {"id": "project", "name": "project", "visibility": "private"},
                              pipeline=lambda remote: None, ensure_pipeline=lambda: {"id": 9},
                              git=git, create=lambda: remote.update(id=7, private=True, project={"visibility": "private"}),
                              set_initial_default_branch=lambda: None, ensure_environment=lambda name, expected: {"name": name})
    plan = repository.prepare(consumer_root=consumer, scope=scope, expected_revision="reviewed",
                              bootstrap_config=config | {"coordination_mode": "single-writer"}, runtime=runtime)
    assert any("private repository" in warning for warning in plan["warnings"])
    if provider == "gha":
        assert plan["auth_namespace"] == "aifactory-" + repository.enrollment.digest({
            "repository": plan["repository"].lower(), "provider": "gha", "coordination_mode": "single-writer"})[:20]
    result = repository.execute(plan, state_dir=state, runtime=runtime)
    assert result["status"] == "succeeded", result
    target = ".github/workflows/factory-lifecycle.yml" if provider == "gha" else "aifactory/pipelines/factory-lifecycle.yml"
    assert (consumer / target).read_bytes() == content
    assert not (consumer / ".azurefactory" / "hub_private_probe.py").exists()
    assert (consumer / "azurefactory" / "register.json").read_bytes() == saved
    assert not any("register.json" in " ".join(args) for args in calls)
