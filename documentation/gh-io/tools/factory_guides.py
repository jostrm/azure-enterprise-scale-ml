"""Publish the maintained Factory guides without keeping a second Markdown copy."""

from pathlib import Path
import posixpath
import re
from urllib.parse import quote, unquote

from mkdocs.structure.files import File


GUIDES = tuple(f"{number}-cli-and-api-and-usage.md" for number in (18, 19, 20))
REPOSITORY = Path(__file__).resolve().parents[3]
SOURCE = REPOSITORY / "documentation" / "v2" / "10-19"
GITHUB = "https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/"
PROJECT_GUIDES = {
    "project-team/agent-factory.md": REPOSITORY / "usecase_code" / "40-agent-factory" / "agent_factory" / "readme.md",
    "project-team/ml-model-factory.md": REPOSITORY / "usecase_code" / "50-ml-model-factory" / "user-config" / "readme.md",
}
SITE_SOURCES = {
    **{(SOURCE / name).resolve(): "factory-tools/" + name for name in GUIDES},
    **{path.resolve(): uri for uri, path in PROJECT_GUIDES.items()},
}
PROJECT_HOME = """# Get started - Agent & ML Factory SDK: Project team

Build workload code in your project without changing the shared factory engines.
For factory configuration and administration, use the
[core-team CLI, Python SDK and REST tutorials](../factory-tools/18-cli-and-api-and-usage.md).

| Your workload | Start here | First safe result |
| --- | --- | --- |
| Agent, RAG or multi-agent application | [Agent Factory SDK](agent-factory.md#project-team-quickstart) | Inspect the catalog, then make an offline single-target plan. |
| Machine-learning model | [ML Model Factory SDK](ml-model-factory.md#project-team-quickstart) | Validate a scenario and inspect its route; optionally train on a reviewed local CSV. |

## Work locally before choosing a cloud target

1. Use a project-owned copy of the purple examples; keep configuration in the orange project.
2. Choose the documented component environment and dependencies, not a global package upgrade.
3. Keep tenant settings, resource selections, credentials and generated artifacts out of public Git.
4. Run the offline examples first. Local files, rendered jobs and catalog entries are **not deployment evidence**.
5. Optional live steps require an operator-reviewed target, approved identity/private connectivity,
   dataset terms, cost budget and passing quality gates. Cloud routes can fail on missing prerequisites;
   do not bypass gates or assume every template is live-validated.

These pages reuse marked sections of the maintained source guides. The full guides,
source code and notebook examples remain linked from each tutorial.
"""
LINK = re.compile(r"(!?\[[^\]\n]*\]\()([^\s)]+)(\))")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
TOOLS = ("CLI (PowerShell)", "Python SDK", "REST (curl)")
TOOL_SECTION = re.compile(
    r'^<details markdown="1" data-factory-tool="([^"]+)">\r?\n'
    r'<summary>\1</summary>\r?\n\r?\n(.*?)'
    r'^</details>\r?\n<!-- /factory-tool -->',
    re.M | re.S,
)


def linked_tabs(text):
    """Render GitHub-readable collapsible tool sections as one Material tab set."""
    sections = list(TOOL_SECTION.finditer(text))
    if [section[1] for section in sections] != list(TOOLS):
        raise ValueError("Factory guide requires exactly one CLI, Python SDK and REST section, in that order.")
    for left, right in zip(sections, sections[1:]):
        if text[left.end():right.start()].strip():
            raise ValueError("Tool sections must be adjacent to form one whole-page selector.")

    def tab(section):
        content = "\n".join("    " + line if line else "" for line in section[2].rstrip().splitlines())
        return f'=== "{section[1]}"\n\n{content}\n'

    return TOOL_SECTION.sub(tab, text)


def project_excerpt(text):
    """Publish only the canonical onboarding section, not the entire source guide."""
    start, end = "<!-- project-team:start -->", "<!-- project-team:end -->"
    if text.count(start) != 1 or text.count(end) != 1 or text.index(start) >= text.index(end):
        raise ValueError("A project-team guide requires exactly one ordered start/end marker pair.")
    return text.split(start, 1)[1].split(end, 1)[0].strip() + "\n"


def site_markdown(text, source, repository=REPOSITORY):
    """Keep tutorial links local; point other source-relative links to GitHub."""
    source, repository = Path(source), Path(repository)

    def replace(match):
        url = match[2]
        if url.startswith(("#", "/", "//")) or re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", url):
            return match[0]
        location, separator, fragment = url.partition("#")
        target = (source.parent / unquote(location)).resolve()
        mapped = SITE_SOURCES.get(target)
        source_uri = SITE_SOURCES.get(source.resolve())
        if mapped and source_uri and (
            mapped.startswith("factory-tools/") or not fragment or fragment == "project-team-quickstart"
        ):
            destination = posixpath.relpath(mapped, posixpath.dirname(source_uri))
        elif target.parent == source.parent.resolve() and target.name in GUIDES:
            destination = target.name
        else:
            relative = target.relative_to(repository.resolve())
            destination = GITHUB + quote(relative.as_posix(), safe="/")
        if separator:
            destination += "#" + fragment
        return match[1] + destination + match[3]

    result, fence = [], None
    for line in text.splitlines(keepends=True):
        marker = FENCE.match(line)
        if marker:
            token = marker[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            result.append(line)
        else:
            result.append(line if fence else LINK.sub(replace, line))
    return "".join(result)


def on_files(files, config):
    def append(uri, content):
        if files.get_file_from_path(uri) is not None:
            raise ValueError(f"Factory guide has a duplicate site source: {uri}")
        files.append(File.generated(config, uri, content=content))

    for name in GUIDES:
        path = SOURCE / name
        uri = "factory-tools/" + name
        text = path.read_text(encoding="utf-8")
        # A combined TOC would expose headings from the two inactive tool views.
        content = "---\nhide:\n  - toc\n---\n\n" + site_markdown(linked_tabs(text), path)
        append(uri, content)
    append("project-team/index.md", PROJECT_HOME)
    for uri, path in PROJECT_GUIDES.items():
        title = "Agent Factory SDK" if uri.endswith("/agent-factory.md") else "ML Model Factory SDK"
        source_url = GITHUB + quote(path.relative_to(REPOSITORY).as_posix(), safe="/")
        content = f"# {title}\n\n[Maintained source guide]({source_url}#project-team-quickstart)\n\n"
        content += site_markdown(project_excerpt(path.read_text(encoding="utf-8")), path)
        append(uri, content)
    return files
