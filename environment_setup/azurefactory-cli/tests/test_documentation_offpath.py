"""Offline checks for the pages next to the quickstart reading path: prerequisites, guides 20-21 and the readmes."""

import importlib.util
import re

import pytest

from test_documentation_quickstarts import ROOT, V2, read, name, references, local_target, anchors, is_external


CLI = ROOT / "environment_setup" / "azurefactory-cli"
AGENT_FACTORY = ROOT / "usecase_code" / "40-agent-factory"
TEMPLATES = ROOT / "environment_setup" / "aifactory" / "bicep" / "copy_to_local_settings"
PREREQUISITES = V2 / "10-19" / "12-prerequisites-setup.md"
GUIDE_21 = V2 / "10-19" / "21-agent-factory-chat.md"
WALKTHROUGH = V2 / "20-29" / "28-tutorial-walkthrough.md"
FINOPS = V2 / "20-29" / "tutorial-finops.md"
CLI_README = CLI / "readme.md"
LIVE_VOICE_README = AGENT_FACTORY / "47-aifactory-agent-live-voice" / "readme.md"
AGENT_FACTORY_README = AGENT_FACTORY / "agent_factory" / "readme.md"
PAGES = [PREREQUISITES, WALKTHROUGH, FINOPS, CLI_README, LIVE_VOICE_README, AGENT_FACTORY_README]
NUMBER_WORDS = {7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve"}
ADMONITION = re.compile(r"(?m)^[ \t]*(!!!|\?\?\?) ")


def broken_links(page):
    broken = []
    for url, _, _ in references(page):
        if is_external(url):
            continue
        target = local_target(page, url)
        if ROOT.resolve() not in target.parents or not target.exists():
            broken.append(url)
        elif "#" in url and target.suffix.lower() == ".md" and url.partition("#")[2].lower() not in anchors(target):
            broken.append(url)
    return broken


def publisher():
    """The MkDocs hook that publishes guides 18-20 and the project-team readmes to the documentation site."""
    pytest.importorskip("mkdocs")
    path = ROOT / "documentation" / "gh-io" / "tools" / "factory_guides.py"
    spec = importlib.util.spec_from_file_location("factory_guides_offpath", path)
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    return hook


def agent_chat_settings():
    """The Agent Chat settings of the variables template: the two switches and every aifactoryAgent* input."""
    template = read(ROOT / "environment_setup" / "aifactory" / "variables.json")
    return set(re.findall(r'"(enableFactoryChatAgent|enableAIFactoryAgentLiveVoice|aifactoryAgent\w+)"\s*:', template))


@pytest.mark.parametrize("page", PAGES, ids=name)
def test_relative_links_and_anchors_resolve(page):
    assert not broken_links(page), f"{name(page)} has unresolved links: {broken_links(page)}"


def test_prerequisites_page_names_local_copies_as_paths_not_links():
    # A link out of the repository (the consumer's own aifactory folder) can never resolve on GitHub.
    text = read(PREREQUISITES)
    assert "Local-repo-link" not in text
    assert "`aifactory/esml-util/29-create-sp-or-update-oid-for-project.sh`" in text


def test_site_publisher_renders_github_alerts_as_admonitions():
    hook = publisher()
    alert = "intro\n\n> [!WARNING]\n> **Stop.** First line\n> second line\n>\n> Last paragraph.\n\nafter\n> a quote\n"
    code = "\n```markdown\n> [!NOTE]\n> stays as written\n```\n"
    expected = "intro\n\n!!! warning\n\n    **Stop.** First line\n    second line\n\n    Last paragraph.\n\nafter\n> a quote\n"
    assert hook.site_alerts(alert + code) == expected + code
    assert hook.site_alerts((alert + code).replace("\n", "\r\n")) == (expected + code).replace("\n", "\r\n")
    for kind, admonition in (("NOTE", "note"), ("TIP", "tip"), ("IMPORTANT", 'info "Important"'),
                             ("CAUTION", 'danger "Caution"')):
        assert hook.site_alerts(f"> [!{kind}]\n> Text.\n") == f"!!! {admonition}\n\n    Text.\n"


def test_published_guides_use_github_alerts_and_the_site_gets_admonitions():
    hook = publisher()
    from mkdocs.config import load_config
    from mkdocs.structure.files import Files

    for guide in hook.GUIDES:
        source = re.sub(r"(?ms)^[ \t]*```.*?^[ \t]*```", "", read(hook.SOURCE / guide))
        assert not ADMONITION.search(source), f"{guide}: MkDocs admonitions do not render on GitHub."
    config = load_config(str(ROOT / "documentation" / "gh-io" / "mkdocs.yml"))
    files = config.plugins.on_files(Files([]), config=config)
    deletion = files.get_file_from_path("factory-tools/20-cli-and-api-and-usage.md").content_string
    assert "> [!WARNING]\n> **Resource deletion is destructive.**" in read(hook.SOURCE / hook.GUIDES[2])
    assert "!!! warning\n\n    **Resource deletion is destructive.**" in deletion.replace("\r\n", "\n")
    for guide in hook.GUIDES:
        assert "[!" not in files.get_file_from_path("factory-tools/" + guide).content_string.split("```", 1)[0]


def test_guide21_counts_the_agent_chat_settings_of_the_variables_template():
    settings = agent_chat_settings()
    text = read(GUIDE_21)
    assert {"enableFactoryChatAgent", "enableAIFactoryAgentLiveVoice", "aifactoryAgentEntraAppId"} <= settings
    counts = set(re.findall(r"\b(\w+) settings side by side", text))
    assert counts == {NUMBER_WORDS[len(settings)]}, f"The variables template has {len(settings)}: {sorted(settings)}"
    # The one settings table is on the quickstart; the guide links to it instead of repeating it.
    owner = next(local_target(GUIDE_21, url) for url, _, _ in references(GUIDE_21) if "first-agent-chat.md" in url)
    assert owner.exists() and all(f"| `{setting}` |" in read(owner) for setting in settings)
    assert not re.search(r"(?m)^\| `(enable|aifactoryAgent)\w+` \|", text)


def test_guide21_sends_v125_readers_to_the_one_call_route():
    text = read(GUIDE_21)
    assert "azurefactory esaf upsert-project 001 dev --settings-json" in text
    assert not re.search(r"(?m)^azurefactory config (review|save)", text), "No config review example for v1.25."
    mentions = [part for part in text.split("\n\n") if re.search(r"config (review|save)", part)]
    assert mentions and all("legacy" in part.lower() and "`aifactory`" in part for part in mentions)


def test_cli_readme_scopes_live_voice_to_any_project_in_dev(monkeypatch):
    monkeypatch.syspath_prepend(str(AGENT_FACTORY))
    from agent_factory import agent_live_voice

    assert agent_live_voice.PROJECT_NUMBER.fullmatch("417") and agent_live_voice.ENVIRONMENT == "dev"
    readme = read(CLI_README)
    section = readme.split("### AI Factory Agent live voice options", 1)[1].split("\n## ", 1)[0]
    assert section.startswith(" (any project, Dev)\n")
    assert "project001" not in section and "any project in Dev" in section
    # Links to the earlier heading keep working.
    assert "ai-factory-agent-live-voice-options-project001-dev" in anchors(CLI_README)


def test_cli_timeout_help_and_readme_state_the_real_defaults():
    from azurefactory import cli

    budgets = {"preflight": cli.PREFLIGHT_REQUEST_TIMEOUT_SECONDS, "costs": cli.COST_REQUEST_TIMEOUT_SECONDS,
               "esaf": cli.POLL_TIMEOUT_SECONDS, "otherwise": cli.DEFAULT_REQUEST_TIMEOUT_SECONDS}
    option = next(action for action in cli.build_parser()._actions if "--timeout" in action.option_strings)
    assert re.findall(r"\d+", option.help) == [f"{seconds:g}" for seconds in budgets.values()]
    for word in budgets:
        assert word in option.help
    readme = read(CLI_README)
    section = readme.split("### Read-only deployment preflight", 1)[1].split("\n## ", 1)[0]
    for seconds in budgets.values():
        assert f"{seconds:g}-second" in section
    assert "360-second" not in readme and "60-second" not in readme.replace("360-second", "")


def test_live_voice_readme_lists_only_routes_that_exist_on_this_branch():
    text = read(LIVE_VOICE_README)
    pipelines = [TEMPLATES / "azure-devops" / "esml-yaml-pipelines" / "esml-infra-project" / "infra-project-genai.yaml",
                 TEMPLATES / "azure-devops" / "esml-yaml-pipelines" / "esml-infra-project" / "jobs"
                 / "job-aifactory-agent-live-voice.yaml",
                 TEMPLATES / "github-actions" / "infra-project.yml", TEMPLATES / "github-actions" / "infra-project-phase.yml"]
    shipped = "".join(read(path) for path in pipelines)
    for term in ("refreshKnowledge", "refresh_knowledge"):
        assert term not in text or term in shipped, f"{term} is not a parameter of the shipped project pipelines."
    workflows = [path.name for folder in (TEMPLATES, ROOT / ".github" / "workflows") for path in folder.rglob("*.y*ml")]
    for file_name in set(re.findall(r"`(?:[\w-]+/)*([\w-]+\.ya?ml)`", text)):
        assert file_name in workflows, f"{file_name} is not on this branch."
    assert "add-factory-agent" not in text.lower()
    title, routes = re.search(r"(?m)^## (\w+) ways to run it\n\n((?:\|.*\n)+)", text).groups()
    assert title == {3: "Three", 4: "Four"}[len(routes.splitlines()) - 2]
    assert "add-aifactory-agent-chat" in routes and (ROOT / "bootstrap" / "lib" / "agent_chat_entry.py").exists()


def test_project_team_site_pages_link_to_existing_github_anchors():
    hook = publisher()
    for source in hook.PROJECT_GUIDES.values():
        site = hook.site_markdown(hook.project_excerpt(source.read_text(encoding="utf-8")), source)
        for match in hook.LINK.finditer(site):
            location, _, fragment = match[2].partition("#")
            if location.startswith(hook.GITHUB) and location.endswith(".md") and fragment:
                target = ROOT / location[len(hook.GITHUB):]
                assert fragment.lower() in anchors(target), f"{name(source)}: {match[2]}"


def test_finops_tutorial_file_name_is_spelled_correctly():
    assert FINOPS.exists() and not FINOPS.with_name("tutorial-fiops.md").exists()
    assert read(FINOPS).startswith("# AI Factory tutorial: FinOps monitoring")
    assert "(tutorial-finops.md)" in read(WALKTHROUGH) and "fiops" not in read(WALKTHROUGH).lower()
