"""Offline checks for the shared documentation source and native tool views."""

import ast
import importlib.util
import json
from pathlib import Path
import re
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[3]
DOCS = ROOT / "documentation" / "v2" / "10-19"
LABELS = ["CLI (PowerShell)", "Python SDK", "REST (curl)"]
CORE_TEAM = "Get started - CLI, SDK, API: Core team"
PROJECT_TEAM = "Get started - Agent & ML Factory SDK: Project team"


def load_hook():
    pytest.importorskip("mkdocs")
    spec = importlib.util.spec_from_file_location("factory_guide_hook",
        ROOT / "documentation" / "gh-io" / "tools" / "factory_guides.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    return hook


def guide_tabs(text):
    sections = re.findall(
        r'^<details markdown="1" data-factory-tool="([^"]+)">\n'
        r'<summary>\1</summary>\n\n(.*?)^</details>\n<!-- /factory-tool -->', text, flags=re.M | re.S)
    assert [label for label, _ in sections] == LABELS
    return dict(sections)


@pytest.mark.parametrize("number", [18, 19, 20])
def test_guides_have_one_complete_native_tool_selector(number):
    text = (DOCS / f"{number}-cli-and-api-and-usage.md").read_text(encoding="utf-8")
    tabs = guide_tabs(text)
    for label, content in tabs.items():
        assert not re.search(r'^\s*=== "', content, flags=re.M)
        assert content.count("```") % 2 == 0
    python = tabs["Python SDK"]
    # Everything until the first unindented following heading/details belongs to this tab.
    assert "```python" in python
    assert "```powershell" not in python and not re.search(r"^\s*@'\s*$", python, re.M) and "'@ |" not in python
    for block in re.findall(r"(?ms)^```python\n(.*?)^```", python):
        ast.parse(textwrap.dedent(block))
    rest = tabs["REST (curl)"]
    assert "curl" in rest
    assert "```python" not in rest and not re.search(r"^\s*@'\s*$", rest, re.M)


def test_site_hook_rewrites_only_document_links(tmp_path):
    pytest.importorskip("mkdocs")
    spec = importlib.util.spec_from_file_location("factory_guide_hook",
        ROOT / "documentation" / "gh-io" / "tools" / "factory_guides.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    source = tmp_path / "documentation" / "v2" / "10-19" / hook.GUIDES[0]
    original = (
        "[next](19-cli-and-api-and-usage.md#example)\n"
        "[source](../../../environment_setup/azurefactory-cli/readme.md#sdk)\n"
        "[external](https://example.com/path)\n"
        "    ```python\n"
        "    value = '[not a link](relative-file)'\n"
        "    ```\n"
    )
    result = hook.site_markdown(original, source, tmp_path)
    assert "[next](19-cli-and-api-and-usage.md#example)" in result
    assert hook.GITHUB + "environment_setup/azurefactory-cli/readme.md#sdk" in result
    assert "[external](https://example.com/path)" in result
    assert "value = '[not a link](relative-file)'" in result


def test_site_hook_adds_all_guides_to_mkdocs_navigation():
    pytest.importorskip("mkdocs")
    from mkdocs.config import load_config
    from mkdocs.structure.files import Files

    site = ROOT / "documentation" / "gh-io"
    spec = importlib.util.spec_from_file_location("factory_guide_site", site / "tools" / "factory_guides.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    config = load_config(str(site / "mkdocs.yml"))
    files = config.plugins.on_files(Files([]), config=config)
    core_uris = ["factory-tools/" + name for name in hook.GUIDES]
    project_uris = ["project-team/index.md", *hook.PROJECT_GUIDES]
    assert [file.src_uri for file in files] == core_uris + project_uris
    assert all('=== "Python SDK"' in files.get_file_from_path(uri).content_string for uri in core_uris)
    assert "content.tabs.link" in config.theme["features"]
    navigation = next(section[CORE_TEAM] for section in config.nav if CORE_TEAM in section)
    assert [next(iter(page.values())) for page in navigation] == core_uris
    projects = next(section[PROJECT_TEAM] for section in config.nav if PROJECT_TEAM in section)
    assert [next(iter(page.values())) for page in projects] == project_uris
    home = (site / "docs" / "index.md").read_text(encoding="utf-8")
    assert CORE_TEAM in home and PROJECT_TEAM in home
    assert "(project-team/index.md)" in home
    for uri, source in hook.PROJECT_GUIDES.items():
        excerpt = hook.project_excerpt(source.read_text(encoding="utf-8"))
        generated = files.get_file_from_path(uri).content_string
        assert hook.site_markdown(excerpt, source) in generated
        assert hook.GITHUB + source.relative_to(ROOT).as_posix() in generated
        assert not (site / "docs" / uri).exists()
        assert "```python" in generated and "```powershell" in generated
        assert "@' " not in generated and "'@ |" not in generated
        for block in re.findall(r"(?ms)^```python\n(.*?)^```", generated):
            ast.parse(textwrap.dedent(block))
    assert "Agent Factory" in files.get_file_from_path(project_uris[0]).content_string
    assert "ML Model Factory" in files.get_file_from_path(project_uris[0]).content_string
    with pytest.raises(ValueError, match="duplicate"):
        config.plugins.on_files(files, config=config)


def test_project_source_links_keep_site_anchors_and_full_source_links():
    hook = load_hook()
    source = hook.PROJECT_GUIDES["project-team/agent-factory.md"]
    text = (
        "[ML SDK](../../50-ml-model-factory/user-config/readme.md#project-team-quickstart)\n"
        "[full configuration](../../50-ml-model-factory/user-config/readme.md#what-to-configure)\n"
        "[core tools](../../../documentation/v2/10-19/18-cli-and-api-and-usage.md#quickstart)\n"
        "[file](catalog.py#agent_catalog)\n"
        "```python\n"
        "value = '[not a link](catalog.py#agent_catalog)'\n"
        "```\n"
    )
    result = hook.site_markdown(text, source)
    assert "[ML SDK](ml-model-factory.md#project-team-quickstart)" in result
    assert hook.GITHUB + "usecase_code/50-ml-model-factory/user-config/readme.md#what-to-configure" in result
    assert "[core tools](../factory-tools/18-cli-and-api-and-usage.md#quickstart)" in result
    assert hook.GITHUB + "usecase_code/40-agent-factory/agent_factory/catalog.py#agent_catalog" in result
    assert "value = '[not a link](catalog.py#agent_catalog)'" in result


def test_project_guide_relative_links_reference_current_sources():
    hook = load_hook()
    for source in hook.PROJECT_GUIDES.values():
        text = hook.project_excerpt(source.read_text(encoding="utf-8"))
        for match in hook.LINK.finditer(text):
            location = match[2].partition("#")[0]
            if location and not location.startswith(("https://", "http://", "/")):
                assert (source.parent / location).exists(), (source, location)


def test_project_catalog_python_examples_run_offline(monkeypatch, capsys):
    hook = load_hook()
    component_roots = [
        ROOT / "usecase_code" / "40-agent-factory",
        ROOT / "usecase_code" / "50-ml-model-factory",
    ]
    monkeypatch.syspath_prepend(str(component_roots[0]))
    monkeypatch.syspath_prepend(str(component_roots[1] / "accelerator" / "src"))
    for source, working_directory in zip(hook.PROJECT_GUIDES.values(), component_roots):
        text = hook.project_excerpt(source.read_text(encoding="utf-8"))
        blocks = re.findall(r"(?ms)^```python\n(.*?)^```", text)
        monkeypatch.chdir(working_directory)
        exec(compile(blocks[0], str(source), "exec"), {})
        output = capsys.readouterr().out
        assert output and "private-test-key" not in output


def test_agent_python_plan_stays_offline_and_selects_one_target(monkeypatch, tmp_path, capsys):
    hook = load_hook()
    monkeypatch.syspath_prepend(str(ROOT / "usecase_code" / "40-agent-factory"))
    import agent_factory.cli

    variables = {
        "tenantId": "11111111-1111-1111-1111-111111111111",
        "dev_sub_id": "22222222-2222-2222-2222-222222222222",
        "project_number_000": "001", "admin_aifactoryPrefixRG": "",
        "admin_aifactorySuffixRG": "-001", "admin_locationSuffix": "test",
        "projectPrefix": "", "projectSuffix": "", "vnetResourceGroupBase": "common",
    }
    (tmp_path / "variables.json").write_text(json.dumps({"dev": variables}), encoding="utf-8")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"targets": [
        {"key": key, "variables_file": "variables.json", "environment": "dev"}
        for key in ("first", "second")
    ]}), encoding="utf-8")
    answers = iter([str(config_path), "second"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    def no_cloud(*args, **kwargs):
        pytest.fail("The documented offline plan attempted Azure authentication.")

    monkeypatch.setattr(agent_factory.cli, "AzureSession", no_cloud)
    source = hook.PROJECT_GUIDES["project-team/agent-factory.md"]
    text = hook.project_excerpt(source.read_text(encoding="utf-8"))
    block = re.findall(r"(?ms)^```python\n(.*?)^```", text)[1]
    namespace = {}
    exec(compile(block, str(source), "exec"), namespace)
    assert namespace["arguments"].target == "second"
    assert json.loads(capsys.readouterr().out)["mutations"] is False


@pytest.mark.parametrize("text", [
    "no markers",
    "<!-- project-team:start -->\nmissing end",
    "<!-- project-team:end -->\n<!-- project-team:start -->",
    "<!-- project-team:start -->\na\n<!-- project-team:end -->\n<!-- project-team:end -->",
])
def test_project_excerpt_rejects_missing_or_ambiguous_source(text):
    hook = load_hook()
    with pytest.raises(ValueError, match="project-team"):
        hook.project_excerpt(text)


def test_smoke_python_example_never_submits_changes():
    path = ROOT / "environment_setup" / "install_config_wizard" / "api-usage-examples" / "python" / "factory_smoke.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls = {node.func.attr for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and isinstance(node.func.value, ast.Name) and node.func.value.id == "client"}
    assert calls == {"health", "catalog_list"}


def test_smoke_python_file_runs_independently_without_shell_state(monkeypatch, tmp_path, capsys):
    import azurefactory
    import sys

    path = ROOT / "environment_setup" / "install_config_wizard" / "api-usage-examples" / "python" / "factory_smoke.py"
    spec = importlib.util.spec_from_file_location("factory_smoke_example", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    answers = iter([str(ROOT), ""])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(module.getpass, "getpass", lambda _: "private-test-key")
    monkeypatch.setattr(module.tempfile, "mkdtemp", lambda **_: str(tmp_path))
    monkeypatch.setattr(sys, "path", list(sys.path))
    calls = []

    class Client:
        def __init__(self, *, base_url, api_key):
            assert base_url == "http://127.0.0.1:8876"
            assert api_key == "private-test-key"

        def health(self):
            calls.append("health")
            return {"status": "ok"}

        def catalog_list(self, folder):
            calls.append("catalog_list")
            assert Path(folder) == tmp_path / "azurefactory"
            assert Path(folder).is_dir() and not list(Path(folder).iterdir())
            return {"factories": []}

    monkeypatch.setattr(azurefactory, "AzureFactoryClient", Client)
    module.main()
    assert calls == ["health", "catalog_list"]
    output = capsys.readouterr().out
    assert '"factories": []' in output and "private-test-key" not in output
