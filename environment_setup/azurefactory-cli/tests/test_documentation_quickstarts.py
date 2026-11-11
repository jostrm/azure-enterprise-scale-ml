"""Offline checks for the quickstart-first end-user documentation (Setup docs and Usage docs)."""

import ast
from collections import Counter
import inspect
from pathlib import Path
import re
import shlex
import textwrap
from urllib.parse import unquote

import pytest

from azurefactory import cli, esaf


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
    "01-install-esaf.md", "02-create-factory.md", "add-scale-set.md", "03-add-project.md",
    "04-first-agent-chat.md", "05-clean-up.md")]
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

# CLI (bash) is for Linux and macOS (and Git Bash): the same azurefactory commands as the PowerShell tab.
TOOL_LABELS = ["App", "CLI (PowerShell)", "CLI (bash)", "Python SDK", "REST (curl)"]
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
    hub = "Setup docs" if page in SETUP_QUICKSTARTS else "Usage docs"  # the breadcrumb names the hub it opens
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
        if label == "CLI (bash)":
            assert "```bash" in content and "azurefactory " in content
            assert "```powershell" not in content and "$env:" not in content, "No PowerShell in the bash tab."


def esaf_commands(content):
    """The azurefactory esaf commands of one tool tab, with file paths written the same way in both shells."""
    return sorted(re.sub(r"\.[\\/]", "./", command.strip())
                  for command in re.findall(r"azurefactory esaf [a-z][^\n`]*", content))


@pytest.mark.parametrize("page", SETUP_QUICKSTARTS, ids=name)
def test_cli_bash_tab_runs_the_same_commands_as_the_powershell_tab(page):
    """Linux and macOS readers get the same calls: only the shell syntax around them differs."""
    sections, powershell = TOOL_SECTION.findall(read(page)), None
    for label, _, content in sections:
        if label == "CLI (PowerShell)":
            powershell = esaf_commands(content)
        if label == "CLI (bash)":
            assert esaf_commands(content) == powershell, name(page)


def test_install_quickstart_says_which_app_package_serves_linux_and_macos():
    text = read(SETUP_QUICKSTARTS[0])
    assert "Linux" in text and "macOS" in text and "v0.47.100" in text
    assert re.search(r"(?m)^- \*\*Linux or macOS", text), "The prerequisites name the Linux and macOS path."


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


# --- The docs cannot drift from the code: every call a page shows is one the facade really accepts. ---------------
CLI_DOCS = ROOT / "environment_setup" / "azurefactory-cli" / "docs" / "esaf" / "readme.md"
WIZARD_README = ROOT / "environment_setup" / "install_config_wizard" / "readme.md"
DRIFT_CHECKED = [*END_USER, CLI_DOCS, WIZARD_README,
                 *(V2 / "10-19" / f"{number}-cli-and-api-and-usage.md" for number in (17, 18, 19, 20))]
ADD_SCALE_SET, ADD_PROJECT, AGENT_CHAT, CLEAN_UP = SETUP_QUICKSTARTS[2:]
LAB_GUIDE = "environment_setup/install_tutorial_guide"
PREVIEW_CONTACT = "https://www.linkedin.com/in/joakimastrom/"
FENCE = r"(?ms)^[ \t]*(`{3,}|~{3,})[^\n]*\n(.*?)^[ \t]*\1[ \t]*$"
REST_CALL = r"(?s)jq -n.*?'(\{.*?\})'\s*\|\s*curl[^\n]*?/api/v1/esaf/([a-z-]+)"


def code_spans(text):
    """Every fenced block and inline code span of a page."""
    return [body for _, body in re.findall(FENCE, text)] + re.findall(r"`([^`\n]+)`", re.sub(FENCE, "", text))


def esaf_nodes(text):
    """The parsed Python a page shows: fenced blocks and inline spans. Signature summaries do not parse; skip them."""
    for span in code_spans(text):
        if "esaf." in span or "job." in span:
            try:
                yield from ast.walk(ast.parse(textwrap.dedent(span)))
            except SyntaxError:
                continue


def is_esaf_call(node, method=None):
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "esaf"
            and method in (None, node.func.attr))


