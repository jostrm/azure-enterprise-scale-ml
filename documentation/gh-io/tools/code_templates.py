"""Build the two libraries of the site from their data files: code templates and Azure resources.

One data file is the single source of each library. A page asks for a library with a marker, and this hook puts
the generated cards and filters in its place when the site is built, so no generated copy is checked in.
Both libraries use the same search box, the same filter checkboxes and the same cards.
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
RESOURCE_COUNT = "<!-- azure-resources:count -->"
SWITCH_COUNT = "<!-- azure-resources:switches -->"
STATES = ("On by default", "Off by default", "Set when you create the Factory", "No switch")


def load():
    return json.loads(DATA.read_text(encoding="utf-8"))


def load_resources():
    """The Azure resources, each with its state as variables.json has it today."""
    data = json.loads(RESOURCES_DATA.read_text(encoding="utf-8"))
    defaults = json.loads(VARIABLES.read_text(encoding="utf-8-sig"))["dev"]
    areas = {category: area for area, members in data["areas"].items() for category in members}
    for resource in data["resources"]:
        resource["areas"] = list(dict.fromkeys(areas[name] for name in resource["categories"] if name in areas))
        resource["in_variables"] = [setting for setting in resource["settings"] if setting in defaults]
        if not resource["settings"]:
            resource["state"] = "No switch"
        elif not resource["in_variables"]:
            resource["state"] = "Set when you create the Factory"
        else:
            # The first setting is the switch unless "switch" names another. on_when is the value that means on.
            value = str(defaults[resource.get("switch", resource["settings"][0])]).lower()
            resource["state"] = "On by default" if value == resource.get("on_when", "true") else "Off by default"
    return data


def checkboxes(group, label, values, counts):
    """One row of filter checkboxes. Checked boxes of one row widen the choice, rows narrow each other."""
    boxes = "".join(
        f'<label class="esaf-chip"><input type="checkbox" data-filter="{group}" data-value="{escape(value)}"> '
        f'{escape(value)} <span class="esaf-chip__count">{counts[value]}</span></label>'
        for value in values)
    return (f'<div class="esaf-library__group" role="group" aria-label="{label}">'
            f'<span class="esaf-library__label">{label}</span>{boxes}</div>')


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


def shell(noun, total, filters, cards):
    return (
        '<div class="esaf-library" data-library>' + toolbar(noun, total) + "".join(filters)
        + '<div class="esaf-library__cards">' + "".join(cards) + '</div>'
        + '<p class="esaf-library__empty" hidden>Nothing matches. Clear a filter or change the search.</p></div>')


def library(data):
    """The code templates library: a search box, three rows of filters and one card for each template."""
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
            links.append('<a href="../architectures/#the-numbers-on-the-images">See it on the architecture</a>')
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
    filters = [checkboxes("factory", "Factory", data["factories"], count(templates, "factory")),
               checkboxes("service", "Azure service", data["services"], count(templates, "services")),
               checkboxes("tag", "Tag", data["tags"], count(templates, "tags"))]
    return shell("templates", len(templates), filters, cards)


def resource_library(data, templates):
    """The Azure resource library: a search box, three rows of filters and one card for each resource."""
    resources = data["resources"]
    uses = count(templates["templates"], "services")
    categories = [category for members in data["areas"].values() for category in members] + [data["cross_category"]]
    cards = []
    for resource in resources:
        text = " ".join([resource["name"], resource["summary"], *resource["settings"], *resource["categories"],
                         *resource["areas"], resource["state"]]).lower()
        settings = " ".join(
            f'<a href="../parameters/variables/#{setting}"><code>{setting}</code></a>'
            if setting in resource["in_variables"] else f"<code>{setting}</code>" for setting in resource["settings"])
        state = resource.get("without_setting", resource["state"])
        links = []
        service = resource.get("template_service")
        if service:
            links.append(f'<a href="../code-templates/?service={quote(service)}">{uses[service]} code '
                         f'template{"s" if uses[service] != 1 else ""} that use it</a>')
        cards.append(
            f'<article class="esaf-card" id="{resource["id"]}" data-area="{escape("|".join(resource["areas"]))}" '
            f'data-category="{escape("|".join(resource["categories"]))}" data-state="{escape(resource["state"])}" '
            f'data-text="{escape(text)}">'
            f'<h3 class="esaf-card__title">{escape(resource["name"])}</h3>'
            f'<p class="esaf-card__summary">{escape(resource["summary"])}</p>'
            f'<p class="esaf-card__tags">{tags(resource["areas"], "factory")}{tags(resource["categories"], "service")}</p>'
            f'<p class="esaf-card__path">{settings} <span class="esaf-card__state">{escape(state)}</span></p>'
            f'<p class="esaf-card__links">{" ".join(links)}</p>'
            '</article>')
    states = [state for state in STATES if any(resource["state"] == state for resource in resources)]
    filters = [checkboxes("area", "Area", list(data["areas"]), count(resources, "areas")),
               checkboxes("category", "Category", categories, count(resources, "categories")),
               checkboxes("state", "Switch", states, count(resources, "state"))]
    return shell("resources", len(resources), filters, cards)


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
    if LIBRARY in markdown or NUMBERS in markdown:
        data = data or load()
        markdown = markdown.replace(LIBRARY, library(data)).replace(NUMBERS, numbers_table(data))
    if RESOURCES in markdown:
        resources = resources or load_resources()
        switchable = sum(1 for resource in resources["resources"] if resource["settings"])
        markdown = (markdown.replace(RESOURCES, resource_library(resources, data or load()))
                    .replace(RESOURCE_COUNT, f'**{len(resources["resources"])}**')
                    .replace(SWITCH_COUNT, f"**{switchable}**"))
    return markdown


def on_page_markdown(markdown, page, config, files):
    return render(markdown)
