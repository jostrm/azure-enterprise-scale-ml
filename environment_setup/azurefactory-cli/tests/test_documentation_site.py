"""The docs site publishes the end-user docs from their single source in documentation/v2."""

import fnmatch
import html
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
        # MkDocs rewrites Markdown links, which are relative to the source page. It leaves HTML attributes alone,
        # and the browser resolves those against the page's URL folder: setup/02-create-factory/ for that page.
        folder = posixpath.dirname(uri)
        url_folder = folder if posixpath.basename(uri) == "index.md" else uri[:-len(".md")]
        for base, urls in ((folder, re.findall(r"\]\(([^)\s]+)\)", content)),
                           (url_folder, re.findall(r'(?:src|href|srcset)="([^"]+)"', content))):
            for url in urls:
                if EXTERNAL.match(url):
                    continue
                target = posixpath.normpath(posixpath.join(base, url.partition("#")[0]))
                page_urls = {target + ".md", posixpath.join(target, "index.md").lstrip("./")}
                if target not in known and not (base == url_folder and page_urls & known):
                    broken.append(f"{uri}: {url}")
    assert not broken, broken


def test_html_urls_resolve_from_the_page_url_folder(site, tmp_path):
    hook = site[0]
    source = hook.DOCS_PAGES["setup/02-create-factory.md"]
    html = '<a href="add-scale-set.md#x"><img src="../images/videos/02-create-factory.png" alt="a"></a>'
    result = hook.site_html(html, source, assets={})
    assert 'src="../../assets/repository/documentation/v2/images/videos/02-create-factory.png"' in result
    assert 'href="../add-scale-set/#x"' in result
    hub = hook.DOCS_PAGES["setup/index.md"]
    assert 'href="01-install-esaf/"' in hook.site_html('<a href="01-install-esaf.md">x</a>', hub, assets={})


def test_diagram_text_is_readable_on_the_dark_boxes(site):
    _, config, _ = site
    sheet = next(name for name in config.extra_css if "diagrams" in name)
    css = (SITE / "docs" / sheet).read_text(encoding="utf-8")
    assert "--md-mermaid-label-fg-color: #ECF6FF" in css and "--md-mermaid-label-bg-color: #191919" in css


def test_site_ships_the_images_the_pages_show(site):
    hook, _, files = site
    assets = [file for file in files if file.src_uri.startswith(hook.ASSETS)]
    assert assets, "Images are copied into the site, so a page never depends on another host."
    for file in assets:
        assert Path(file.abs_src_path).exists(), file.src_uri
    assert "assets/" in page(site, "setup/index.md") and "raw.githubusercontent.com" not in page(site, "setup/index.md")


def test_site_header_carries_the_product_name(site):
    _, config, _ = site
    assert config.site_name == "Enterprise Scale Azure Factory"
    home = (SITE / "docs" / "index.md").read_text(encoding="utf-8")
    assert "![Enterprise Scale Azure Factory](assets/images/header.png)" in home
    assert "Enterprise Scale AI Factory" not in home
    # The repository README shows the same banner as the home page of the site.
    assert (V2 / "10-19" / "images" / "header.png").read_bytes() == (
        SITE / "docs" / "assets" / "images" / "header.png").read_bytes()


def test_site_renders_mermaid_diagrams(site):
    _, config, _ = site
    fences = config.mdx_configs.get("pymdownx.superfences", {}).get("custom_fences", [])
    assert any(fence.get("name") == "mermaid" for fence in fences)


