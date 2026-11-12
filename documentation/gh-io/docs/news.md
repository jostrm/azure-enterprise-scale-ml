# News and releases

This site describes the `main` branch, where development happens. A release branch is a stable version that
you choose when you create a Factory.

## New on main

| Area | What is new | Where to read |
| --- | --- | --- |
| Architecture images | One image for each hub mode. It shows how ESAF connects to Microsoft 365, Power Platform, SharePoint, Fabric and the AI gateway, with a number for each code template. | [Architecture](architectures.md) |
| Code templates library | Every code template of the Agent Factory, the Model Factory and the other folders, with a search box and filters. | [Code templates library](code-templates/index.md) |
| Azure resource library | Every Azure service a project can switch on, by category, with its setting. | [Azure resource library](resources/index.md) |
| Setup and usage docs | Five quickstarts for the platform team and the first steps for a project team. Each scenario is one call. | [Setup docs](setup/index.md), [Usage docs](usage/index.md) |
| Every variable explained | All variables of `variables.json`, with the default value and what each one does. | [Every variable in variables.json](parameters/variables.md) |
| CLI, Python SDK and REST tutorials | One tab for each tool, with examples you can run, for adding, updating and removing. | [Get started](factory-tools/18-cli-and-api-and-usage.md) |
| MCP and AI gateway | Optional steps of the project 001 Dev pipeline: the Factory MCP server, and its publication on API Management. | [Settings](parameters/advanced.md#mcp-and-ai-gateway-parameters) |
| Agent Chat live voice | Talk to ESAF Agent Chat with Azure Voice Live. Switch it on with `enableAIFactoryAgentLiveVoice` next to `enableFactoryChatAgent`. | [Agent Chat and live voice](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/documentation/v2/10-19/21-agent-factory-chat.md) |
| AKS for Azure Machine Learning | Attaching an existing AKS cluster passes the load-balancer subnet of that cluster. | [Bicep](iac/bicep.md) |
| Usage, cost and monitoring | Workbooks in the Azure portal, sample and saved reports, and live cost reads. | [Monitor and operate](intelligence.md) |

!!! note "A change on main reaches you when you update"
    New code on `main` changes nothing in a Factory that exists. You get it when you update the tools you
    installed and run the pipelines of your Factory again with that version.

## v1.25

The [v1.25 release notes](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/RELEASE_125.md) describe
the `release/v1.25` branch as of 23 September 2026: the Factory API with its CLI and SDK, the Agent Factory,
the ML Model Factory, versioned data, monitoring and the gateway policies.

The [roadmap](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/ROADMAP_MAIN.md) lists what is
planned after that.

## Not available yet

| Capability | Status |
| --- | --- |
| Promotion from Dev to Stage to Prod as one workflow | Not available. You deploy each environment with its own settings. |
| Keeping selected resources when a whole resource group is deleted | Not available. A whole-group delete removes everything in the group. |
| A health model command in the CLI and the app | Not available. Deploy the health model with its own pipeline. |
| Sending reports by email | Not available. |

## Earlier releases

- [v1.24 and v1.24.1](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/RELEASE_124.md)
- [v1.23](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/RELEASE_123.md)
- [v1.20](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/RELEASE_120.md)

<details markdown="1">
<summary>More info</summary>

Version `125` means the `release/v1.25` branch. The launcher scripts of a repository that was set up with
v1.24 still create with version `124` unless you name another, and an update keeps the version that was
saved.

Use the tools, the templates and the workload code of the same version together. Each run records the commit
it used. Before you upgrade, read the release notes for settings that were renamed or removed.

</details>
