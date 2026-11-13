"""Draw the three ESAF architecture images, one for each hub mode, as SVG.

    python documentation/gh-io/tools/generate_architecture.py            # write the three SVG files
    python documentation/gh-io/tools/generate_architecture.py --check    # fail when a checked-in SVG is stale
    python documentation/gh-io/tools/generate_architecture.py --png      # also write the PNG stills (Playwright)

The numbered blue circles come from documentation/gh-io/data/code_templates.json: a template with a "number" gets
a circle at its "place". The names come from documentation/gh-io/data/azure_resources.json: every resource of
the Azure resource library is on the images. The icons are in architecture_icons/ (see its README): SVG files,
or a PNG file for a product without an official SVG. A product in TILES has no icon and is drawn as a lettered
dark tile.
"""

import argparse
import base64
import json
from pathlib import Path
import re
import sys
from xml.sax.saxutils import escape

SITE = Path(__file__).resolve().parents[1]
DATA = SITE / "data" / "code_templates.json"
RESOURCES = SITE / "data" / "azure_resources.json"
ICONS = Path(__file__).resolve().parent / "architecture_icons"
OUTPUT = SITE / "docs" / "assets" / "architecture"
WIDTH, HEIGHT = 1600, 1300
HUB_HEIGHT = HEIGHT - 20 - 566   # the hub box ends where the AI Factory box ends
FONT = "Segoe UI, Roboto, Helvetica, Arial, sans-serif"

# Colors carry meaning: blue is neutral, purple is the AI Factory, pink is a project. No red and no orange.
PALETTE = {
    "canvas": "#FFFFFF", "ink": "#1B2A3A", "muted": "#566575", "line": "#6B7785",
    "blue": "#5AA9FF", "blue_tint": "#F4F9FF", "blue_bar": "#DFEDFF",
    "purple": "#B07CFF", "purple_tint": "#FAF7FF", "purple_bar": "#EBE0FF",
    "pink": "#FF6FD8", "pink_tint": "#FFF9FD", "pink_bar": "#FFE3F6",
    "box": "#191919", "light": "#ECF6FF",
}
BLUE = PALETTE["blue"]
MODES = {
    "external-hub": {
        "title": "ESAF with an external hub",
        "summary": "The AI Factory connects to a hub that you already own. The hub gives the VPN or ExpressRoute "
                   "connection, the firewall and the private DNS zones.",
    },
    "own-hub": {
        "title": "ESAF standalone, with its own hub",
        "summary": "The AI Factory creates its own hub in its Dev network, with a VPN gateway, a DNS resolver and "
                   "Bastion. The private DNS zones live in the common resource group.",
    },
    "standalone": {
        "title": "ESAF standalone, without a hub",
        "summary": "The AI Factory has no hub. People reach the services over the internet from allowed IP "
                   "addresses, with hybrid or public networking.",
    },
}
# Where the circle of a place sits: the key of the icon it belongs to.
PLACES = {
    "teams": "teams", "voice": "voice", "fabric": "fabric", "fabric-iq": "fabric-tool", "sharepoint": "sharepoint",
    "mcp": "tools", "gateway": "apim", "ml": "aml", "agents": "prompt", "hosted": "hosted", "search": "search",
    "ingestion": "adf", "chat": "chat-agent", "model-factory": "aml", "functions": "functions",
    "functions-storage": "storage", "starter-rag": "models", "starter-fabric": "fabric-agent",
}
# Products without an official icon in the Microsoft icon sets: the letters and the border color of their tile.
TILES = {"sharepoint": ("SP", "blue"), "kong": ("K", "blue"), "pipelines": ("CI", "blue"), "bing": ("B", "blue"),
         "elasticsearch": ("ES", "blue"), "factory-apps": ("ESAF", "purple")}


def load():
    return json.loads(DATA.read_text(encoding="utf-8"))


def icon_file(name):
    """The file of an icon: an SVG, or a PNG for a product without an official SVG. None for a lettered tile."""
    return next((path for path in (ICONS / f"{name}.svg", ICONS / f"{name}.png") if path.is_file()), None)


