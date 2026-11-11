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
| [scale-set-floor.svg](scale-set-floor.svg) | Quickstart 03 | A building where each floor holds project rooms, and one floor is being added | Illustration of a factory building where each floor is a scale set that holds project rooms. |
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

## Still to capture

Nothing on the pages points at these files yet, so no page shows a broken image. Add each file, then add it to
the page named here.

| File to add | Page | What it shows | Alt text |
|---|---|---|---|
| `images/videos/02-create-factory.png` | Quickstart 02 | A frame from the scenario 1 video where the run has finished, with a play overlay and the duration | Screenshot of a finished Init factory run with the new resource groups listed. |
| `images/videos/03-add-project.png` | Quickstart 03 | A frame where project 002 appears after the run | Screenshot of project 002 added to the Dev scale set after the run. |
| `images/videos/05-clean-up.png` | Quickstart 05 | A frame where the delete run has completed | Screenshot of the delete factory run with all steps completed. |
| `images/usage/project-dashboard.png` | View your project dashboards | The Azure portal project dashboard: resource group, Cost analysis and the daily cost charts | Screenshot of the project dashboard with the resource group, cost analysis and cost charts. |
| `images/usage/my-project-workbook.png` | View your project dashboards | The My Project - Usage and Cost workbook, Model tokens view | Screenshot of the Usage and Cost workbook that shows token usage for each model. |
| `images/usage/app-monitoring-my-project.png` | View your project dashboards | The ESAF app, Monitoring, My Project | Screenshot of the My Project view in the ESAF app with usage beside the cost tab. |
| `images/quickstarts/app-quick-setup.png` | Quickstart 01 | The app's Quick setup page with Start API host | Screenshot of the Quick setup page in the app with Start API host selected. |
| `images/quickstarts/app-agent-chat-switches.png` | Quickstart 04 | The AI Factory Agent chat & live voice section | Screenshot of the Agent chat and live voice section with both switches turned on. |

Video thumbnails link to the lab guide, never to a video host: the videos open from inside the ESAF
Tutorials app.

### Check these app labels against the current app

The quickstarts name these labels from earlier docs. Check each one when you capture the screenshots:
**Quick setup** > **Start API host**, **Start Guide**, **Simple Mode**, **Full bootstrap**,
**Configure only—do not deploy**, **Projects**, **AI Factory Agent chat & live voice**, **Monitoring** >
**My Project**.
