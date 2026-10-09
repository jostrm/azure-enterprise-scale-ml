# News and releases

**`main` is the shared development branch. Release branches are stable adoption
points.** This site describes published `main`, with limits called out where a
feature needs a particular API or runtime version.

## Recent published development

| Area | What is available | Where to read |
| --- | --- | --- |
| CLI, Python SDK and REST tutorials | One whole-page tool selector, real Python examples and matching add/update/remove walkthroughs. | [Get started](factory-tools/18-cli-and-api-and-usage.md) |
| Reviewed client shortcuts | Named configuration, settings, project/scale-set deletion preparation and local draft-removal helpers. Confirmation remains separate. | [Add and update](factory-tools/19-cli-and-api-and-usage.md), [remove and recover](factory-tools/20-cli-and-api-and-usage.md) |
| MCP and AI Gateway integration | Opt-in project001 Dev component pipeline steps, with image, identity and network prerequisites. This is not a universal APIM-versus-Kong switch. | [Parameters](parameters/advanced.md#mcp-and-ai-gateway-parameters) |
| Factory Agent Chat live voice | Optional Azure Voice Live speech for the chat: a pulsing voice orb, the same governed answers, `enableAIFactoryAgentLiveVoice` next to `enableFactoryChatAgent`. Opt-in, project001 Dev, off by default. | [Chapter 21](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/documentation/v2/10-19/21-agent-factory-chat.md) |
| AKS attached to Azure ML | The published template supplies the existing cluster's load-balancer subnet. | [IaC](iac/bicep.md) |
| Usage, cost and monitoring | Native workbooks, sample/saved report interfaces and explicit Azure billing reads; missing data is not zero cost. | [Monitor and operate](intelligence.md) |

!!! note "Source, installation and release are different"
    A push to `main` makes source available. It does not upgrade an installed
    desktop/API, change a deployment's selected version, or provision Azure.
    Use the current host's capabilities and review before execution.

## v1.25 release notes

The [v1.25 notes](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/RELEASE_125.md)
review the **23 September 2026** source snapshot on `release/v1.25`.
They cover registered configuration/bootstrap, CLI/SDK/API examples, Agent
Factory, ML Model Factory, versioned data, monitoring and gateway policies.
The snapshot is not a new GA announcement.

Later development on `main` is not automatically part of that snapshot.
Read the [roadmap](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/ROADMAP_MAIN.md)
as a dated assessment, not a promise that every planned feature is released.

## Still limited or in progress

| Capability | Current boundary |
| --- | --- |
| Captured Dev-to-Stage-to-Prod promotion | Not a completed executable workflow. Registering a target and deploying current settings is different. |
| Full bootstrap and deletion | Conditional on compatible source, identity, networking, ownership and retention checks. Unsupported combinations remain blocked. |
| Keeping selected resources inside groups chosen for whole-group deletion | Not supported by that execution path. Do not remove the safeguard. |
| New nine-persona access policy and shared dual-graph enhancements | Local development/addendum material must not be read as proof of inclusion in a published release or installed host. |
| Health-model integration everywhere | Optional component tooling is separate; do not assume a complete Factory CLI/desktop/API health-model workflow. |
| General report-email delivery | A report or an alert is not proof that report attachments were emailed. |

## Earlier releases

- [v1.24 and v1.24.1](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/RELEASE_124.md)
- [v1.23](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/RELEASE_123.md)
- [v1.20](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/RELEASE_120.md)

<details markdown="1">
<summary>More info</summary>

Recent source references include `413c48d0` (native tool tutorials), `0da0d85b`
and `2ae10aa9` (reviewed wrappers and environment-order handling), `cf8437af`
(MCP/AI Gateway pipeline integration), and `940b1b48` (AML/AKS subnet binding).
These identify source changes, not successful customer deployments.

The original v1.25 note identifies snapshot
`1bd9020e009036427763a0f66b2b2449ca38f288`. The supported version selector maps
`125` to `release/v1.25`; similarly named branches are not automatically
equivalent. Some legacy creation defaults still select 124 and update flows can
inherit the saved version. Development's use of `main` does not silently change
those deployment defaults.

Choose compatible launcher, helpers, provider templates, CLI/API and workload
versions together. Each approved run records the exact source it will use even
while `main` continues to advance. Review removed or renamed parameters and
service/region prerequisites before an upgrade.

</details>
