"""Offline checks for the quickstart-first end-user documentation (Setup docs and Usage docs)."""

import ast
from collections import Counter
from pathlib import Path
import re
import textwrap
from urllib.parse import unquote

import pytest


ROOT = Path(__file__).resolve().parents[3]
V2 = ROOT / "documentation" / "v2"
HUB = V2 / "README.md"
SETUP_HUB = V2 / "quickstarts" / "README.md"
USAGE_HUB = V2 / "usage" / "README.md"
USAGE_PREREQUISITES = V2 / "usage" / "prerequisites.md"
PAGE_24 = V2 / "20-29" / "24-end-2-end-setup.md"
SCENARIOS = V2 / "reference" / "scenarios.md"
LEGACY = V2 / "20-29" / "24-legacy-v124-setup.md"
MAINTAINERS = V2 / "reference" / "maintainers" / "automation-and-review-flow.md"
ONION_PAGE = V2 / "10-19" / "10-factory-onion-architecture-v2.md"

SETUP_QUICKSTARTS = [V2 / "quickstarts" / name for name in (
    "01-install-esaf.md", "02-create-factory.md", "03-add-project.md", "04-first-agent-chat.md", "05-clean-up.md")]
USAGE_QUICKSTARTS = [V2 / "usage" / name for name in ("01-first-agent.md", "02-first-ml-model.md")]
QUICKSTARTS = SETUP_QUICKSTARTS + USAGE_QUICKSTARTS
USAGE_PAGES = [USAGE_HUB, USAGE_PREREQUISITES, *USAGE_QUICKSTARTS, V2 / "usage" / "dashboards.md"]
CONCEPT_PAGES = [V2 / "concepts" / "hub-and-network-modes.md"]
REFERENCE_PAGES = [SCENARIOS, V2 / "reference" / "folder-structure.md", V2 / "reference" / "settings.md"]
# The reading path: what a new user follows. Legacy and maintainer pages are deliberately not part of it.
END_USER = [HUB, SETUP_HUB, *SETUP_QUICKSTARTS, *USAGE_PAGES, *CONCEPT_PAGES, *REFERENCE_PAGES, PAGE_24]
# Pages this rewrite touched or created off the reading path: their links must still resolve.
OFF_PATH = [
    LEGACY, MAINTAINERS, V2 / "images" / "concepts" / "README.md", V2 / "10_index.md",
    *(V2 / "10-19" / f"{number}-cli-and-api-and-usage.md" for number in (17, 18, 19, 20)),
    V2 / "10-19" / "21-agent-factory-chat.md", V2 / "20-29" / "29-ESAIF-Chat-Agent.md",
    V2 / "20-29" / "24-create-AIFactory-common.md", V2 / "20-29" / "24-configure-AIfactory-project.md",
    V2 / "20-29" / "24-create-AIFactory-project.md", V2 / "20-29" / "27-extend-AIF-pipelines.md",
    V2 / "10-19" / "13-setup-aifactory.md",
]

TOOL_LABELS = ["App", "CLI (PowerShell)", "Python SDK", "REST (curl)"]
TOOL_SECTION = re.compile(
    r'^<details markdown="1" data-factory-tool="([^"]+)"( open)?>\n<summary>\1</summary>\n\n(.*?)'
    r'^</details>\n<!-- /factory-tool -->', re.M | re.S)
ALERT = re.compile(r"^([ \t]*)>[ \t]*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]", re.M)
MARKDOWN_LINK = re.compile(r'(!?)\[((?:[^\[\]]|\[[^\]]*\])*)\]\(\s*<?([^)\s>]+)>?(?:\s+"[^"]*")?\)')
HTML_TAG = re.compile(r"<(img|a|source)\b([^>]*)>", re.I)
# Existing animated assets reused as they are; every image this rewrite adds stays under the limit.
REUSED_LARGE_IMAGES = {"10-factory-onion-architecture-v2.png", "10-factory-onion-architecture-v2.gif"}
IMAGE_LIMIT = 300 * 1024
LEGACY_TERMS = [r"variables\.yaml", r"(?<![\w$])\.env\b", r"release/v1\.24", r"00-start\.sh", r"\bClassic\b",
                r"aifactory\\variables\.json"]
V124_FOOTER = "https://github.com/jostrm/azure-enterprise-scale-ml/tree/release/v1.24/documentation"
# The calls behind the facade, test-run identifiers and author-machine paths never belong on the reading path.
INTERNAL_TERMS = [
    r"factory_create_prepare", r"\bbootstrap_\w+", r"scaleset_add_prepare", r"project_add_prepare",
    r"project_deployment_\w+", r"project_delete_prepare", r"scaleset_delete_prepare", r"delete_aifactory_\w+",
    r"catalog_confirm", r"creation_workflow_\w+", r"authorize_deletion_\w+", r"\baif-1\d\d\b",
    r"C:\\Users\\jostrm", r"code_py_25", r"\bapply_project\b",
]


