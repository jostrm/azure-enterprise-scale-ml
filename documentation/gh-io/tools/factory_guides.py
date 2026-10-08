"""Publish the maintained Factory guides without keeping a second Markdown copy."""

from pathlib import Path
import re
from urllib.parse import quote, unquote

from mkdocs.structure.files import File


GUIDES = tuple(f"{number}-cli-and-api-and-usage.md" for number in (18, 19, 20))
REPOSITORY = Path(__file__).resolve().parents[3]
SOURCE = REPOSITORY / "documentation" / "v2" / "10-19"
GITHUB = "https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/"
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


def site_markdown(text, source, repository=REPOSITORY):
    """Keep tutorial links local; point other source-relative links to GitHub."""
    source, repository = Path(source), Path(repository)

    def replace(match):
        url = match[2]
        if url.startswith(("#", "/", "//")) or re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", url):
            return match[0]
        location, separator, fragment = url.partition("#")
        target = (source.parent / unquote(location)).resolve()
        if target.parent == source.parent.resolve() and target.name in GUIDES:
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
    for name in GUIDES:
        path = SOURCE / name
        uri = "factory-tools/" + name
        if files.get_file_from_path(uri) is not None:
            raise ValueError(f"Factory guide has a duplicate site source: {uri}")
        text = path.read_text(encoding="utf-8")
        # A combined TOC would expose headings from the two inactive tool views.
        content = "---\nhide:\n  - toc\n---\n\n" + site_markdown(linked_tabs(text), path)
        files.append(File.generated(config, uri, content=content))
    return files
