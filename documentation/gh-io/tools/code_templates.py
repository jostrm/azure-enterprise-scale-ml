"""Build the two libraries of the site from their data files: code templates and Azure resources.

One data file is the single source of each library. A page asks for a library with a marker, and this hook puts
the generated cards and filters in its place when the site is built, so no generated copy is checked in.
"""

from html import escape
import json
from pathlib import Path
from urllib.parse import quote


SITE = Path(__file__).resolve().parents[1]
REPOSITORY = Path(__file__).resolve().parents[3]
DATA = SITE / "data" / "code_templates.json"
RESOURCES_DATA = SITE / "data" / "azure_resources.json"
VARIABLES = REPOSITORY / "environment_setup" / "aifactory" / "variables.json"
GITHUB_TREE = "https://github.com/jostrm/azure-enterprise-scale-ml/tree/main/"
GITHUB_BLOB = "https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/"
LIBRARY = "<!-- code-templates:library -->"
NUMBERS = "<!-- code-templates:numbers -->"
RESOURCES = "<!-- azure-resources:library -->"


def load():
    return json.loads(DATA.read_text(encoding="utf-8"))


def load_resources():
    """The Azure resources, each with the default of its setting as variables.json has it today."""
    data = json.loads(RESOURCES_DATA.read_text(encoding="utf-8"))
    defaults = json.loads(VARIABLES.read_text(encoding="utf-8-sig"))["dev"]
    for resource in data["resources"]:
        value = defaults.get(resource["setting"])
        resource["default"] = None if value is None else str(value).lower() == "true"
    return data


def chips(group, label, values, counts):
    buttons = "".join(
        f'<button type="button" class="esaf-chip" data-filter="{group}" data-value="{escape(value)}" '
        f'aria-pressed="false">{escape(value)} <span class="esaf-chip__count">{counts[value]}</span></button>'
        for value in values)
    return f'<div class="esaf-library__group"><span class="esaf-library__label">{label}</span>{buttons}</div>'


def toolbar(noun, total):
    return (
        '<div class="esaf-library__bar">'
        f'<input type="search" class="esaf-library__search" placeholder="Search {noun}" aria-label="Search {noun}">'
        f'<span class="esaf-library__count" aria-live="polite"><span data-count>{total}</span> of {total} {noun}</span>'
        '<button type="button" class="esaf-library__clear" data-clear>Clear filters</button>'
        '</div>')


def tags(values, kind):
    return "".join(f'<span class="esaf-tag esaf-tag--{kind}">{escape(value)}</span>' for value in values)


def count(items, key):
    counts = {}
    for item in items:
        for value in (item[key] if isinstance(item[key], list) else [item[key]]):
            counts[value] = counts.get(value, 0) + 1
    return counts


def library(data):
    """The code templates library: a search box, three filter groups and one card for each template."""
    templates = data["templates"]
    cards = []
    for template in templates:
        number = (f'<span class="esaf-card__number" title="Number {template["number"]} on the architecture images">'
                  f'{template["number"]}</span>') if "number" in template else ""
        text = " ".join([template["title"], template["summary"], template["factory"], *template["services"],
                         *template["tags"], template["path"]]).lower()
        links = [f'<a href="{GITHUB_TREE}{quote(template["path"])}">Open the template</a>',
                 f'<a href="{GITHUB_BLOB}{quote(template["readme"])}">Read the guide</a>']
        if "number" in template:
            links.append(f'<a href="../architectures/#the-numbers-on-the-images">See it on the architecture</a>')
        cards.append(
            f'<article class="esaf-card" id="{template["id"]}" data-factory="{escape(template["factory"])}" '
            f'data-service="{escape("|".join(template["services"]))}" data-tag="{escape("|".join(template["tags"]))}" '
            f'data-text="{escape(text)}">'
            f'<h3 class="esaf-card__title">{number}{escape(template["title"])}</h3>'
            f'<p class="esaf-card__summary">{escape(template["summary"])}</p>'
            f'<p class="esaf-card__tags">{tags([template["factory"]], "factory")}{tags(template["services"], "service")}'
            f'{tags(template["tags"], "tag")}</p>'
            f'<p class="esaf-card__path"><code>{escape(template["path"])}</code></p>'
            f'<p class="esaf-card__links">{" ".join(links)}</p>'
            '</article>')
    return (
        '<div class="esaf-library" data-library>'
        + toolbar("templates", len(templates))
        + chips("factory", "Factory", data["factories"], count(templates, "factory"))
        + chips("service", "Azure service", data["services"], count(templates, "services"))
        + chips("tag", "Tag", data["tags"], count(templates, "tags"))
        + '<div class="esaf-library__cards">' + "".join(cards) + '</div>'
        + '<p class="esaf-library__empty" hidden>Nothing matches. Clear a filter or change the search.</p>'
        + '</div>')