def name(path):
    return path.relative_to(ROOT).as_posix()


def read(path):
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def without_code(text):
    text = re.sub(r"(?ms)^[ \t]*(`{3,}|~{3,}).*?^[ \t]*\1[ \t]*$", "", text)
    return re.sub(r"`[^`\n]*`", "", text)


def anchors(path):
    """GitHub heading anchors: lower case, punctuation dropped, spaces to hyphens, duplicates numbered."""
    text, found, seen = read(path), set(), Counter()
    for heading in re.findall(r"(?m)^#{1,6}[ \t]+(.+?)[ \t]*#*$", re.sub(r"(?ms)^```.*?^```", "", text)):
        heading = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", heading)
        slug = re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")
        found.add(slug if not seen[slug] else f"{slug}-{seen[slug]}")
        seen[slug] += 1
    return found | {value.lower() for value in re.findall(r'(?:id|name)="([^"]+)"', text)}


def references(path):
    """Every link and image of a page as (url, kind, alt_or_text); kind is False, True (image) or "source"."""
    text = without_code(read(path))
    for image, label, url in MARKDOWN_LINK.findall(text):
        nested = re.fullmatch(r"!\[([^\]]*)\]\(([^)\s]+)\)", label)
        if nested:  # [![alt](image)](target)
            yield nested[2], True, nested[1]
        yield url, bool(image), label
    for tag, attributes in HTML_TAG.findall(text):
        values = dict(re.findall(r'([\w-]+)="([^"]*)"', attributes))
        url = values.get("src") or values.get("href") or values.get("srcset")
        if url:
            yield url, {"img": True, "source": "source"}.get(tag.lower(), False), values.get("alt", "")


def local_target(path, url):
    location = unquote(url.partition("#")[0].split("?")[0])
    return path if not location else (path.parent / location).resolve()


