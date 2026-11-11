# Icons of the architecture images

`generate_architecture.py` embeds these icons in the three ESAF architecture images.

They are the official Azure service icons from the
[Azure architecture icons](https://learn.microsoft.com/azure/architecture/icons/) set, copied unchanged under
short names. Microsoft permits their use in architecture diagrams, training materials and documentation.
Keep each icon as it is: don't crop, flip, rotate or recolor it.

A product that has no file here (Teams, Microsoft 365 Copilot, Copilot Studio, Power Automate, SharePoint,
Fabric, Kong) is drawn as a lettered dark tile. To replace a tile, add the product's official SVG icon here
with the name the generator uses (`teams.svg`, `m365-copilot.svg`, `copilot-studio.svg`, `power-automate.svg`,
`sharepoint.svg`, `fabric.svg`, `fabric-data-agent.svg`, `kong.svg`, `pipelines.svg`), then run:

```bash
python documentation/gh-io/tools/generate_architecture.py --png
```