def resource_library(data, templates):
    """The Azure resource library: a search box, three filter groups and one card for each resource."""
    resources = data["resources"]
    uses = count(templates["templates"], "services")
    cards = []
    for resource in resources:
        state = {True: "On by default", False: "Off by default", None: "Set in the AI gateway pipeline"}[
            resource["default"]]
        text = " ".join([resource["name"], resource["summary"], resource["setting"], resource["category"],
                         resource["scope"], *resource["kinds"]]).lower()
        links = ['<a href="../parameters/variables/">Its setting in variables.json</a>']
        service = resource.get("template_service")
        if service:
            links.append(f'<a href="../code-templates/?service={quote(service)}">{uses[service]} code '
                         f'template{"s" if uses[service] != 1 else ""} that use it</a>')
        cards.append(
            f'<article class="esaf-card" id="{resource["id"]}" data-category="{escape(resource["category"])}" '
            f'data-kind="{escape("|".join(resource["kinds"]))}" data-scope="{escape(resource["scope"])}" '
            f'data-text="{escape(text)}">'
            f'<h3 class="esaf-card__title">{escape(resource["name"])}</h3>'
            f'<p class="esaf-card__summary">{escape(resource["summary"])}</p>'
            f'<p class="esaf-card__tags">{tags([resource["category"]], "factory")}{tags(resource["kinds"], "tag")}'
            f'{tags([resource["scope"]], "service")}</p>'
            f'<p class="esaf-card__path"><code>{escape(resource["setting"])}</code> {state}</p>'
            f'<p class="esaf-card__links">{" ".join(links)}</p>'
            '</article>')
    scopes = sorted({resource["scope"] for resource in resources}, key=["Project", "Common", "AI gateway pipeline"].index)
    return (
        '<div class="esaf-library" data-library>'
        + toolbar("resources", len(resources))
        + chips("category", "Category", data["categories"], count(resources, "category"))
        + chips("kind", "Kind", data["kinds"], count(resources, "kinds"))
        + chips("scope", "Deployed in", scopes, count(resources, "scope"))
        + '<div class="esaf-library__cards">' + "".join(cards) + '</div>'
        + '<p class="esaf-library__empty" hidden>Nothing matches. Clear a filter or change the search.</p>'
        + '</div>')


def numbers_table(data):
    """The table under the architecture images: one row for each numbered circle."""
    rows = ["| No. | Code template | What you build with it | Where on the image | Code |", "|---|---|---|---|---|"]
    numbered = sorted((template for template in data["templates"] if "number" in template),
                      key=lambda template: template["number"])
    for template in numbered:
        rows.append(
            f'| **{template["number"]}** | [{template["title"]}](code-templates/index.md#{template["id"]}) '
            f'| {template["summary"]} | {data["places"][template["place"]]} '
            f'| [`{template["path"].split("/", 1)[1]}`]({GITHUB_TREE}{quote(template["path"])}) |')
    return "\n".join(rows)


def render(markdown, data=None, resources=None):
    """Replace each library marker on a page with the library it asks for."""
    if LIBRARY in markdown or NUMBERS in markdown or RESOURCES in markdown:
        data = data or load()
        markdown = markdown.replace(LIBRARY, library(data)).replace(NUMBERS, numbers_table(data))
        if RESOURCES in markdown:
            markdown = markdown.replace(RESOURCES, resource_library(resources or load_resources(), data))
    return markdown


def on_page_markdown(markdown, page, config, files):
    return render(markdown)