def is_external(url):
    return bool(re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", url))


@pytest.mark.parametrize("page", END_USER + OFF_PATH, ids=name)
def test_relative_links_and_anchors_resolve(page):
    broken = []
    for url, _, _ in references(page):
        if is_external(url):
            continue
        target = local_target(page, url)
        if ROOT.resolve() not in target.parents or not target.exists():
            broken.append(url)
        elif "#" in url and target.suffix.lower() == ".md" and url.partition("#")[2].lower() not in anchors(target):
            broken.append(url)
    assert not broken, f"{name(page)} has unresolved links: {broken}"


@pytest.mark.parametrize("page", END_USER, ids=name)
def test_reading_path_uses_relative_links_that_follow_the_branch(page):
    hard_coded = [url for url, _, _ in references(page)
                  if re.search(r"github\.com/jostrm/azure-enterprise-scale-ml/(blob|tree)/release/v1\.25/", url)]
    assert not hard_coded


@pytest.mark.parametrize("page", QUICKSTARTS, ids=name)
def test_quickstart_follows_the_template(page):
    text = read(page)
    lines = text.splitlines()
    hub = "Quickstarts" if page in SETUP_QUICKSTARTS else "Usage docs"
    assert lines[0] == f"[Docs](../README.md) › [{hub}](README.md)"
    titles = [line for line in lines if line.startswith("# ")]
    assert len(titles) == 1 and titles[0].startswith("# Quickstart: ") and not titles[0].endswith(".")
    intro = text.split(titles[0], 1)[1].strip().splitlines()[0]
    assert intro.startswith("In this quickstart, you ")
    sections = re.findall(r"(?m)^## (.+)$", without_code(text))
    required = ["Prerequisites", "Verify the result", "Clean up resources", "Next step"]
    if page.name == "01-install-esaf.md":
        required.remove("Clean up resources")
    assert [section for section in sections if section in required] == required
    assert all(not section.endswith((".", ":")) for section in sections)
    assert re.search(r"(?m)^\*\*Next:\*\* \[", text.split("## Next step", 1)[1])


@pytest.mark.parametrize("page", SETUP_QUICKSTARTS, ids=name)
def test_setup_quickstart_offers_every_tool_and_the_lab_guide(page):
    text = read(page)
    labels = [label for label, _, _ in TOOL_SECTION.findall(text)]
    assert set(labels) == set(TOOL_LABELS)
    assert "install_tutorial_guide" in text, "Every quickstart links to the ESAF Tutorials lab guide."
    assert "dropbox.com" not in text, "Videos open from inside the lab guide app only."


@pytest.mark.parametrize("page", END_USER, ids=name)
def test_tool_selectors_use_the_tested_markup(page):
    text = read(page)
    sections = TOOL_SECTION.findall(text)
    assert len(sections) == text.count("data-factory-tool=") == text.count("<!-- /factory-tool -->")
    group = []
    for label, is_open, content in sections:
        assert label in TOOL_LABELS
        if group and TOOL_LABELS.index(label) <= TOOL_LABELS.index(group[-1]):
            group = []
        assert bool(is_open) == (not group), "Only the first tool of each selector is open."
        group.append(label)
        assert content.count("```") % 2 == 0 and not ALERT.search(content)
        if label == "Python SDK":
            blocks = re.findall(r"(?ms)^```python\n(.*?)^```", content)
            assert blocks
            for block in blocks:
                ast.parse(textwrap.dedent(block))
        if label == "REST (curl)":
            assert "curl" in content and "```python" not in content
        if label == "CLI (PowerShell)":
            assert "```powershell" in content


@pytest.mark.parametrize("page", END_USER + [V2 / "images" / "concepts" / "README.md"], ids=name)
def test_images_have_alt_text_and_stay_small(page):
    problems = []
    for url, is_image, alt in references(page):
        target = None if is_external(url) else local_target(page, url)
        if is_image is True and not (40 <= len(alt) <= 150 and alt.endswith(".")):
            problems.append(f"alt text of {url}: {alt!r}")
        if is_image and target and target.exists():
            if target.stat().st_size > IMAGE_LIMIT and target.name not in REUSED_LARGE_IMAGES:
                problems.append(f"{url} is {target.stat().st_size} bytes")
    assert not problems, problems


def test_new_images_fit_the_repository_budget_and_no_video_is_committed():
    new_images = [path for path in (V2 / "images").rglob("*") if path.is_file() and path.suffix.lower() != ".md"
                  and path.parent != V2 / "images"]
    assert all(path.stat().st_size <= IMAGE_LIMIT for path in new_images)
    assert sum(path.stat().st_size for path in new_images) <= 3 * 1024 * 1024
    videos = [path for suffix in ("*.mp4", "*.mov", "*.webm") for path in (ROOT / "documentation").rglob(suffix)]
    assert not videos


@pytest.mark.parametrize("page", END_USER, ids=name)
def test_animated_images_offer_a_reduced_motion_still(page):
    text = read(page)
    for gif in re.findall(r'src="([^"]+\.gif)"', text):
        picture = next(body for body in re.findall(r"(?s)<picture>(.*?)</picture>", text) if gif in body)
        assert re.search(r'<source media="\(prefers-reduced-motion: reduce\)" srcset="[^"]+\.png">', picture)
    assert not re.search(r"!\[[^\]]*\]\([^)]+\.gif\)", without_code(text)), "Wrap a GIF in <picture> with a still."


@pytest.mark.parametrize("page", END_USER, ids=name)
def test_alerts_are_few_and_outside_lists_and_details(page):
    text = re.sub(r"(?ms)^```.*?^```", "", read(page))
    found = ALERT.findall(text)
    assert len(found) <= 2
    assert all(indent == "" for indent, _ in found), "No alert inside a list item."
    for body in re.findall(r"(?s)<details\b.*?</details>", text):
        assert not ALERT.search(body), "No alert inside <details>."
    assert not re.search(r"(?m)^(!!!|\?\?\?) ", text), "MkDocs admonitions do not render on GitHub."


@pytest.mark.parametrize("page", END_USER, ids=name)
def test_reading_path_has_no_legacy_terms(page):
    text = read(page)
    if page == HUB:
        assert text.count(V124_FOOTER) == 1, "The hub has exactly one footer line for v1.24."
        text = "\n".join(line for line in text.splitlines() if V124_FOOTER not in line)
    found = [term for term in LEGACY_TERMS if re.search(term, text)]
    assert not found, f"{name(page)} mentions {found}"
    assert not any(LEGACY.name in url for url, _, _ in references(page)), "The new path never links to the legacy page."


@pytest.mark.parametrize("page", END_USER, ids=name)
def test_reading_path_shows_the_facade_not_the_calls_behind_it(page):
    found = [term for term in INTERNAL_TERMS if re.search(term, read(page))]
    assert not found, f"{name(page)} exposes internals: {found}"


def test_scenario_table_shows_one_facade_call_per_tool():
    text = read(SCENARIOS)
    for call in ("esaf.init_factory()", "esaf.add_scale_set(", "esaf.upsert_project(", "esaf.delete_project(",
                 "esaf.delete_scale_set(", "esaf.delete_factory()"):
        assert call in text
    for command in ("init-factory", "add-scale-set", "upsert-project", "delete-project", "delete-scale-set",
                    "delete-factory"):
        assert f"azurefactory esaf {command}" in text and f"/api/v1/esaf/{command}" in text


def test_scenario_outcome_table_lives_on_exactly_one_page():
    pages = [*END_USER, *OFF_PATH]
    owners = [name(page) for page in pages
              if re.search(r"(?m)^\|[^\n]*\bScenario\b[^\n]*\|[^\n]*\bOutcome\b[^\n]*\|$", read(page))]
    assert owners == [name(SCENARIOS)]
    for number in (17, 18):
        guide = read(V2 / "10-19" / f"{number}-cli-and-api-and-usage.md")
        assert "reference/scenarios.md" in guide and "factory_create_prepare" not in guide


@pytest.mark.parametrize("page", [HUB, PAGE_24], ids=name)
def test_page_opens_with_the_two_doors(page):
    text = read(page)
    opening = text.split("\n## ", 1)[0]
    table = re.search(r"(?s)<table>.*?</table>", opening)
    assert table, "The two cards come before the first H2."
    links = re.findall(r'<a href="([^"]+)"><b>([^<]+)</b></a>', table[0])
    assert [text for _, text in links] == [
        "Setup docs - platform team: How to set up the Factory",
        "Usage docs - project team: How to build agents, apps and ML",
    ]
    assert [local_target(page, url) for url, _ in links] == [SETUP_HUB.resolve(), USAGE_HUB.resolve()]
    assert len(re.findall(r"<td\b", table[0])) == 2 and len(re.findall(r"<img\b", table[0])) == 2


@pytest.mark.parametrize("page", [p for p in USAGE_PAGES if p != USAGE_PREREQUISITES], ids=name)
def test_usage_pages_share_one_prerequisites_page(page):
    assert any(local_target(page, url) == USAGE_PREREQUISITES.resolve() for url, _, _ in references(page)
               if not is_external(url))


def test_usage_prerequisites_offer_setup_docs_or_deploy_to_azure():
    urls = [url for url, _, _ in references(USAGE_PREREQUISITES)]
    assert any(not is_external(url) and local_target(USAGE_PREREQUISITES, url) == SETUP_HUB.resolve() for url in urls)
    assert "https://aka.ms/deploytoazurebutton" in urls
    assert any(url.startswith("https://portal.azure.com/#blade/Microsoft_Azure_CreateUIDef/CustomDeploymentBlade/")
               for url in urls)
    assert "quick test" in read(USAGE_PREREQUISITES)


def test_setup_hub_shows_the_onion_many_tools_one_goal():
    text = read(SETUP_HUB)
    picture = next(body for body in re.findall(r"(?s)<picture>(.*?)</picture>", text)
                   if "10-factory-onion-architecture-v2.gif" in body)
    assert "10-factory-onion-architecture-v2.png" in picture and re.search(r'alt="[^"]{40,150}\."', picture)
    assert any(not is_external(url) and local_target(SETUP_HUB, url) == ONION_PAGE.resolve()
               for url, _, _ in references(SETUP_HUB))
    assert "Every tool is an L1 client of the same Factory API" in text
    first = read(SETUP_QUICKSTARTS[0])
    assert "10-factory-onion-architecture-v2" in first.split("data-factory-tool", 1)[0]


def test_every_end_user_page_has_a_breadcrumb_and_a_next_link():
    for page in END_USER:
        text = read(page)
        if page not in (HUB, PAGE_24):
            assert text.startswith("[Docs]("), name(page)
        assert re.search(r"(?m)^\*\*Next:\*\* \[", text), name(page)


def test_agent_chat_settings_table_lives_on_the_quickstart_only():
    owner = V2 / "quickstarts" / "04-first-agent-chat.md"
    row = re.compile(r"(?m)^\| `enableAIFactoryAgentLiveVoice`")
    assert row.search(read(owner))
    for page in (V2 / "10-19" / "19-cli-and-api-and-usage.md", V2 / "10-19" / "21-agent-factory-chat.md",
                 V2 / "20-29" / "29-ESAIF-Chat-Agent.md"):
        text = read(page)
        assert not row.search(text) and "04-first-agent-chat.md" in text
        chat = text.split("## Agent Factory chat and live voice", 1)[-1] if page.name.startswith("19-") else text
        if not page.name.startswith("21-"):  # guide 21 keeps its dated evidence of one project001 test run
            assert "project001 Dev" not in chat, "Agent Chat works for any project number in Dev."


def test_llms_index_lists_every_end_user_page():
    index = read(V2 / "llms.txt")
    for page in END_USER:
        assert f"({page.relative_to(V2).as_posix()})" in index, name(page)
    for url in re.findall(r"\]\(([^)]+)\)", index):
        assert is_external(url) or (V2 / url).exists(), url
