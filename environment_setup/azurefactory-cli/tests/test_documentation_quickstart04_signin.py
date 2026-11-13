"""Quickstart 04 sets up the sign-in registration that a new reader can actually run (video 10, 2026-11-13).

`python -m aifactory_agent.browser_auth` failed on pydantic: the page never created the agent folder's virtual
environment. And the registration had one fixed name for the whole tenant, so a second Factory or project hit
"configuration drift" although the page says it's done once per project.
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PAGE = Path(os.environ.get("ESAF_QUICKSTART04", ROOT / "documentation" / "v2" / "quickstarts" / "04-first-agent-chat.md"))
AGENT = ROOT / "usecase_code" / "40-agent-factory" / "40-aifactory-agent"


def section(text: str, heading: str) -> str:
    start = text.index("\n## " + heading + "\n")
    end = text.find("\n## ", start + 1)
    return text[start:end if end > 0 else len(text)]


def signin() -> str:
    return section(PAGE.read_text(encoding="utf-8"), "Create the sign-in registration")


def test_sign_in_section_creates_the_agent_environment_before_running_the_tool():
    text = signin()
    steps = ["Set-Location .\\azure-enterprise-scale-ml\\usecase_code\\40-agent-factory\\40-aifactory-agent",
             "py -3.12 -m venv .venv",
             ".\\.venv\\Scripts\\python.exe -m pip install -r requirements.lock.txt",
             ".\\.venv\\Scripts\\python.exe -m pip install -e ..\\..\\..\\environment_setup\\azurefactory-cli",
             ".\\.venv\\Scripts\\python.exe -m aifactory_agent.browser_auth"]
    positions = [text.index(step) for step in steps]
    assert positions == sorted(positions)
    assert "\n   python -m aifactory_agent.browser_auth" not in text     # never the global interpreter


def test_documented_install_files_exist_and_carry_what_browser_auth_imports():
    assert any(line.lower().startswith("pydantic==") for line in
               (AGENT / "requirements.lock.txt").read_text(encoding="utf-8").splitlines())
    assert (AGENT / ".." / ".." / ".." / "environment_setup" / "azurefactory-cli" / "pyproject.toml").resolve().is_file()
    # browser_auth -> config -> actions imports the azurefactory package, so the CLI install is not optional.
    assert "from azurefactory." in (AGENT / "aifactory_agent" / "actions.py").read_text(encoding="utf-8")


def test_each_project_gets_its_own_named_registration():
    text = signin()
    assert "once per project" in text
    assert "Enterprise Scale AI Factory Agent (aifactory-agent-project001-dev." in text
    assert "`display_name`" in text and "--display-name" in text
    assert "**Enterprise Scale AI Factory Agent** enterprise application" not in text


def test_agent_readme_explains_per_project_names_and_the_legacy_name():
    readme = (AGENT / "readme.md").read_text(encoding="utf-8")
    auth = readme[readme.index("## Authentication, tools and approvals"):]
    assert "--display-name" in auth
    assert "Enterprise Scale AI Factory Agent (<app>.<environment>)" in auth
    assert "legacy" in auth.lower() and "same redirect URI" in auth
