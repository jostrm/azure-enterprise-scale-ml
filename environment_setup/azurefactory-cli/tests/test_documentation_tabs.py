"""Offline checks for the shared documentation source and native tool views."""

import ast
import importlib.util
from pathlib import Path
import re
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[3]
DOCS = ROOT / "documentation" / "v2" / "10-19"
LABELS = ["CLI (PowerShell)", "Python SDK", "REST (curl)"]


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
    assert [file.src_uri for file in files] == ["factory-tools/" + name for name in hook.GUIDES]
    assert all('=== "Python SDK"' in file.content_string for file in files)
    assert "content.tabs.link" in config.theme["features"]
    navigation = next(section["Factory tools"] for section in config.nav if "Factory tools" in section)
    assert [next(iter(page.values())) for page in navigation] == [file.src_uri for file in files]
    with pytest.raises(ValueError, match="duplicate"):
        config.plugins.on_files(files, config=config)


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
