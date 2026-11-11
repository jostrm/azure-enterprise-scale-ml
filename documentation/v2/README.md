# Enterprise Scale Azure Factory (ESAF) documentation

Go from an empty Azure subscription to a governed AI Factory, then build agents and ML models in it.

<table>
<tr>
<td width="50%" valign="top">
<a href="quickstarts/README.md"><img src="images/concepts/door-setup.svg" width="96" alt="Illustration of a purple factory building with a green gear, for the platform team."></a><br>
<a href="quickstarts/README.md"><b>Setup docs - platform team: How to set up the Factory</b></a><br>
Install the tools, create the Factory, add projects and switch on Agent Chat.
</td>
<td width="50%" valign="top">
<a href="usage/README.md"><img src="images/concepts/door-usage.svg" width="96" alt="Illustration of a purple project box with a chat bubble and a chart, for project teams."></a><br>
<a href="usage/README.md"><b>Usage docs - project team: How to build agents, apps and ML</b></a><br>
Build on a project your platform team already set up.
</td>
</tr>
</table>

<img src="images/concepts/factory-line.svg" width="760" alt="Illustration of a purple factory whose conveyor belt carries green project crates to a waiting team.">

*AI-generated illustration.*

An **AI Factory** is a production line for AI projects. The platform team builds the line once. Each project
team then gets the same secure project: private networking, identities, Microsoft Foundry, Azure AI Search and
Azure Machine Learning.

## Learn by watching

The **ESAF Tutorial Guide** is a Windows app (installed as **ESAF Tutorials**). It types each command for you, checks every step and plays a
narrated video for each scenario. It has one tutorial for the CLI, one for the Python SDK and one for REST,
and each runs the six scenarios in order.

| Video in the ESAF Tutorial Guide | Tool | Hub mode | Networking | Length |
|---|---|---|---|---|
| Scenarios 1-4 | Python SDK | External hub | Private | 9 min |
| Scenarios 1-3 | Python SDK | Standalone, no hub | Public | 7 min |
| Scenarios 1-3 | Config Wizard app | Standalone, no hub | Public | 6 min |
| Scenarios 1-3 | Python SDK | Own hub | Private | 8 min |

[Download the ESAF Tutorial Guide](../../environment_setup/install_tutorial_guide/README.md), then open **Resources** > **Scenario videos**. It's a private preview:
ask [Joakim Åström on LinkedIn](https://www.linkedin.com/in/joakimastrom/) for a preview code. It runs on
Windows. On Linux and macOS, follow the [Setup docs](quickstarts/README.md) with the CLI (bash) tab.

## Understand ESAF

| Page | What it explains |
|---|---|
| [The six scenarios](reference/scenarios.md) | Lists the one call per scenario, for every tool. |
| [Hub and network modes](concepts/hub-and-network-modes.md) | Compares the three hub modes and the three networking modes. |
| [Folder structure](reference/folder-structure.md) | Shows the `azurefactory` folder that holds your factories. |
| [Settings](reference/settings.md) | Explains the connection settings and the naming limits. |
| [Onion architecture](10-19/10-factory-onion-architecture-v2.md) | Shows the five layers from your tool down to Azure Resource Manager. |
| [Architecture diagrams](10-19/11-architecture-diagrams.md) | Shows the Azure services in the common part and in a project. |
| [Factory overview](10-19/15-aifactory-overview.md) | Lists the services and their naming convention. |

## Go deeper by tool

| Guide | What you do |
|---|---|
| [18. Get started with Factory tools](10-19/18-cli-and-api-and-usage.md) | Try the CLI, the Python SDK or REST against a local demo service. |
| [19. Add and update an AI factory](10-19/19-cli-and-api-and-usage.md) | Review each change yourself before the API applies it. |
| [20. Remove, observe and recover](10-19/20-cli-and-api-and-usage.md) | Delete with a review, follow jobs and recover from a stopped run. |
| [21. Agent Factory chat and live voice](10-19/21-agent-factory-chat.md) | Operate, secure and troubleshoot Agent Chat. |
| [22. Lifecycle Azure Function](10-19/22-lifecycle-azure-function.md) | Call the six scenarios from a hosted function. |
| [Tutorial: configure, review and verify](20-29/28-tutorial-walkthrough.md) | Walk through the app and the read-only API. |
| [Tutorial: FinOps monitoring](20-29/tutorial-finops.md) | Turn usage and cost evidence into FinOps reports. |
| [ITSM integration](20-29/29-ITSM-integrated.md) | Order projects from ServiceNow, Jira or your own portal. |

**Next:** [Setup docs - platform team](quickstarts/README.md)

---

Using v1.24? See the [release/v1.24 docs](https://github.com/jostrm/azure-enterprise-scale-ml/tree/release/v1.24/documentation).