def accepted_rest_fields():
    """The body each route takes, read by calling every scenario against a recording client."""
    class Recorder:
        def __init__(self):
            self.bodies = {}

        def esaf_submit(self, route, body):
            self.bodies[route] = set(body)
            return {"job_id": "recorded"}

    recorder = Recorder()
    session = esaf.Session("folder", recorder, "factory")
    for function in (esaf.init_factory, esaf.add_scale_set, esaf.upsert_project, esaf.delete_project,
                     esaf.delete_scale_set, esaf.delete_factory):
        arguments = {parameter: ("dev" if parameter == "environment" else "x")
                     for parameter in inspect.signature(function).parameters
                     if parameter not in ("wait", "poll", "session")}
        function(**arguments, session=session)
    return recorder.bodies


def top_level_keys(program):
    depth, flat = 0, ""
    for character in program.strip()[1:-1]:
        depth += (character == "{") - (character == "}")
        flat += character if depth == 0 and character != "}" else ""
    return set(re.findall(r'(?:^|,)\s*"?(\w+)"?\s*:', flat))


@pytest.mark.parametrize("page", DRIFT_CHECKED, ids=name)
def test_every_esaf_command_shown_is_accepted_by_the_real_cli_parser(page, capsys):
    parser, refused = cli.build_parser(), []
    for span in code_spans(read(page)):
        for line in span.splitlines():
            shown = re.search(r"azurefactory (?:esaf [a-z]|health\b).*", line)
            if not shown:
                continue
            command = re.sub(r"<[^>]+>", "PLACEHOLDER", shown[0]).strip()
            try:
                parser.parse_args(shlex.split(command, posix=False)[1:])
            except SystemExit:
                refused.append(command)
    capsys.readouterr()  # argparse prints its usage on a refusal; the assertion below carries the message
    assert not refused, f"{name(page)} shows commands the CLI refuses: {refused}"


@pytest.mark.parametrize("page", DRIFT_CHECKED, ids=name)
def test_every_python_call_shown_matches_the_real_esaf_signature(page):
    problems = []
    job_members = set(esaf.EsafJob.__dataclass_fields__) | {"status", "wait"}
    for node in esaf_nodes(read(page)):
        # In the step-by-step guides `job` is also a plain dict, so check job members where it is always an EsafJob.
        if (page in [*END_USER, CLI_DOCS] and isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name) and node.value.id == "job"):
            if node.attr not in job_members:
                problems.append(f"job.{node.attr}")
        if not is_esaf_call(node):
            continue
        try:
            inspect.signature(getattr(esaf, node.func.attr)).bind(
                *node.args, **{keyword.arg: 0 for keyword in node.keywords if keyword.arg})  # **mapping names no keyword
        except (AttributeError, TypeError) as error:
            problems.append(f"esaf.{node.func.attr}: {error}")
    assert not problems, f"{name(page)} shows calls the SDK refuses: {problems}"


@pytest.mark.parametrize("page", DRIFT_CHECKED, ids=name)
def test_every_rest_route_and_body_field_shown_is_one_the_api_route_takes(page):
    accepted, text = accepted_rest_fields(), read(page)
    unknown = set(re.findall(r"/api/v1/esaf/([a-z][a-z-]*)", text)) - set(accepted) - {"jobs"}
    assert not unknown, f"{name(page)} shows routes the SDK never calls: {unknown}"
    for span in code_spans(text):
        for program, route in re.findall(REST_CALL, span):
            extra = top_level_keys(program) - accepted[route]
            assert not extra, f"{name(page)} posts {extra} to {route}, which takes {sorted(accepted[route])}"


# --- The quickstarts tell one story: what a page deletes or updates, an earlier page created. --------------------
def shown_targets(page, command):
    return set(re.findall(rf"azurefactory esaf {command} (\d{{3}}) (dev|stage|prod)", read(page)))


def test_setup_hub_lists_the_quickstarts_in_reading_order():
    linked = [url for url, _, _ in references(SETUP_HUB) if re.fullmatch(r"(?!README)[\w-]+\.md", url)]
    in_table = linked[:-1] if linked and linked[-1] == linked[0] else linked  # the closing Next link repeats 01
    assert in_table == [page.name for page in SETUP_QUICKSTARTS]


