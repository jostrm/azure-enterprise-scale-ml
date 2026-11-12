# Icons of the architecture images

`generate_architecture.py` embeds these icons in the three ESAF architecture images. Every file is an official
Microsoft icon, copied unchanged under a short name.

| Icons | Official set | Downloaded |
|---|---|---|
| The Azure services | [Azure architecture icons](https://learn.microsoft.com/azure/architecture/icons/) | 2026 |
| `copilot-studio.svg`, `power-automate.svg` | [Microsoft Power Platform icons](https://learn.microsoft.com/power-platform/guidance/icons) | 2026-11-12 |
| `fabric.svg`, `onelake.svg`, `fabric-data-agent.svg`, `m365-copilot.svg` (the Copilot icon of that set) | [Microsoft Fabric icons](https://learn.microsoft.com/fabric/fundamentals/icons), version 6.1.0 | 2026-11-12 |
| `teams.svg` (the Chat symbol in Teams purple) | [Microsoft 365 architecture icons](https://learn.microsoft.com/microsoft-365/solutions/architecture-icons-templates) | 2026-11-12 |

Microsoft permits the use of these icons in architecture diagrams, training materials and documentation. Keep
each icon as it is: don't crop, flip, rotate or recolor it, and put the product name close to it.

## Lettered tiles

Three products have no official icon in those sets and are drawn as a lettered dark tile:

| Tile | Product | Why |
|---|---|---|
| `sharepoint.svg` | SharePoint | The Microsoft 365 set has symbols in the SharePoint color, but no SharePoint icon. |
| `kong.svg` | Kong | Not a Microsoft product. |
| `pipelines.svg` | Azure DevOps or GitHub Actions | One tile stands for either of the two. |

To replace a tile, add the official SVG here under that name, remove the name from `TILES` in the generator
and run:

```bash
python documentation/gh-io/tools/generate_architecture.py --png
```
