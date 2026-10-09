# AI Factory concepts

An AI Factory separates reusable platform services from the projects that use
them. You choose what to configure, where to deploy it and who may operate it.

## Factory, scale set and project

| Term | Meaning |
| --- | --- |
| **Factory** | The registered identity and settings for a governed AI platform, including its region and naming. |
| **Scale set** | An environment/subscription/networking grouping inside a factory. **Not Azure Virtual Machine Scale Sets (VMSS).** |
| **Project** | A logical workload/team with its own number, settings and explicitly selected deployment locations. |
| **Placement** | The scale set used by that project in Dev, Stage or Prod. Adding a placement saves a target; it does not deploy it. |
| **Common services** | Shared resources such as networking or storage that projects may depend on. |

The registered format uses stable UUIDs for these objects. Human-readable names
and three-digit numbers help navigation but are not interchangeable with UUIDs.
See [scale and environment choices](enterprise-scale.md).

## Choose the layer you need

| Goal | Guidance |
| --- | --- |
| Configure or operate the factory | [Factory tools](../factory-tools/18-cli-and-api-and-usage.md) |
| Understand planning and dependency checks | [Platform automation](intelligence.md) |
| Build infrastructure | [IaC templates](templates/iac.md) |
| Prepare and move data | [DataOps](templates/dataops.md) |
| Train and evaluate models | [MLOps](templates/mlops.md) |
| Build agents and RAG applications | [GenAIOps](templates/genaiops.md) |
| Follow usage, cost and health | [Monitor and operate](../intelligence.md) |

## Three rules to keep in mind

1. **Configuration is not deployment.** Save reviewed settings, then separately
   approve the operation that applies them.
2. **A flag is not a cleanup plan.** Removing settings and deleting resources are
   different tasks with different safeguards.
3. **Shared source is not live state.** A template, graph or screenshot does not
   prove a resource was deployed successfully in your environment.

Both GitHub Actions and Azure DevOps are supported provider choices, with
different authentication and execution setup. Their availability does not imply
that every operation behaves identically through every version.

<details markdown="1">
<summary>More info</summary>

The default registered layout is `azurefactory/register.json` with
API-written project settings. Older `aifactory` JSON/YAML/`.env` workflows remain
separate routes. A source-version change does not migrate one layout into another.

The CLI and Python SDK use the shared Factory API for supported operations.
Advanced enrollment is a separate local CLI implementation. A desktop host,
Agent Chat or MCP adapter does not create a second independent deployment engine
or bypass approval.

Conceptual labels such as foundation, automation and guided experience describe
levels of assistance, not Azure product SKUs.

</details>