def symbol(name):
    """One icon file as an SVG symbol. Its ids get a prefix, so that two icons never share a gradient."""
    path = icon_file(name)
    if path.suffix == ".png":
        # A PNG says its width and height in bytes 16 to 24. The picture goes into the image unchanged.
        data = path.read_bytes()
        width, height = (int.from_bytes(data[start:start + 4], "big") for start in (16, 20))
        picture = base64.b64encode(data).decode("ascii")
        return (f'<symbol id="icon-{name}" viewBox="0 0 {width} {height}">'
                f'<image width="{width}" height="{height}" href="data:image/png;base64,{picture}"/></symbol>')
    text = path.read_text(encoding="utf-8")
    opening = re.search(r"<svg\b[^>]*>", text)[0]
    box = re.search(r'viewBox="([^"]+)"', opening)
    # The Fabric icons have a width and a height instead of a viewBox, and set the fill on the root element.
    box = box[1] if box else "0 0 {} {}".format(*(re.search(rf'\b{side}="([\d.]+)', opening)[1]
                                                  for side in ("width", "height")))
    fill = re.search(r'\bfill="([^"]+)"', opening)
    inherited = f' fill="{fill[1]}"' if fill else ""
    body = text[text.index(opening) + len(opening):text.rindex("</svg>")]
    body = re.sub(r"<(title|desc)>.*?</\1>", "", body, flags=re.S)
    body = re.sub(r'\bid="([^"]+)"', lambda match: f'id="{name}-{match[1]}"', body)
    body = re.sub(r"url\(#([^)]+)\)", lambda match: f"url(#{name}-{match[1]})", body)
    body = re.sub(r'href="#([^"]+)"', lambda match: f'href="#{name}-{match[1]}"', body)
    return f'<symbol id="icon-{name}" viewBox="{box}"{inherited}>{body.strip()}</symbol>'


def names():
    """The label of each resource on the images, from the Azure resource library: one name in both places."""
    resources = json.loads(RESOURCES.read_text(encoding="utf-8"))["resources"]
    return {resource["id"]: resource["label"] for resource in resources if "label" in resource}


