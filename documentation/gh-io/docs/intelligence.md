# Monitor and operate

Choose the question you want to answer.

| Your question | Use | Good to know |
| --- | --- | --- |
| Is the Factory API running? | `azurefactory health` | It checks the API process. For the health of Azure resources, use the health model below. |
| What exists in my Factory? | The catalog: factories, scale sets and projects | It shows what the API has saved and deployed. |
| Did this deployment finish? | The status and the logs of the job that the call returned | A job ends as succeeded or failed. Follow it until then. |
| How much did we use, and what did it cost? | The usage workbooks and the cost reports | Azure reports cost with a delay, so today's cost is incomplete. |
| Are the services of a project healthy together? | The optional Azure Monitor health model | It is a preview service that you set up for each project. |

[Remove and recover](factory-tools/20-cli-and-api-and-usage.md) has the commands for job status, logs,
watching a GitHub workflow, saved reports and the cost of a resource group. Project teams start at
[Project dashboards](usage/dashboards.md).

## Metrics, reports and dashboards

- **Sample reports** show demonstration data, so that you can see a report before you have usage of your own.
- **Saved reports** show results that were collected earlier.
- **Live reads** ask Azure now. Your identity needs read access to the subscription or the resource group.
- **Dashboards** have their own refresh operation, apart from reading a report.

Treat missing or old data as unknown, never as zero cost or good health. To report business results, add
your own measures to the application.

## Optional health models

The `healthmodel` package deploys an Azure Monitor health model for a project: a tree of the services, the
signals of each one and the alerts. It has its own Azure DevOps and GitHub Actions pipelines and uses the
preview API `Microsoft.CloudHealth`. Check that your region supports it.

[Health model guide](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/healthmodel/readme.md)

## Agent Chat and MCP

| Component | What it is for |
| --- | --- |
| ESAF Agent Chat | Ask questions about your Factory and its documentation, in a chat that answers from the sources. See [Enable ESAF Agent Chat](setup/04-first-agent-chat.md). |
| Agent Chat live voice | Talk to the same agent. A voice orb shows when it listens, thinks and speaks. It needs Agent Chat, an Entra ID app registration and private access to Foundry. |
| Factory MCP server | Gives MCP clients, such as an agent, the read-only tools of the Factory. |
| Private Azure MCP template | Gives the agents of your workload read-only tools for Azure resources. |
| MCP on the AI gateway | Publishes the Factory MCP server through API Management. It is an optional step of the project 001 Dev pipeline. |

Each of these acts with the permissions of the person or the identity that calls it.

<details markdown="1">
<summary>More info</summary>

[Dashboards](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/documentation/v2/30-39/32-dashboards.md) |
[Agent Chat template](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/usecase_code/40-agent-factory/40-aifactory-agent/readme.md) |
[Factory MCP](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/mcp/readme.md) |
[Private Azure MCP template](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/usecase_code/40-agent-factory/44-azure-mcp/readme.md) |
[MCP on the AI gateway](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/usecase_code/40-agent-factory/45-aifactory-mcp-gateway/readme.md) |
[Agent Chat and live voice](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/documentation/v2/10-19/21-agent-factory-chat.md)

Model calls, monitoring queries and deployments each need their own permissions, and each has its own cost.

</details>