def test_add_scale_set_quickstart_shows_scenario_two_in_every_tool():
    text = read(ADD_SCALE_SET)
    assert shown_targets(ADD_SCALE_SET, "add-scale-set") == {("002", "dev")}
    assert 'esaf.add_scale_set("002", "dev", cidr=' in text and "/api/v1/esaf/add-scale-set" in text
    assert "--cidr" in text and "overlap" in text, "A new scale set needs its own VNet range."


def test_clean_up_only_deletes_what_an_earlier_quickstart_created():
    assert shown_targets(CLEAN_UP, "delete-project") <= shown_targets(ADD_PROJECT, "upsert-project")
    assert shown_targets(CLEAN_UP, "delete-scale-set") == shown_targets(ADD_SCALE_SET, "add-scale-set")
    assert "esaf delete-factory" in read(CLEAN_UP)


@pytest.mark.parametrize("page", [ADD_PROJECT, AGENT_CHAT], ids=name)
def test_project_calls_name_the_scale_set_once_dev_has_two(page):
    """After the add-scale-set quickstart, a project call without a scale set is refused as ambiguous."""
    text = read(page)
    commands = re.findall(r"azurefactory esaf upsert-project [^\n`|]*", text)
    assert commands and all("--scale-set 001" in command for command in commands), commands
    calls = [node for node in esaf_nodes(text) if is_esaf_call(node, "upsert_project")]
    assert calls and all("scale_set" in {keyword.arg for keyword in call.keywords} for call in calls)
    bodies = [program for span in code_spans(text) for program, route in re.findall(REST_CALL, span)
              if route == "upsert-project"]
    assert bodies and all("scale_set" in top_level_keys(program) for program in bodies)


def test_topology_choice_warns_before_the_agent_chat_dead_end():
    """Public networking is the smallest setup, but Agent Chat needs private or hybrid: say so where you choose."""
    choice = read(SETUP_QUICKSTARTS[1]).split("## Choose your topology", 1)[1].split("\n## ", 1)[0]
    assert AGENT_CHAT.name in choice and "hybrid" in choice


@pytest.mark.parametrize("page", END_USER, ids=name)
def test_lab_guide_links_say_it_needs_a_preview_code(page):
    text = read(page)
    if LAB_GUIDE not in text:
        return
    assert "preview code" in text and PREVIEW_CONTACT in text, "The ESAF Tutorials download is a private preview."
    assert "dropbox.com" not in text


# --- Describe your Factory: three file options and the app, with settings the API really takes. ------------------
CREATE = SETUP_QUICKSTARTS[1]
DESCRIBE_OPTIONS = ["In a file: automated networking", "In a file: BYO VNet", "In a file: BYO subnets",
                    "In the app: Full bootstrap"]
# The API refuses addAIFactoryMCP2APIM without the MCP itself, so the file turns on both.
SERVICE_SWITCHES = {"enableAIFactoryMCP": "true", "addAIFactoryMCP2APIM": "true", "enableFactoryChatAgent": "true"}
# Not project settings: the Factory API refuses them, and the AI gateway pipeline reads them from its own source.
GATEWAY_SWITCHES = ('ENABLE_KONG: "false"', 'ENABLE_APIM: "true"')


def describe_options():
    section = read(CREATE).split("## Describe your Factory", 1)[1].split("\n## ", 1)[0]
    return {summary: body for summary, body in
            re.findall(r"(?s)<details(?: open)?>\n<summary>([^<]+)</summary>\n(.*?)\n</details>", section)}


def json_blocks(text):
    import json
    return [json.loads(block) for block in re.findall(r"(?ms)^[ \t]*```json\n(.*?)^[ \t]*```", text)]