class Drawing:
    def __init__(self):
        self.parts, self.icons, self.at, self.names = [], [], {}, names()

    def add(self, text):
        self.parts.append(text)

    def text(self, x, y, value, size=11, weight="400", color="ink", anchor="start", style=""):
        self.add(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{PALETTE[color]}" '
                 f'text-anchor="{anchor}"{style}>{escape(value)}</text>')

    def lines(self, x, y, values, size=11, color="ink", anchor="middle", step=13, weight="400", style=""):
        spans = "".join(f'<tspan x="{x}" dy="{0 if index == 0 else step}">{escape(value)}</tspan>'
                        for index, value in enumerate(values))
        self.add(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{PALETTE[color]}" '
                 f'text-anchor="{anchor}"{style}>{spans}</text>')

    def named(self, items):
        """The lines of a label, and the attribute that says which resources of the library it names.

        An item that starts with @ is the id of a resource: it becomes the name of that resource.
        """
        lines = [line for item in items for line in (self.names[item[1:]] if item.startswith("@") else [item])]
        resources = " ".join(item[1:] for item in items if item.startswith("@"))
        return lines, f' data-resource="{resources}"' if resources else ""

    def container(self, x, y, w, h, title, tone, note="", dashed=False):
        """A box with a title bar. A title can be a list, with the id of a resource in it: see `named`."""
        title, resources = self.named(title) if isinstance(title, list) else ([title], "")
        dash = ' stroke-dasharray="6 4"' if dashed else ""
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{PALETTE[tone + "_tint"]}" '
                 f'stroke="{PALETTE[tone]}" stroke-width="1.5"{dash}/>')
        self.add(f'<path d="M{x + 1} {y + 26} V{y + 8} a7 7 0 0 1 7 -7 H{x + w - 8} a7 7 0 0 1 7 7 V{y + 26} Z" '
                 f'fill="{PALETTE[tone + "_bar"]}"/>')
        self.text(x + 12, y + 18, " ".join(title), size=12.5, weight="700", style=resources)
        if note:
            self.text(x + w - 12, y + 18, note, size=11, color="muted", anchor="end")

    def icon(self, key, name, cx, top, label, size=30):
        """An icon with its label underneath. `key` names the spot for circles and arrows."""
        self.at[key] = (cx, top)
        label, resources = self.named(label)
        if icon_file(name):
            if name not in self.icons:
                self.icons.append(name)
            self.add(f'<use href="#icon-{name}" x="{cx - size / 2:g}" y="{top}" width="{size}" height="{size}"/>')
        else:
            letters, tone = TILES[name]
            self.add(f'<rect x="{cx - size / 2:g}" y="{top}" width="{size}" height="{size}" rx="7" '
                     f'fill="{PALETTE["box"]}" stroke="{PALETTE[tone]}" stroke-width="2"/>')
            self.text(cx, top + size / 2 + (4 if len(letters) < 3 else 3.5), letters, size=12 if len(letters) < 3 else 9,
                      weight="700", color="light", anchor="middle")
        self.lines(cx, top + size + 14, label, style=resources)

    def arrow(self, points, dashed=False, label="", label_at=None, anchor="middle"):
        dash = ' stroke-dasharray="5 4"' if dashed else ""
        path = " ".join(f"{x:g},{y:g}" for x, y in points)
        self.add(f'<polyline points="{path}" fill="none" stroke="{PALETTE["line"]}" stroke-width="1.6"{dash} '
                 'marker-end="url(#arrow)"/>')
        if label:
            x, y = label_at
            self.text(x, y, label, size=10.5, color="muted", anchor=anchor)

    def number(self, number, template, cx, cy):
        self.add(
            f'<a href="../../code-templates/#{template["id"]}" target="_top">'
            f'<g class="template-number" data-template="{template["id"]}">'
            f'<title>{number}. {escape(template["title"])}</title>'
            f'<circle cx="{cx:g}" cy="{cy:g}" r="10.5" fill="{BLUE}" stroke="{PALETTE["canvas"]}" stroke-width="2"/>'
            f'<text x="{cx:g}" y="{cy + 4:g}" font-size="11.5" font-weight="700" fill="{PALETTE["box"]}" '
            f'text-anchor="middle">{number}</text></g></a>')


def hub(drawing, mode):
    """The left column below the external systems: who gets in, and through which hub."""
    if mode == "external-hub":
        drawing.container(16, 456, 300, 96, "On-premises network", "blue")
        drawing.icon("people", "users", 76, 492, ["Your people"])
        drawing.icon("onprem", "expressroute", 226, 492, ["Site-to-site VPN", "or ExpressRoute"])
        drawing.container(16, 566, 300, HUB_HEIGHT, "Your hub · connectivity subscription", "blue",
                          note="you own it")
        drawing.icon("hub-vpn", "vpn-gateway", 86, 620, ["VPN or ExpressRoute", "gateway"])
        drawing.icon("hub-firewall", "firewall", 236, 620, ["Azure Firewall"])
        drawing.icon("hub-resolver", "dns-resolver", 86, 765, ["@dns-resolver"])
        drawing.icon("hub-dns", "dns-zones", 236, 765, ["@dns-zones", "(central)"])
        drawing.icon("hub-bastion", "bastion", 86, 910, ["@bastion"])
        drawing.icon("hub-vnet", "vnet", 236, 910, ["Hub virtual", "network"])
        drawing.lines(166, 1040, ["One hub can serve several AI Factories.",
                                 "Settings: centralDnsZoneByPolicyInHub = true,",
                                 "access_hub_mode = external"], size=10.5, color="muted")
        drawing.arrow([(166, 552), (166, 566)])
    elif mode == "own-hub":
        drawing.container(16, 456, 300, 96, "People who work in the Factory", "blue")
        drawing.icon("people", "users", 76, 492, ["Your people"])
        drawing.icon("onprem", "vpn-gateway", 226, 492, ["Azure VPN client", "(point-to-site)"])
        drawing.container(16, 566, 300, HUB_HEIGHT, "Own hub · created by ESAF", "purple", note="Dev network")
        drawing.icon("hub-vpn", "vpn-gateway", 86, 620, ["@vpn-gateway"])
        drawing.icon("hub-resolver", "dns-resolver", 236, 620, ["@dns-resolver"])
        drawing.icon("hub-bastion", "bastion", 86, 750, ["@bastion"])
        drawing.icon("hub-vnet", "vnet", 236, 750, ["Hub virtual", "network"])
        drawing.lines(166, 880, ["The Factory needs no other hub.",
                                 "Each Factory pays for its own VPN gateway.",
                                 "Settings: enableAIFactoryHub = true,",
                                 "setup_hub_access = true, vpn_client_cidr"], size=10.5, color="muted")
        drawing.arrow([(166, 552), (166, 566)])
    else:
        drawing.container(16, 456, 300, 96, "People who work in the Factory", "blue")
        drawing.icon("people", "users", 76, 492, ["Your people"])
        drawing.icon("onprem", "browser", 226, 492, ["Allowed IP", "addresses"])
        drawing.container(16, 566, 300, HUB_HEIGHT, "No hub", "blue", dashed=True)
        for y, block in ((650, ["The Factory keeps its network and its", "private DNS zones in the common",
                                "resource group."]),
                         (760, ["Networking is hybrid or public:", "people reach the services over the",
                                "internet, from the IP addresses you allow."]),
                         (870, ["Fastest to create, easiest to delete.", "For private-only access, choose a hub."]),
                         (960, ["Settings: access_hub_mode = integrated,", "setup_hub_access = false,",
                                "network_mode = hybrid or public"])):
            drawing.lines(166, y, block, size=11, color="muted", step=15)


