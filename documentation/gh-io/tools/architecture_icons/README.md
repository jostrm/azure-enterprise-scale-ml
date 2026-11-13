# Icons of the architecture images

`generate_architecture.py` embeds these icons in the three ESAF architecture images. Every SVG file is an
official Microsoft icon from Microsoft's own icon sets, copied unchanged under a short name.

| Icons | Official set | Downloaded |
|---|---|---|
| The Azure services, among them `managed-redis.svg`, `logic-apps.svg`, `application-gateway.svg`, `defender.svg`, `vision.svg`, `recovery-services-vault.svg` and `private-link.svg` | [Azure architecture icons](https://learn.microsoft.com/azure/architecture/icons/) | 2026 |
| `copilot-studio.svg`, `power-automate.svg` | [Microsoft Power Platform icons](https://learn.microsoft.com/power-platform/guidance/icons) | 2026-11-12 |
| `fabric.svg`, `onelake.svg`, `fabric-data-agent.svg`, `m365-copilot.svg` (the Copilot icon of that set) | [Microsoft Fabric icons](https://learn.microsoft.com/fabric/fundamentals/icons), version 6.1.0 | 2026-11-12 |
| `teams.svg` (the Chat symbol in Teams purple) | [Microsoft 365 architecture icons](https://learn.microsoft.com/microsoft-365/solutions/architecture-icons-templates) | 2026-11-12 |

Microsoft permits the use of these icons in architecture diagrams, training materials and documentation. Keep
each icon as it is: don't crop, flip, rotate or recolor it, and put the product name close to it.

## Icons from another place

One icon is not in Microsoft's icon sets. It is a PNG file, and the generator puts the picture into the image
unchanged:

| Icon | Product | From | Downloaded |
|---|---|---|---|
| `microsoft-foundry.png` | Microsoft Foundry: the hosted, prompt and chat agents | [selfhst/icons](https://github.com/selfhst/icons) on GitHub (`png/microsoft-foundry.png`), the link Joakim gave | 2026-11-13 |

`foundry-iq.svg` is still the icon of the Azure set. Joakim has a newer Foundry IQ icon: add it here as
`foundry-iq.png` (or replace the SVG), and add a row to this table.

## Lettered tiles

Six products have no official icon in those sets and are drawn as a lettered dark tile:

| Tile | Product | Why |
|---|---|---|
| `sharepoint.svg` | SharePoint | The Microsoft 365 set has symbols in the SharePoint color, but no SharePoint icon. |
| `kong.svg` | Kong | Not a Microsoft product. |
| `pipelines.svg` | Azure DevOps or GitHub Actions | One tile stands for either of the two. |
| `bing.svg` | Grounding with Bing Search and with Bing Custom Search | The Azure set has no Bing icon. |
| `elasticsearch.svg` | Elasticsearch | Not a Microsoft product. |
| `factory-apps.svg` | The Factory apps, such as the Configuration Wizard | ESAF's own apps: the tile has the purple border of the AI Factory. |

To replace a tile, add the official SVG here under that name, remove the name from `TILES` in the generator
and run:

```bash
python documentation/gh-io/tools/generate_architecture.py --png
```
