"""The docs site publishes the end-user docs from their single source in documentation/v2."""

import fnmatch
import importlib.util
from pathlib import Path
import posixpath
import re

import pytest

pytest.importorskip("mkdocs")

ROOT = Path(__file__).resolve().parents[3]
V2 = ROOT / "documentation" / "v2"
SITE = ROOT / "documentation" / "gh-io"
SETUP = "Setup docs: Platform team"
USAGE = "Usage docs: Project team"
EXTERNAL = re.compile(r"(?:[A-Za-z][A-Za-z0-9+.-]*:|#|/)")


@pytest.fixture(scope="module")
def site():
    from mkdocs.config import load_config
    from mkdocs.structure.files import Files

    spec = importlib.util.spec_from_file_location("factory_guide_docs", SITE / "tools" / "factory_guides.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    config = load_config(str(SITE / "mkdocs.yml"))
    files = config.plugins.on_files(Files([]), config=config)
    return hook, config, files


def page(site, uri):
    return site[2].get_file_from_path(uri).content_string


def navigation(entries):
    for entry in entries:
        if isinstance(entry, str):
            yield entry
        elif isinstance(entry, dict):
            for value in entry.values():
                yield from navigation(value if isinstance(value, list) else [value])


def test_site_publishes_every_setup_and_usage_page_from_its_single_source(site):
    hook, _, files = site
    sources = {source.resolve() for source in hook.DOCS_PAGES.values()}
    for folder in ("quickstarts", "usage"):
        for source in (V2 / folder).glob("*.md"):
            assert source.resolve() in sources, f"{source.name} is not published on the site"
    for uri, source in hook.DOCS_PAGES.items():
        assert source.exists() and files.get_file_from_path(uri) is not None, uri
        assert not (SITE / "docs" / uri).exists(), f"{uri} must not have a second copy in the site folder"


def test_site_navigation_lists_every_published_docs_page(site):
    hook, config, _ = site
    listed = set(navigation(config.nav))
    assert set(hook.DOCS_PAGES) <= listed
    setup = next(section[SETUP] for section in config.nav if SETUP in section)
    assert [next(iter(entry.values())) for entry in setup] == [
        uri for uri in hook.DOCS_PAGES if uri.startswith("setup/")]
    assert any(USAGE in section for section in config.nav)
    home = (SITE / "docs" / "index.md").read_text(encoding="utf-8")
    assert "(setup/index.md)" in home and "(usage/index.md)" in home and "(parameters/variables.md)" in home


def test_quickstart_renders_tabs_options_and_alerts_the_site_way(site):
    content = page(site, "setup/02-create-factory.md")
    for label in ("App", "CLI (PowerShell)", "CLI (bash)", "Python SDK", "REST (curl)"):
        assert f'=== "{label}"' in content
    assert "data-factory-tool" not in content and "<details" not in content and "</details>" not in content
    assert '???+ note "In a file: automated networking"' in content
    assert '??? note "In a file: BYO VNet"' in content and '??? note "In the app: Full bootstrap"' in content
    assert "!!! tip" in content and "!!! warning" in content and "[!TIP]" not in content
    assert not content.lstrip().startswith("[Docs]("), "The site has its own navigation; no breadcrumb line."
    assert "(add-scale-set.md#use-your-own-vnet-or-subnets)" in content
    assert "(../reference/hub-and-network-modes.md" in content
    assert "```mermaid" in content


def test_every_link_and_image_on_a_published_page_resolves(site):
    hook, _, files = site
    known = {file.src_uri for file in files} | {
        path.relative_to(SITE / "docs").as_posix() for path in (SITE / "docs").rglob("*") if path.is_file()}
    broken = []
    for uri in hook.DOCS_PAGES:
        content = re.sub(r"(?ms)^[ \t]*(`{3,}).*?^[ \t]*\1[ \t]*$", "", page(site, uri))
        content = re.sub(r"`[^`\n]*`", "", content)
        urls = re.findall(r"\]\(([^)\s]+)\)", content) + re.findall(r'(?:src|href|srcset)="([^"]+)"', content)
        for url in urls:
            if EXTERNAL.match(url):
                continue
            target = posixpath.normpath(posixpath.join(posixpath.dirname(uri), url.partition("#")[0]))
            if target not in known:
                broken.append(f"{uri}: {url}")
    assert not broken, broken


def test_site_ships_the_images_the_pages_show(site):
    hook, _, files = site
    assets = [file for file in files if file.src_uri.startswith(hook.ASSETS)]
    assert assets, "Images are copied into the site, so a page never depends on another host."
    for file in assets:
        assert Path(file.abs_src_path).exists(), file.src_uri
    assert "assets/" in page(site, "setup/index.md") and "raw.githubusercontent.com" not in page(site, "setup/index.md")


def test_site_renders_mermaid_diagrams(site):
    _, config, _ = site
    fences = config.mdx_configs.get("pymdownx.superfences", {}).get("custom_fences", [])
    assert any(fence.get("name") == "mermaid" for fence in fences)


def test_pages_workflow_rebuilds_the_site_when_a_docs_page_changes(site):
    import yaml

    hook = site[0]
    workflow = yaml.load((ROOT / ".github" / "workflows" / "deploy-docs.yml").read_text(encoding="utf-8"),
                         Loader=yaml.BaseLoader)
    paths = workflow["on"]["push"]["paths"]
    for source in hook.DOCS_PAGES.values():
        relative = source.relative_to(ROOT).as_posix()
        assert any(fnmatch.fnmatchcase(relative, pattern) for pattern in paths), relative
    commands = [step.get("run", "") for step in workflow["jobs"]["deploy"]["steps"]]
    assert any("test_documentation_site.py" in command for command in commands)