def connect_hub(drawing, mode):
    """The line between the hub and the common virtual network, drawn on top of the Factory boxes."""
    if mode == "standalone":
        drawing.arrow([(316, 504), (346, 504)], dashed=True)
        drawing.text(308, 484, "over the internet", size=10.5, color="muted", anchor="end")
        return
    cx, top = drawing.at["hub-vnet"]
    drawing.arrow([(cx + 18, top + 15), (338, top + 15), (338, 1006), (360, 1006)], dashed=True)
    drawing.text(cx + 22, top + 9, "VNet peering", size=10.5, color="muted")


def render(mode, data=None):
    data = data or load()
    about = MODES[mode]
    d = Drawing()

    # ---- outside Azure: Microsoft 365, Power Platform, knowledge and data
    d.text(332, 40, about["title"], size=26, weight="700")
    d.lines(332, 62, [about["summary"]], size=12.5, color="muted", anchor="start")
    d.add(f'<circle cx="341" cy="80" r="7" fill="{BLUE}"/>')
    d.text(354, 84, "A numbered circle is a code template: select it, or find it in the table below the image. "
                    "A dashed line is a private connection.", size=11, color="muted")
    d.container(1330, 8, 254, 80, "Microsoft 365", "blue")
    d.icon("teams", "teams", 1400, 38, ["Teams"], size=26)
    d.icon("m365", "m365-copilot", 1510, 38, ["Microsoft 365 Copilot"], size=26)

    d.container(16, 96, 300, 130, "Microsoft Power Platform", "blue")
    d.icon("copilot-studio", "copilot-studio", 86, 134, ["Copilot Studio", "agent"])
    d.icon("power-automate", "power-automate", 236, 134, ["Power Automate", "flow"])
    d.arrow([(108, 149), (214, 149)])

    d.container(16, 240, 300, 202, "Knowledge and data outside the Factory", "blue")
    d.icon("sharepoint", "sharepoint", 86, 276, ["SharePoint", "sites and files"])
    d.icon("onelake", "onelake", 86, 362, ["@onelake"])
    d.icon("fabric", "fabric", 236, 276, ["Microsoft Fabric"])
    d.icon("fabric-agent", "fabric-data-agent", 236, 362, ["Fabric data agent", "(Fabric IQ)"])

    hub(d, mode)

    # ---- the AI Factory
    d.container(332, 96, 1252, HEIGHT - 20 - 96,
                "AI Factory · scale set 001 · Dev subscription (Stage and Prod have the same layout)", "purple")
    d.container(346, 132, 1224, 654, "Project resource group · one for each team (project 001, 002, ...)", "pink")

    d.container(360, 186, 490, 454, ["@foundry", "· account and project"], "blue")
    for key, name, column, row, label in (
        ("hosted", "microsoft-foundry", 0, 0, ["Hosted agents"]),
        ("prompt", "microsoft-foundry", 1, 0, ["Prompt agents"]),
        ("chat-agent", "microsoft-foundry", 2, 0, ["@agent-chat"]),
        ("models", "azure-openai", 3, 0, ["Models"]),
        ("foundry-iq", "foundry-iq", 0, 1, ["Foundry IQ", "knowledge base"]),
        ("tools", "mcp", 1, 1, ["Tools:", "MCP servers"]),
        ("agent-service", "cognitive-services", 2, 1, ["@foundry-caphost"]),
        ("evaluations", "evaluations", 3, 1, ["Evaluations"]),
        ("fabric-tool", "fabric-data-agent", 0, 2, ["Fabric data agent", "tool"]),
        ("voice", "speech", 1, 2, ["@agent-chat-voice"]),
        ("content-safety", "content-safety", 2, 2, ["@content-safety"]),
        ("doc-intelligence", "document-intelligence", 3, 2, ["@document-intelligence"]),
        ("bing", "bing", 0, 3, ["@bing"]),
        ("bing-custom", "bing", 1, 3, ["@bing-custom"]),
        ("azure-mcp", "mcp", 2, 3, ["@azure-mcp"]),
        ("foundry-gateway", "api-management", 3, 3, ["@ai-gateway"]),
    ):
        d.icon(key, name, 424 + column * 120, 232 + row * 102, label)

    d.container(864, 186, 240, 174, "Agent service keeps its data here", "blue")
    d.icon("search", "ai-search", 924, 220, ["@ai-search"])
    d.icon("cosmos", "cosmos-db", 1044, 220, ["@cosmos-db"])
    d.icon("storage", "storage", 924, 290, ["Storage"])
    d.icon("keyvault", "key-vault", 1044, 290, ["@key-vault"])

    d.container(864, 372, 240, 268, "Azure Machine Learning and data", "blue")
    d.icon("aml", "machine-learning", 924, 402, ["@azure-ml"])
    d.icon("eventhubs", "event-hubs", 1044, 402, ["@event-hubs"])
    d.icon("adf", "data-factory", 924, 486, ["@data-factory"])
    d.icon("databricks", "databricks", 1044, 486, ["@databricks"])
    d.icon("aks-ml", "aks", 924, 570, ["@aks-for-ml"])
    d.icon("logic-apps", "logic-apps", 1044, 570, ["@logic-apps"])

    d.container(1118, 186, 438, 252, "Applications · full stack", "blue")
    for key, name, column, row, label in (
        ("containerapps", "container-apps", 0, 0, ["@container-apps"]),
        ("functions", "functions", 1, 0, ["@function-app"]),
        ("webapp", "app-service", 2, 0, ["@web-app"]),
        ("bot", "bot-service", 3, 0, ["@bot-service"]),
        ("aks", "aks", 0, 1, ["@aks"]),
        ("sql", "sql-database", 1, 1, ["@sql"]),
        ("postgres", "postgresql", 2, 1, ["@postgresql"]),
        ("redis", "redis", 3, 1, ["@redis-cache"]),
        ("app-gateway", "application-gateway", 0, 2, ["@app-gateway"]),
        ("cosmos-mongodb", "cosmos-db", 1, 2, ["@cosmos-mongodb"]),
        ("elasticsearch", "elasticsearch", 2, 2, ["@elasticsearch"]),
        ("redis-managed", "managed-redis", 3, 2, ["@redis-managed"]),
    ):
        d.icon(key, name, 1178 + column * 108, 220 + row * 70, label)

    d.container(1118, 450, 438, 190, "Project subnets · in the common virtual network", "blue")
    d.icon("pe", "private-endpoint", 1178, 488, ["@private-endpoints"])
    d.icon("agent-subnet", "subnet", 1286, 488, ["Agent subnet"])
    d.icon("aca-subnet", "subnet", 1394, 488, ["Container Apps", "subnet"])
    d.icon("identity", "managed-identity", 1502, 488, ["Managed", "identities"])
    d.lines(1337, 590, ["The services of a project are reached through private endpoints.",
                        "Each service runs with a managed identity of the project."], size=10.5, color="muted")

    d.container(360, 652, 490, 120, "Azure AI services · beside Foundry", "blue")
    d.icon("azure-openai", "azure-openai", 442, 686, ["@azure-openai"])
    d.icon("speech", "speech", 605, 686, ["@speech"])
    d.icon("vision", "vision", 768, 686, ["@vision"])

    d.container(864, 652, 692, 120, "Reach and protect the project", "blue")
    d.icon("project-vm", "virtual-machine", 924, 686, ["@project-vm"])
    d.icon("vm-backup", "recovery-services-vault", 1044, 686, ["@vm-backup"])
    d.icon("defender-resource", "defender", 1178, 686, ["@defender-resource"])
    d.lines(1400, 700, ["The project VM is private: reach it through Bastion or the VPN.",
                        "Azure Backup keeps the admin VM and the project VMs.",
                        "Defender for AI watches each AI resource of the project."], size=10.5, color="muted")

    d.container(346, 800, 1224, 466, "Common resource group · shared by the projects of the scale set", "purple")
    d.container(360, 834, 600, 190, "Common virtual network", "blue")
    d.icon("pp-subnet", "subnet", 424, 874, ["Power Platform", "subnet (delegated)"])
    d.icon("common-subnet", "private-endpoint", 544, 874, ["Common subnet:", "private endpoints"])
    d.icon("scoring-subnet", "subnet", 664, 874, ["Scoring subnet"])
    d.icon("bastion-subnet", "bastion", 784, 874, ["@bastion", "(optional)"])
    d.icon("admin-vm", "virtual-machine", 904, 874, ["@admin-vm", "(optional)"])
    dns = {"external-hub": "Private DNS zones are in your hub. Peering connects this network to it.",
           "own-hub": "Private DNS zones are in this resource group. Peering connects this network to the own hub.",
           "standalone": "Private DNS zones are in this resource group. There is no peering."}[mode]
    d.lines(660, 986, [dns, "A new project gets its own subnets from the address range of this network."],
            size=10.5, color="muted")

    d.container(360, 1038, 600, 214, "Common services", "blue")
    d.icon("datalake", "storage", 424, 1074, ["Data lake", "(ADLS Gen2)"])
    d.icon("common-kv", "key-vault", 544, 1074, ["@key-vault"])
    d.icon("acr", "container-registry", 664, 1074, ["Container", "registry"])
    d.icon("log-analytics", "log-analytics", 784, 1074, ["Log Analytics"])
    if mode == "external-hub":
        d.icon("dashboards", "dashboard", 904, 1074, ["Dashboards"])
    else:
        d.icon("common-dns", "dns-zones", 904, 1074, ["@dns-zones"])
    d.icon("common-adf", "data-factory", 424, 1166, ["@data-factory-common"])
    d.icon("defender", "defender", 544, 1166, ["@defender-subscription"])
    d.lines(784, 1184, ["Defender for Cloud covers the whole subscription,",
                        "with the plans for AI and Key Vault."], size=10.5, color="muted")

    d.container(974, 834, 582, 190, "AI gateway · its own pipeline", "blue")
    d.icon("apim", "api-management", 1050, 874, ["@apim"])
    d.text(1150, 894, "or", size=12, color="muted", anchor="middle")
    d.icon("kong", "kong", 1250, 874, ["@kong"])
    d.icon("factory-mcp", "container-apps", 1450, 874, ["@factory-mcp", "(published on the gateway)"])
    d.lines(1265, 980, ["One endpoint in front of a pool of model deployments, with retries.",
                        "Settings: ENABLE_APIM or ENABLE_KONG, addAIFactoryMCP2APIM.",
                        "The Foundry account can also have its own AI gateway (new SKU): enableAIGatewaySKU."],
            size=10.5, color="muted")

    d.container(974, 1038, 582, 214, "Run and watch the Factory", "blue")
    d.icon("pipelines", "pipelines", 1050, 1074, ["Azure DevOps or", "GitHub Actions"])
    d.icon("monitor", "monitor", 1184, 1074, ["Azure Monitor", "health model"])
    d.icon("appinsights", "application-insights", 1318, 1074, ["@app-insights"])
    d.icon("dashboards2", "dashboard", 1452, 1074, ["@dashboards"])
    d.icon("factory-apps", "factory-apps", 1050, 1166, ["@factory-apps"])
    d.icon("ampls", "private-link", 1184, 1166, ["@ampls"])
    d.icon("appinsights-dashboard", "dashboard", 1318, 1166, ["@app-insights-dashboard"])

    # ---- how it connects
    d.arrow([(1508, 88), (1508, 216)])
    d.text(1500, 114, "an agent published to Teams and Microsoft 365 Copilot", size=10.5, color="muted",
           anchor="end")
    d.arrow([(1492, 216), (1492, 172), (424, 172), (424, 228)])
    d.text(1000, 167, "Bot Service passes each message to the agent", size=10.5, color="muted", anchor="middle")
    d.arrow([(316, 160), (324, 160), (324, 889), (405, 889)], dashed=True)
    d.text(374, 882, "private", size=10.5, color="muted", anchor="middle")
    d.arrow([(316, 349), (405, 349)], dashed=True)
    d.arrow([(316, 400), (338, 400), (338, 451), (405, 451)], dashed=True)
    d.arrow([(850, 236), (903, 236)])
    d.arrow([(850, 421), (903, 421)])
    d.arrow([(850, 553), (857, 553), (857, 793), (1050, 793), (1050, 870)], dashed=True)
    d.text(1060, 819, "model and MCP calls", size=10.5, color="muted")
    connect_hub(d, mode)

    # ---- one blue circle for each numbered code template
    stack = {}
    for template in sorted((item for item in data["templates"] if "number" in item), key=lambda item: item["number"]):
        key = PLACES[template["place"]]
        cx, top = d.at[key]
        index = stack[key] = stack.get(key, -1) + 1
        d.number(template["number"], template, cx + 24 + index * 23, top + 2)

    defs = ('<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 Z" fill="{PALETTE["line"]}"/></marker>')
    defs += "".join(symbol(name) for name in d.icons)
    description = (f'{about["summary"]} The image also shows Microsoft 365 with Teams and Copilot, which reach a '
                   "Foundry agent through Bot Service; Microsoft Power Platform with Copilot Studio and Power "
                   "Automate, which reach the common virtual network; SharePoint and Microsoft Fabric as knowledge "
                   "and data for Foundry IQ and the Fabric data agent tool; and API Management or Kong as the AI "
                   "gateway. Every Azure resource of the resource library is on the image, in the project "
                   "resource group or in the common resource group. Numbered blue circles mark the code "
                   "template for each part.")
    return "\n".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" height="{HEIGHT}" '
        f'role="img" aria-labelledby="title desc" font-family="{FONT}">',
        f'<title id="title">{escape(about["title"])}</title>',
        f'<desc id="desc">{escape(description)}</desc>',
        f"<defs>{defs}</defs>",
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{PALETTE["canvas"]}"/>',
        *d.parts,
        "</svg>", ""])


def png(mode):
    """Render the checked-in SVG to a PNG still with headless Chromium."""
    from playwright.sync_api import sync_playwright

    source = OUTPUT / f"esaf-architecture-{mode}.svg"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1)
        page.goto(source.resolve().as_uri())
        page.screenshot(path=str(source.with_suffix(".png")))
        browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail when a checked-in SVG is stale")
    parser.add_argument("--png", action="store_true", help="also write the PNG stills")
    arguments = parser.parse_args()
    data = load()
    stale = []
    for mode in MODES:
        path = OUTPUT / f"esaf-architecture-{mode}.svg"
        text = render(mode, data)
        if arguments.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                stale.append(path.name)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        if arguments.png:
            png(mode)
        print("wrote", path.relative_to(SITE))
    if stale:
        sys.exit("Stale architecture images, run generate_architecture.py: " + ", ".join(stale))


if __name__ == "__main__":
    main()
