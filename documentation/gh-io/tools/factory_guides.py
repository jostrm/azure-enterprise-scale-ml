"""Publish the maintained Factory guides and end-user docs without keeping a second Markdown copy."""

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
V2 = REPOSITORY / "documentation" / "v2"
# The end-user docs, published from their single source: site path -> source page, in navigation order.
DOCS_PAGES = {
    "setup/index.md": V2 / "quickstarts" / "README.md",
    **{"setup/" + name: V2 / "quickstarts" / name for name in (
        "01-install-esaf.md", "02-create-factory.md", "add-scale-set.md", "03-add-project.md",
        "04-first-agent-chat.md", "05-clean-up.md")},
    "usage/index.md": V2 / "usage" / "README.md",
    **{"usage/" + name: V2 / "usage" / name for name in (
        "prerequisites.md", "01-first-agent.md", "02-first-ml-model.md", "dashboards.md")},
    "reference/scenarios.md": V2 / "reference" / "scenarios.md",
    "reference/hub-and-network-modes.md": V2 / "concepts" / "hub-and-network-modes.md",
    "reference/folder-structure.md": V2 / "reference" / "folder-structure.md",
    "reference/settings.md": V2 / "reference" / "settings.md",
}
DOCS_SECTIONS = ("factory-tools/", "setup/", "usage/", "reference/")
# Images a docs page shows are copied into the site under this folder, so no page depends on another host.
ASSETS = "assets/repository/"
IMAGE_SUFFIXES = (".png", ".gif", ".svg", ".jpg", ".jpeg", ".webp")
SITE_SOURCES = {
    **{(SOURCE / name).resolve(): "factory-tools/" + name for name in GUIDES},
    **{path.resolve(): uri for uri, path in PROJECT_GUIDES.items()},
    **{path.resolve(): uri for uri, path in DOCS_PAGES.items()},
    (V2 / "README.md").resolve(): "index.md",  # the docs hub on GitHub is the site's home page
}
PROJECT_HOME = """# Get started - Agent & ML Factory SDK: Project team

Build the code of your workload in your project. The shared engines of the factories stay as they are.
To configure and administer the Factory itself, use the
[core-team CLI, Python SDK and REST tutorials](../factory-tools/18-cli-and-api-and-usage.md).

| Your workload | Start here | Your first result |
| --- | --- | --- |
| Agent, RAG or multi-agent application | [Agent Factory SDK](agent-factory.md#project-team-quickstart) | List the catalog, then make a plan for one target without calling Azure. |
| Machine-learning model | [ML Model Factory SDK](ml-model-factory.md#project-team-quickstart) | Validate a scenario and see its route. You can also train on a local CSV file. |

Looking for a template to start from? Search the [code templates library](../code-templates/index.md).

## Work on your machine first

1. Copy the examples into the repository of your project, and keep your configuration there.
2. Install the packages into the Python environment of the component, rather than upgrading them globally.
3. Keep tenant settings, credentials and generated files out of a public repository.
4. Run the offline examples first. They need no Azure sign-in and create nothing in Azure.
5. Before a live step, check the target with your platform team: the identity, the private network, the terms
   of the dataset and the budget. A live step stops when the project lacks something it needs. Fix that
   first, then run it again.

Each tutorial links to its full guide, the source code and the notebooks.
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
TOOL_TAB = re.compile(
    r'^<details markdown="1" data-factory-tool="([^"]+)"(?: open)?>\r?\n'
    r'<summary>\1</summary>\r?\n\r?\n(.*?)'
    r'^</details>\r?\n<!-- /factory-tool -->\r?\n?',
    re.M | re.S,
)
DETAILS = re.compile(r"^<details( open)?>\r?\n<summary>([^<\n]+)</summary>\r?\n(.*?)^</details>[ \t]*\r?\n", re.M | re.S)
HTML_URL = re.compile(r'\b(src|srcset|href)="([^"]+)"')
BREADCRUMB = re.compile(r"\A\[Docs\]\([^)\n]*\)[^\n]*\n+")
ALERT = re.compile(r"> ?\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\][ \t]*")
ADMONITIONS = {"NOTE": "note", "TIP": "tip", "IMPORTANT": 'info "Important"', "WARNING": "warning",
               "CAUTION": 'danger "Caution"'}


def site_alerts(text):
    """Render GitHub alerts (`> [!NOTE]`) as Material admonitions: the site has no alert extension."""
    result, fence, alert = [], None, False
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        ending = line[len(body):]
        marker = FENCE.match(line)
        if marker and fence is None:
            fence = marker[1]
        elif marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
            fence = None
        kind = None if fence or marker else ALERT.fullmatch(body)
        if kind:
            alert = True
            result.append(f"!!! {ADMONITIONS[kind[1]]}{ending}{ending}")
        elif alert and not marker and body.startswith(">"):
            content = body[1:].removeprefix(" ")
            result.append(("    " + content if content else "") + ending)
        else:
            alert = False
            result.append(line)
    return "".join(result)


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


def indented(body):
    return "\n".join("    " + line if line.strip() else "" for line in body.strip("\r\n").splitlines())


def tool_tabs(text):
    """Render every tool selector of a docs page as a Material tab set; adjacent sections form one set."""
    return TOOL_TAB.sub(lambda section: f'=== "{section[1]}"\n\n{indented(section[2])}\n\n', text)


def collapsibles(text):
    """Render plain <details> blocks as collapsible notes: Markdown inside raw HTML is not rendered on the site."""
    def note(block):
        title = block[2].strip().replace('"', "'")
        return f'{"???+" if block[1] else "???"} note "{title}"\n\n{indented(block[3])}\n\n'
    return DETAILS.sub(note, text)


def project_excerpt(text):
    """Publish only the canonical onboarding section, not the entire source guide."""
    start, end = "<!-- project-team:start -->", "<!-- project-team:end -->"
    if text.count(start) != 1 or text.count(end) != 1 or text.index(start) >= text.index(end):
        raise ValueError("A project-team guide requires exactly one ordered start/end marker pair.")
    return text.split(start, 1)[1].split(end, 1)[0].strip() + "\n"


def site_url(url, source, repository=REPOSITORY, assets=None, html=False):
    """Where a source-relative URL points on the site: a site page, a copied image, or the file on GitHub.

    MkDocs rewrites Markdown links itself, so those stay relative to the source page. It leaves HTML attributes
    alone: with html=True the result is relative to the page's URL folder, and a page is named by its URL.
    """
    if url.startswith(("#", "/", "//")) or re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", url):
        return url
    location, separator, fragment = url.partition("#")
    target = (source.parent / unquote(location)).resolve()
    mapped = SITE_SOURCES.get(target)
    source_uri = SITE_SOURCES.get(source.resolve())
    folder = posixpath.dirname(source_uri) if source_uri else ""
    if html and source_uri and posixpath.basename(source_uri) != "index.md":
        folder = source_uri[:-len(".md")]
    if assets is not None and source_uri and target.suffix.lower() in IMAGE_SUFFIXES and target.is_file():
        asset = ASSETS + target.relative_to(repository.resolve()).as_posix()
        assets[asset] = target
        destination = posixpath.relpath(asset, folder)
    elif mapped and source_uri and (
        mapped.startswith(DOCS_SECTIONS) or not fragment or fragment == "project-team-quickstart"
    ):
        if html:
            page_url = posixpath.dirname(mapped) if posixpath.basename(mapped) == "index.md" else mapped[:-len(".md")]
            relative = posixpath.relpath(page_url or ".", folder or ".")
            destination = "./" if relative == "." else relative + "/"
        else:
            destination = posixpath.relpath(mapped, folder)
    elif target.parent == source.parent.resolve() and target.name in GUIDES:
        destination = target.name
    else:
        relative = target.relative_to(repository.resolve())
        destination = GITHUB + quote(relative.as_posix(), safe="/")
    return destination + ("#" + fragment if separator else "")


def outside_fences(text, rewrite):
    """Apply `rewrite` to every line that is not inside a fenced code block."""
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
            result.append(line if fence else rewrite(line))
    return "".join(result)


def site_markdown(text, source, repository=REPOSITORY, assets=None):
    """Keep tutorial links local; point other source-relative links to GitHub."""
    source, repository = Path(source), Path(repository)
    return outside_fences(text, lambda line: LINK.sub(
        lambda match: match[1] + site_url(match[2], source, repository, assets) + match[3], line))


def site_html(text, source, repository=REPOSITORY, assets=None):
    """The same for the URLs of HTML tags (<a>, <img>, <source>), which the docs use for sized images."""
    source, repository = Path(source), Path(repository)
    return outside_fences(text, lambda line: HTML_URL.sub(
        lambda match: f'{match[1]}="{site_url(match[2], source, repository, assets, html=True)}"', line))


def docs_page(text, source, assets):
    """One end-user docs page as the site shows it: tabs, collapsible notes, admonitions and site links."""
    text = collapsibles(tool_tabs(site_alerts(BREADCRUMB.sub("", text))))
    return site_html(site_markdown(text, source, assets=assets), source, assets=assets)


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
        content = "---\nhide:\n  - toc\n---\n\n" + site_markdown(linked_tabs(site_alerts(text)), path)
        append(uri, content)
    append("project-team/index.md", PROJECT_HOME)
    for uri, path in PROJECT_GUIDES.items():
        title = "Agent Factory SDK" if uri.endswith("/agent-factory.md") else "ML Model Factory SDK"
        source_url = GITHUB + quote(path.relative_to(REPOSITORY).as_posix(), safe="/")
        content = f"# {title}\n\n[Maintained source guide]({source_url}#project-team-quickstart)\n\n"
        content += site_markdown(project_excerpt(path.read_text(encoding="utf-8")), path)
        append(uri, content)
    assets = {}
    for uri, path in DOCS_PAGES.items():
        append(uri, docs_page(path.read_text(encoding="utf-8"), path, assets))
    for uri, path in sorted(assets.items()):
        if files.get_file_from_path(uri) is None:
            files.append(File.generated(config, uri, abs_src_path=str(path)))
    return files