def tool(name):
    spec = importlib.util.spec_from_file_location(f"site_tool_{name}", SITE / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def published_pages(site):
    """Every Markdown page of the site as the reader gets it: the hand-written ones and the generated ones."""
    for path in sorted((SITE / "docs").rglob("*.md")):
        yield path.relative_to(SITE / "docs").as_posix(), path.read_text(encoding="utf-8")
    for file in site[2]:
        if file.src_uri.endswith(".md"):
            yield file.src_uri, file.content_string


# One project type exists today: a project with the services its team switches on. These names are gone.
LEGACY_TERMS = ("ESML project", "GenAI project", "ESML or GenAI", "ESGenAI", "infrastructure families",
                "two project types", "GenAI-1")
# Wording that answers the author of the page instead of helping its reader: defensive disclaimers about what a
# sentence does not claim, and notes about the repository the page was written in.
PROMPTER_WORDING = tuple(re.compile(pattern, re.I) for pattern in (
    r"commercial SKU", r"product SKU", r"\bcertif(?:y|ies|ication)\b", r"\bblanket\b", r"\bproof\b", r"\bproves?\b",
    r"\bdo(?: not|n't) assume\b", r"\bguarantee", r"\bpromise\b", r"self-aware", r"\baddend(?:a|um)\b", r"\bmerely\b",
    r"\bsilently\b", r"historical examples", r"source branch", r"deployment evidence",
    r"\b(?:purple|orange|pink) (?:examples?|project|repo)", r"not a substitute", r"\binfer\b",
    r"general instruction", r"deletion approval", r"cleanup plan", r"must not be read", r"\bunpublished\b",
    r"local release", r"not a general", r"deployment-readiness",
))
# The three long tool tutorials are written for the core team and are checked by their own tests.
CORE_TEAM_TUTORIALS = "factory-tools/"


def test_site_has_no_retired_project_types(site):
    found = [f"{uri}: {term}" for uri, text in published_pages(site) for term in LEGACY_TERMS if term in text]
    assert not found, found


def test_site_speaks_to_the_reader_not_to_the_author_of_the_page(site):
    found = []
    for uri, text in published_pages(site):
        if uri.startswith(CORE_TEAM_TUTORIALS):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            found += [f"{uri}:{number}: {pattern.pattern}" for pattern in PROMPTER_WORDING if pattern.search(line)]
    assert not found, found


def test_delete_flag_is_described_as_the_switch_it_is(site):
    # The project pipeline runs the delete step only when the flag is true: 06b in Azure DevOps, 18 in GitHub Actions.
    templates = ROOT / "environment_setup" / "aifactory" / "bicep"
    script = (templates / "scripts" / "delete-services-if-disabled.sh").read_text(encoding="utf-8")
    assert '"$enableDeleteForDisabledResources" != "true"' in script and "NEVER" in script
    ado = (templates / "copy_to_local_settings" / "azure-devops" / "esml-yaml-pipelines" / "esml-infra-project" /
           "jobs" / "job-2-genai-services.yaml").read_text(encoding="utf-8")
    gha = (templates / "copy_to_local_settings" / "github-actions" / "infra-project-phase.yml").read_text(
        encoding="utf-8")
    assert "06b_Delete_Service_If_Not_Enabled_And_Exists" in ado and "eq(variables['enableDeleteForDisabledResources'], 'true')" in ado
    assert "18_Delete_Service_If_Not_Enabled_And_Exists" in gha
    # The site says the same thing in the three places a reader looks.
    docs = SITE / "docs"
    home = (docs / "index.md").read_text(encoding="utf-8")
    variables = (docs / "parameters" / "variables.md").read_text(encoding="utf-8")
    row = next(line for line in variables.splitlines() if line.startswith("| `enableDeleteForDisabledResources` |"))
    for text in (home, row, (docs / "parameters" / "index.md").read_text(encoding="utf-8")):
        assert "enableDeleteForDisabledResources" in text
        for words in ("deletes", "project resource group", "Key Vault", "purge"):
            assert words in text, words
    assert '`"true"`' in home and '`"false"`' in home


def test_code_templates_library_lists_only_templates_that_exist():
    library = tool("code_templates")
    data = library.load()
    templates = data["templates"]
    identifiers = [template["id"] for template in templates]
    assert len(identifiers) == len(set(identifiers))
    assert all(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", identifier) for identifier in identifiers)
    for template in templates:
        assert (ROOT / template["path"]).exists(), template["path"]
        assert (ROOT / template["readme"]).is_file(), template["readme"]
        assert template["factory"] in data["factories"], template["id"]
        assert template["tags"] and set(template["tags"]) <= set(data["tags"]), template["id"]
        assert template["services"] and set(template["services"]) <= set(data["services"]), template["id"]
        assert 20 <= len(template["summary"]) <= 200 and template["summary"].endswith("."), template["id"]
    numbers = sorted(template["number"] for template in templates if "number" in template)
    assert numbers == list(range(1, len(numbers) + 1)), "The numbers on the architecture images have no gaps."
    for template in (item for item in templates if "number" in item):
        assert template["place"] in data["places"], template["id"]
    # A new template folder has to be added to the library, or to "skipped" with the reason.
    listed = [template["path"] for template in templates]
    code = ROOT / "usecase_code"
    folders = [folder for folder in (code / "40-agent-factory").iterdir() if re.match(r"\d\d-", folder.name)]
    folders += [folder for folder in (code / "10-azure-function").iterdir() if re.match(r"\d\d_", folder.name)]
    folders += [folder for folder in code.iterdir() if re.match(r"\d\d-", folder.name)
                and folder.name not in ("00-install-prereqs", "10-azure-function", "40-agent-factory")]
    for folder in folders:
        name = folder.relative_to(ROOT).as_posix()
        assert folder.is_dir(), name
        assert name in data["skipped"] or any(path == name or path.startswith(name + "/") for path in listed), name
    for name in data["skipped"]:
        assert (ROOT / name).is_dir() and name not in listed, name


def test_code_templates_cards_use_compact_architecture_links():
    library = tool("code_templates")
    data = library.load()
    page = library.render(library.LIBRARY, data)
    labels = re.findall(r'<a href="\.\./architectures/#the-numbers-on-the-images">([^<]*)</a>', page)
    assert labels == ["architecture"] * sum("number" in template for template in data["templates"])


def test_code_templates_page_shows_every_template_with_filters(site):
    _, config, _ = site
    library = tool("code_templates")
    data = library.load()
    # MkDocs never publishes docs/templates/ (its default exclude), so the page lives in docs/code-templates/.
    assert not (SITE / "docs" / "templates").exists()
    source = (SITE / "docs" / "code-templates" / "index.md").read_text(encoding="utf-8")
    assert library.LIBRARY in source
    page = library.render(source, data)
    assert library.LIBRARY not in page
    for template in data["templates"]:
        assert f'id="{template["id"]}"' in page and html.escape(template["title"]) in page
        assert library.GITHUB_TREE + template["path"] in page
    for group, values in (("factory", data["factories"]), ("tag", data["tags"]), ("service", data["services"])):
        used = {value for template in data["templates"]
                for value in ([template["factory"]] if group == "factory" else template[group + "s"])}
        assert used == set(values), f"Every {group} filter matches at least one template, and none is missing."
        for value in values:
            assert f'type="checkbox" data-filter="{group}" data-value="{value}"' in page
    assert 'type="search"' in page
    assert {"Code templates library: Project team": "code-templates/index.md"} in config.nav
    script = next(name for name in config.extra_javascript if "libraries" in str(name))
    assert (SITE / "docs" / str(script)).is_file()
    home = (SITE / "docs" / "index.md").read_text(encoding="utf-8")
    assert "(code-templates/index.md)" in home and "(architectures.md)" in home


def test_azure_resource_library_lists_every_resource_a_setting_switches_on(site):
    import json

    _, config, _ = site
    library = tool("code_templates")
    data = library.load_resources()
    resources = data["resources"]
    identifiers = [resource["id"] for resource in resources]
    assert len(identifiers) == len(set(identifiers))
    variables = json.loads((ROOT / "environment_setup" / "aifactory" / "variables.json").read_text(
        encoding="utf-8-sig"))["dev"]
    bootstrap = (ROOT / "bootstrap" / "lib" / "aifactory_scaleset_config.py").read_text(encoding="utf-8")
    services = set(library.load()["services"])
    # The areas and categories are the ones of the repository README, plus Full stack across them.
    assert list(data["areas"]) == ["Architectures", "Connectivity and security", "Tools and automation"]
    categories = [category for members in data["areas"].values() for category in members] + [data["cross_category"]]
    assert data["cross_category"] == "Full stack" and len(categories) == len(set(categories))
    for resource in resources:
        assert resource["categories"] and set(resource["categories"]) <= set(categories), resource["id"]
        assert resource["categories"][0] != data["cross_category"], "Full stack is an extra category, never the only one."
        for setting in resource["settings"]:
            # A real key: in variables.json, or an input of the simple-mode bootstrap. Never an invented flag.
            assert setting in variables or (setting.startswith("AIF_") and setting in bootstrap), setting
        # A resource without a switch says what provides it instead.
        assert bool(resource["settings"]) != bool(resource.get("without_setting")), resource["id"]
        assert resource.get("template_service", next(iter(services))) in services, resource["id"]
        assert 20 <= len(resource["summary"]) <= 220 and resource["summary"].endswith("."), resource["id"]
    assert {category for resource in resources for category in resource["categories"]} == set(categories)
    # A new switch in variables.json has to be added to the library, or to "not_listed" with the reason.
    listed = {setting for resource in resources for setting in resource["settings"]}
    for key in variables:
        if key.lower().startswith("enable"):
            assert (key in listed) != (key in data["not_listed"]), key
    # Full stack holds what an application needs around its AI.
    names = {resource["name"] for resource in resources if "Full stack" in resource["categories"]}
    assert {"Azure Web App", "Azure Container Apps", "Azure Kubernetes Service (AKS)", "Azure SQL Database",
            "Azure Cache for Redis", "Azure API Management as the AI gateway"} <= names
    # The names on Joakim's list that have no switch of their own are listed with what provides them.
    by_name = {resource["name"]: resource for resource in resources}
    assert by_name["Azure Cosmos DB for MongoDB"]["settings"] == ["enableCosmosDB", "cosmosKind"]
    assert by_name["Microsoft OneLake and Fabric"]["without_setting"]
    assert by_name["Azure VPN Gateway"]["settings"] == ["enableAIFactoryHub"]

    source = (SITE / "docs" / "resources" / "index.md").read_text(encoding="utf-8")
    page = library.render(source)
    assert library.RESOURCES in source and library.RESOURCES not in page and 'type="search"' in page
    variables_page = (SITE / "docs" / "parameters" / "variables.md").read_text(encoding="utf-8")
    for resource in resources:
        assert f'id="{resource["id"]}"' in page and html.escape(resource["name"]) in page
        for setting in resource["settings"]:
            assert f"<code>{setting}</code>" in page
            if setting in variables:
                assert f'href="../parameters/variables/#{setting}"' in page
                assert f'<a id="{setting}"></a>' in variables_page, "Each card links to the row of its variable."
    for group, values in (("area", list(data["areas"])), ("category", categories)):
        for value in values:
            assert f'type="checkbox" data-filter="{group}" data-value="{html.escape(value)}"' in page
    # The numbers on the page are the numbers of the data: no rounded "35+".
    switchable = sum(1 for resource in resources if resource["settings"])
    assert page.count('<article class="esaf-card"') == len(resources)
    assert f"**{len(resources)}** Azure resources" in page and f"**{switchable}** of them" in page
    assert switchable >= 35, "The README promises more than 35 resources a team can switch on."
    assert "35+" not in page and "+35" not in page
    assert {"Azure resource library": "resources/index.md"} in config.nav
    code_templates = (SITE / "docs" / "code-templates" / "index.md").read_text(encoding="utf-8")
    assert "(../resources/index.md)" in code_templates and "(../code-templates/index.md)" in source


def test_architecture_page_shows_each_hub_mode_with_the_numbered_templates(site):
    import xml.etree.ElementTree as ET

    library = tool("code_templates")
    drawing = tool("generate_architecture")
    data = library.load()
    numbered = {template["number"]: template for template in data["templates"] if "number" in template}
    source = (SITE / "docs" / "architectures.md").read_text(encoding="utf-8")
    assert library.NUMBERS in source and {"Architecture": "architectures.md"} in site[1].nav
    svg = "{http://www.w3.org/2000/svg}"
    drawn_labels = ""
    for label, mode in (("External hub", "external-hub"), ("Standalone - Own Hub", "own-hub"),
                        ("Standalone", "standalone")):
        assert source.count(f'=== "{label}"') == 2, "The image tab and the animation tab switch together."
        path = SITE / "docs" / "assets" / "architecture" / f"esaf-architecture-{mode}.svg"
        text = path.read_text(encoding="utf-8")
        assert text == drawing.render(mode, data), "Run documentation/gh-io/tools/generate_architecture.py."
        assert f"assets/architecture/{path.name}" in source
        assert path.with_suffix(".png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        root = ET.fromstring(text)
        assert root.find(f"{svg}title") is not None and root.find(f"{svg}desc") is not None
        circles = {int(group.find(f"{svg}text").text): group for group in root.iter(f"{svg}g")
                   if group.get("class") == "template-number"}
        assert set(circles) == set(numbered), "One blue circle per numbered template."
        for number, group in circles.items():
            assert group.get("data-template") == numbered[number]["id"]
            assert group.find(f"{svg}circle").get("fill") == drawing.BLUE
        labels = " ".join(node.text or "" for node in root.iter(f"{svg}text")) + " ".join(
            node.text or "" for node in root.iter(f"{svg}tspan"))
        for name in ("Microsoft 365", "Teams", "Bot Service", "Power Platform", "Copilot Studio", "Power Automate",
                     "SharePoint", "Foundry IQ", "API Management", "Kong", "Fabric", "Azure Machine Learning"):
            assert name in labels, f"{mode}: {name}"
        drawn_labels += labels
        # The embedded Azure icons keep their official colors. Everything drawn around them uses the palette.
        drawn = re.sub(r"(?s)<defs>.*</defs>", "", text, count=1)
        colors = {color.upper() for color in re.findall(r"#[0-9A-Fa-f]{6}\b", drawn)}
        assert colors <= {color.upper() for color in drawing.PALETTE.values()}, "No red or orange: see the style guide."
        assert text.count("<symbol ") >= 30, "The services are drawn with the official Azure icons."
        # Microsoft 365, Power Platform and Fabric are drawn with the official icons of their own icon sets.
        for name in ("teams", "m365-copilot", "copilot-studio", "power-automate", "fabric", "fabric-data-agent",
                     "onelake"):
            assert (SITE / "tools" / "architecture_icons" / f"{name}.svg").is_file(), name
            assert f'<symbol id="icon-{name}" viewBox="' in text and f'href="#icon-{name}"' in text, f"{mode}: {name}"
        # A product without an official icon in those sets stays a lettered tile, and the README says which.
        readme = (SITE / "tools" / "architecture_icons" / "README.md").read_text(encoding="utf-8")
        for name in drawing.TILES:
            assert not (SITE / "tools" / "architecture_icons" / f"{name}.svg").exists() and f"`{name}.svg`" in readme
    on_image = [resource for resource in library.load_resources()["resources"] if resource.get("label")]
    assert len(on_image) >= 20, "The services on the images take their names from the resource library."
    for resource in on_image:
        for line in resource["label"]:
            assert line in drawn_labels, f"The images name {resource['id']} as the resource library does."
        assert f'"@{resource["id"]}"' in (SITE / "tools" / "generate_architecture.py").read_text(encoding="utf-8")
    table = library.render(source, data)
    for number, template in numbered.items():
        row = next(line for line in table.splitlines() if line.startswith(f"| **{number}** |"))
        assert f"(code-templates/index.md#{template['id']})" in row and library.GITHUB_TREE + template["path"] in row


def test_architecture_images_show_every_resource_of_the_resource_library():
    import xml.etree.ElementTree as ET

    drawing = tool("generate_architecture")
    resources = tool("code_templates").load_resources()["resources"]
    everything = {resource["id"] for resource in resources}
    # The VPN gateway and the DNS resolver exist only when the Factory creates its own hub.
    own_hub_only = {resource["id"] for resource in resources if resource["settings"] == ["enableAIFactoryHub"]}
    assert own_hub_only == {"vpn-gateway", "dns-resolver"}
    for resource in resources:
        assert resource.get("label"), f"{resource['id']} has no name for the architecture images."
    drawn = {}
    for mode in drawing.MODES:
        root = ET.fromstring(drawing.render(mode))
        named = [node for node in root.iter() if node.get("data-resource")]
        drawn[mode] = {identifier for node in named for identifier in node.get("data-resource").split()}
        text = " ".join(piece for node in named for piece in node.itertext())
        for resource in resources:
            if resource["id"] in drawn[mode]:
                for line in resource["label"]:
                    assert line in text, f"{mode}: {resource['id']} is named as in the resource library."
    assert drawn["own-hub"] == everything, sorted(everything - drawn["own-hub"])
    assert drawn["standalone"] == everything - own_hub_only, "A Factory without a hub has no hub resources."
    assert everything - own_hub_only <= drawn["external-hub"] <= everything
    # The page shows the images at the size the generator draws them.
    size = f'width="{drawing.WIDTH}" height="{drawing.HEIGHT}"'
    assert (SITE / "docs" / "architectures.md").read_text(encoding="utf-8").count(size) == len(drawing.MODES)
    styles = (SITE / "docs" / "assets" / "stylesheets" / "libraries.css").read_text(encoding="utf-8")
    assert f"aspect-ratio: {drawing.WIDTH} / {drawing.HEIGHT};" in styles


def test_architecture_images_use_the_modern_foundry_icon_from_a_png_file():
    import base64

    drawing = tool("generate_architecture")
    icons = SITE / "tools" / "architecture_icons"
    picture = (icons / "microsoft-foundry.png").read_bytes()
    assert picture[:8] == b"\x89PNG\r\n\x1a\n" and not (icons / "foundry.svg").exists()
    # A PNG icon becomes a symbol with the picture inside, at the size the file says.
    symbol = drawing.symbol("microsoft-foundry")
    assert symbol.startswith('<symbol id="icon-microsoft-foundry" viewBox="0 0 512 512">')
    assert '<image width="512" height="512" href="data:image/png;base64,' in symbol
    assert base64.b64decode(re.search(r'base64,([^"]+)"', symbol)[1]) == picture
    for mode in drawing.MODES:
        text = drawing.render(mode)
        assert text.count('href="#icon-microsoft-foundry"') == 3, "Hosted, prompt and chat agents."
        assert 'id="icon-foundry"' not in text and text.count('id="icon-microsoft-foundry"') == 1
    readme = (icons / "README.md").read_text(encoding="utf-8")
    assert "`microsoft-foundry.png`" in readme and "selfhst/icons" in readme


def test_repository_readme_shows_the_external_hub_image_from_the_generated_png():
    drawing = tool("generate_architecture")
    copy = ROOT / "documentation" / "v2" / "20-29" / "images" / "esaf-architecture-external-hub.png"
    assert drawing.README_IMAGE == copy, "The generator keeps the copy for the README current."
    generated = SITE / "docs" / "assets" / "architecture" / copy.name
    assert copy.read_bytes() == generated.read_bytes(), "Run generate_architecture.py --png."
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    image = "./documentation/v2/20-29/images/esaf-architecture-external-hub.png"
    assert readme.count(image) == 1 and "esaf-architecture-own-hub.svg" not in readme
    # Below the landing zone image, above the tagline, with a text for screen readers.
    assert readme.index("14-eslz-full-1.png") < readme.index(image) < readme.index("Private, WAF-aligned full stack")
    alternative = re.search(r'<img src="' + re.escape(image) + r'"[^>]*\balt="([^"]+)"', readme)
    assert alternative and "external hub" in alternative[1]


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
