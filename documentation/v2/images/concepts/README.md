# Visual style guide and image briefs

This page is for people who add or replace images in the ESAF docs. It isn't part of the reading path.

## Rules for every image

- **Alt text:** 40 to 150 characters, ending with a period. Start with the type: "Screenshot of…",
  "Diagram that shows…" or "Illustration of…".
- **Size:** 300 KB or less per file, and 3 MB or less for everything under `documentation/v2/images/`.
- **No video files** in the repository. Videos open from inside the ESAF Tutorials lab guide.
- **Animated images** go in a `<picture>` with a PNG still for `prefers-reduced-motion`.
- **Screenshots:** only when a UI element is hard to find. PNG, 750 to 1000 px wide, light theme, no cursor,
  no IDs or secrets.

## Colors carry meaning

| Color | Meaning | Hex |
|---|---|---|
| Purple | The AI Factory itself | `#7c3aed` |
| Green | Good: a working result | `#22c55e` |
| Blue | Neutral | `#3b82f6` |
| Orange | Caution | `#f59e0b` |
| Pink | Weak | `#ec4899` |
| Red | Bad, always | `#ef4444` |

## Concept illustrations

One shared style: flat shapes, soft rounded corners, an off-white background (`#faf8f5`), no text in the image
and no logos or brand marks. Caption each one with "*AI-generated illustration.*" on the page.

| File | Used on | Scene | Alt text |
|---|---|---|---|
| [door-setup.svg](door-setup.svg) | Docs hub, page 24 | A purple factory building with a green gear | Illustration of a purple factory building with a green gear, for the platform team. |
| [door-usage.svg](door-usage.svg) | Docs hub, page 24 | A purple project box with a chat bubble and a chart | Illustration of a purple project box with a chat bubble and a chart, for project teams. |
| [factory-line.svg](factory-line.svg) | Docs hub | A factory whose conveyor carries project crates to a team | Illustration of a purple factory whose conveyor belt carries green project crates to a waiting team. |
| [hub-roads.svg](hub-roads.svg) | Hub and network modes | Three roads to one city: a shared highway, a direct lane and an own bridge | Illustration of three different roads that all lead to the same purple city. |
| [scale-set-floor.svg](scale-set-floor.svg) | Add a scale set | A building where each floor holds project rooms, and one floor is being added | Illustration of a factory building where each floor is a scale set that holds project rooms. |
| [project-app-soon.svg](project-app-soon.svg) | Usage hub | A desktop window with a dashed outline and a ribbon | Illustration of a desktop app window drawn with a dashed outline and a blue ribbon. |

These six are hand-written SVG. To replace one with a raster illustration, keep the file name, the scene and
the alt text, and stay inside the size limit.

## Reused assets

| Asset | Source | Used on |
|---|---|---|
| Onion V2 (GIF with PNG still) | `documentation/v2/10-19/images/10-factory-onion-architecture-v2.*` | Setup hub, quickstart 01 |
| Hub topology stills and animations | `documentation/gh-io/docs/assets/animations/factory-topology-*` | Hub and network modes |
| Agent Chat voice states | `documentation/v2/10-19/images/21-agent-chat-voice-*.png` | Quickstart 04 |
| Template thumbnails (GIF) | `usecase_code/*/images/*-thumb.gif`, stills in `documentation/v2/images/usage/` | Usage hub |

## Video thumbnails

One frame of the scenario video, softened so that terminal text can't be read, with a play overlay and the
length. Each one is 960 px wide and links to the ESAF Tutorials download, never to a video host: the videos open
from inside the app.

| File | Used on | Frame |
|---|---|---|
| [02-create-factory.png](../videos/02-create-factory.png) | Quickstart 02 | The checks of the new Factory have passed. |
| [add-scale-set.png](../videos/add-scale-set.png) | Add a scale set | The checks of scale set 002 are passing. |
| [03-add-project.png](../videos/03-add-project.png) | Quickstart 03 | The checks of project 002 have passed. |
| [05-clean-up.png](../videos/05-clean-up.png) | Quickstart 05 | The delete project run has succeeded. |

## Still to capture

Nothing on the pages points at these files yet, so no page shows a broken image. Add each file, then add it to
the page named here.

| File to add | Page | What it shows | Alt text |
|---|---|---|---|
| `images/usage/project-dashboard.png` | View your project dashboards | The Azure portal project dashboard: resource group, Cost analysis and the daily cost charts | Screenshot of the project dashboard with the resource group, cost analysis and cost charts. |
| `images/usage/my-project-workbook.png` | View your project dashboards | The My Project - Usage and Cost workbook, Model tokens view | Screenshot of the Usage and Cost workbook that shows token usage for each model. |
| `images/usage/app-monitoring-my-project.png` | View your project dashboards | Enterprise Scale AI Factory, Monitoring, My Project | Screenshot of the My Project view in the ESAF app with usage beside the cost tab. |
| `images/quickstarts/app-quick-setup.png` | Quickstart 01 | AIFactory Config Wizard, the Quick setup menu with Start API host | Screenshot of the Quick setup menu in the Config Wizard with Start API host selected. |
| `images/quickstarts/app-scenarios.png` | Quickstart 02 | Enterprise Scale AI Factory, Quick setup & tear down, with the six scenario buttons | Screenshot of the Quick setup and tear down page with one button for each scenario. |

## App labels on the pages

Two desktop apps appear in the quickstarts. Their labels were read from the app source on 2026-11-11. Check
them again when you capture a screenshot.

| App | Where the pages use it | Labels |
|---|---|---|
| AIFactory Config Wizard (`aifactory-config.exe`; Windows, Linux, macOS) | Quickstart 01, to start the Factory API | **Quick setup** > **Start API host**; dialogs **API Host Authentication** and **API Host Started** |
| Enterprise Scale AI Factory (Windows 11) | Every App tab | **Start Guide**, **Use Simple Mode**, **Use Full bootstrap**, **Save local configuration**; menu **Configuration wizard** > **Quick setup & tear down**; **1. Init AI Factory** to **6. Delete AI Factory**; **Run selected scenario**; **Deletion phrase**; **Monitoring** > **My Project** |
| ESAF Tutorials (Windows) | The "Run it guided" tips | Tutorials **ESAF CLI**, **ESAF Python SDK** and **ESAF REST - scenarios 1-6**; tracks **Scenarios 1–3**, **Scenarios 4–6**; **Resources** > **Scenario videos** |