def test_describe_your_factory_offers_three_file_options_and_the_app():
    options = describe_options()
    assert list(options) == DESCRIBE_OPTIONS
    for label in DESCRIBE_OPTIONS[:3]:
        blocks = json_blocks(options[label])
        switches = [block for block in blocks if "enableFactoryChatAgent" in block]
        assert len(switches) == 1, f"{label} shows the service switches once."
        assert switches[0] == SERVICE_SWITCHES, label
        assert not any(key in block for block in blocks for key in ("ENABLE_APIM", "ENABLE_KONG")), label
        assert all(switch in options[label] for switch in GATEWAY_SWITCHES)
        assert "AI gateway pipeline" in options[label], label
    vnet = [block for block in json_blocks(options["In a file: BYO VNet"]) if "vnetResourceGroup_param" in block]
    subnets = [block for block in json_blocks(options["In a file: BYO subnets"]) if "vnetResourceGroup_param" in block]
    assert len(vnet) == len(subnets) == 1
    assert "BYO_subnets" not in vnet[0] and subnets[0]["BYO_subnets"] == "true"
    assert all(block.get("vnetNameFull_param") for block in (vnet[0], subnets[0]))
    assert "Full bootstrap" in options["In the app: Full bootstrap"] and "```json" not in options[DESCRIBE_OPTIONS[3]]


def test_creation_request_holds_only_the_fields_the_api_takes():
    """The creation request is a closed set of lower-case fields; switches and BYO settings go in their own files."""
    requests = [block for block in json_blocks(read(CREATE)) if "contract_version" in block]
    assert requests, "Quickstart 02 shows the creation request."
    for request in requests:
        assert request["mode"] == "full-bootstrap" and request["action"] == "create-factory"
        strangers = [key for key in request["config"] if not re.fullmatch(r"[a-z][a-z0-9_]*", key)]
        assert not strangers, f"The API refuses these names in a creation request: {strangers}"


# --- Navigation: every page in a reading path links back and forward. ---------------------------------------------
READING_PATHS = [[SETUP_HUB, *SETUP_QUICKSTARTS],
                 [USAGE_HUB, USAGE_PREREQUISITES, *USAGE_QUICKSTARTS, V2 / "usage" / "dashboards.md"]]


def navigation_target(page, word):
    found = re.search(rf"(?m)^\*\*{word}:\*\* \[[^\]]+\]\(([^)#]+)", read(page))
    return (page.parent / found[1]).resolve() if found else None


@pytest.mark.parametrize("path", READING_PATHS, ids=["setup", "usage"])
def test_pages_link_back_and_next_along_the_reading_path(path):
    for before, after in zip(path, path[1:]):
        assert navigation_target(before, "Next") == after.resolve(), f"{name(before)}: Next"
        assert navigation_target(after, "Back") == before.resolve(), f"{name(after)}: Back"


# --- Diagrams: dark gray boxes with rounded corners, borders in the onion's colors, labels that fit. ------------
BOX_FILL = "#191919"
BORDER_COLORS = {"#5AA9FF", "#B07CFF", "#FF6FD8", "#3DDC97"}
TEXT_COLOR = "#ECF6FF"


@pytest.mark.parametrize("page", END_USER, ids=name)
def test_mermaid_boxes_are_dark_gray_and_rounded_with_onion_borders(page):
    for diagram in re.findall(r"(?ms)^```mermaid\n(.*?)^```", read(page)):
        colors = {color.upper() for color in re.findall(r"#[0-9a-fA-F]{6}\b", diagram)}
        assert colors <= BORDER_COLORS | {BOX_FILL, TEXT_COLOR}, f"{name(page)}: {sorted(colors)}"
        for fill, stroke, text in re.findall(r"classDef \w+ fill:(#\w+),stroke:(#\w+),[^\n]*color:(#\w+)", diagram):
            assert (fill, text) == (BOX_FILL, TEXT_COLOR) and stroke in BORDER_COLORS, name(page)
        if not diagram.lstrip().startswith("flowchart"):
            continue
        assert not re.search(r"\b\w+\[", diagram), f"{name(page)}: use rounded boxes, id(label), not id[label]"
        for label in re.findall(r"[({]([^(){}\"]+)[)}]", diagram):
            assert all(len(line) <= 20 for line in label.split("<br/>")), f"{name(page)}: break the label {label!r}"
