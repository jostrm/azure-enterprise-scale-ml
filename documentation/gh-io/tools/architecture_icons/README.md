# Icons of the architecture images

`generate_architecture.py` embeds these icons in the three ESAF architecture images. An SVG file is an official
Microsoft icon from Microsoft's own icon sets, copied unchanged under a short name, unless it is listed under
"Icons from another place".

| Icons | Official set | Downloaded |
|---|---|---|
| The Azure services, among them `managed-redis.svg`, `logic-apps.svg`, `application-gateway.svg`, `defender.svg`, `vision.svg`, `recovery-services-vault.svg` and `private-link.svg` | [Azure architecture icons](https://learn.microsoft.com/azure/architecture/icons/) | 2026 |
| `copilot-studio.svg`, `power-automate.svg` | [Microsoft Power Platform icons](https://learn.microsoft.com/power-platform/guidance/icons) | 2026-11-12 |
| `fabric.svg`, `onelake.svg`, `fabric-data-agent.svg`, `m365-copilot.svg` (the Copilot icon of that set) | [Microsoft Fabric icons](https://learn.microsoft.com/fabric/fundamentals/icons), version 6.1.0 | 2026-11-12 |
| `teams.svg` (the Chat symbol in Teams purple) | [Microsoft 365 architecture icons](https://learn.microsoft.com/microsoft-365/solutions/architecture-icons-templates) | 2026-11-12 |

Microsoft permits the use of these icons in architecture diagrams, training materials and documentation. Keep
each icon as it is: don't crop, flip, rotate or recolor it, and put the product name close to it.

## Icons from another place

Four icons are not in Microsoft's icon sets. Joakim gave the link or the picture for each. The generator puts
a PNG file into the image as the file has it:

| Icon | Product | From | Added |
|---|---|---|---|
| `bing.svg` | Grounding with Bing Search and with Bing Custom Search | [Bing Fluent Logo.svg](https://commons.wikimedia.org/wiki/File:Bing_Fluent_Logo.svg) on Wikimedia Commons, public domain there, a Microsoft trademark. Unchanged. | 2026-11-13 |
| `elasticsearch.svg` | Elasticsearch | [Elasticsearch logo.svg](https://commons.wikimedia.org/wiki/File:Elasticsearch_logo.svg) on Wikimedia Commons, Apache License 2.0, a trademark of Elastic. The six paths of the mark, unchanged, without the word "elasticsearch" beside it. | 2026-11-13 |
| `microsoft-foundry.png` | Microsoft Foundry: the hosted, prompt and chat agents | [selfhst/icons](https://github.com/selfhst/icons) on GitHub (`png/microsoft-foundry.png`), the link Joakim gave | 2026-11-13 |
| `foundry-iq.png` | Foundry IQ knowledge base | A picture of the Foundry IQ mark that Joakim gave. The white around the mark was made transparent, the empty margin trimmed and the picture scaled to 144 x 144. The mark itself is unchanged. | 2026-11-13 |

## Lettered tiles

Four products have no icon and are drawn as a lettered dark tile:

| Tile | Product | Why |
|---|---|---|
| `sharepoint.svg` | SharePoint | The Microsoft 365 set has symbols in the SharePoint color, but no SharePoint icon. |
| `kong.svg` | Kong | Not a Microsoft product. |
| `pipelines.svg` | Azure DevOps or GitHub Actions | One tile stands for either of the two. |
| `factory-apps.svg` | The Factory apps, such as the Configuration Wizard | ESAF's own apps: the tile has the purple border of the AI Factory. |

To replace a tile, add the official SVG here under that name, remove the name from `TILES` in the generator
and run:

```bash
python documentation/gh-io/tools/generate_architecture.py --png
```
