# Monitor and operate

Choose the question you want to answer. Factory inventory, deployment progress,
usage, billing and workload health are different views.

| Your question | Use | Important limit |
| --- | --- | --- |
| Is the Factory API running? | `health` | Process health, not Azure resource health. |
| What is registered or deployed? | Catalog/inventory and the selected run's results | Refreshing a list is not telemetry collection. |
| Did this deployment finish? | Exact job status, logs and provider/worker completion records | Submission or local script exit does not prove deployment success. |
| How much was used or billed? | Usage workbooks/reports and explicit Cost Management reads | Billing can be delayed; modelled cost is not billed cost. |
| Are services healthy together? | Optional Azure Monitor health-model component | Preview service and separate setup; missing signals remain unknown. |

[CLI, SDK and REST observation examples](factory-tools/20-cli-and-api-and-usage.md)
include job status, logs, GitHub workflow watch, saved reports and resource-group
cost reads. A GitHub watcher is not an ADO watcher.

## Metrics, reports and dashboards

- **Sample reports** use demonstration data, not customer usage.
- **Saved reports** read existing results. They do not silently collect new
  telemetry or provision monitoring.
- **Live reads** require the correct identity and scope. A request may read
  Azure even when it does not change resources.
- **Dashboard-only refresh** is a separate plan/apply operation for dashboard
  resources, not a side effect of reading a report.

Missing, stale or incomplete observations are not zero cost or good health.
Business-outcome reporting needs application instrumentation and agreed measures.
Creating a report does not mean its attachments were emailed.

## Optional health models

The published `healthmodel` package provides an optional Azure Monitor health
tree, signal configuration, alerts and separate ADO/GHA deployment entry points.
It uses the preview `Microsoft.CloudHealth` API. Check supported regions,
permissions and signal sources for your environment.

This is not the same as API `health`, an MCP dependency check, or a universally
integrated `azurefactory healthmodel` command. The package's recorded test results
are not a guarantee of current availability in another subscription.

[Health-model component guide](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/healthmodel/readme.md)

## Agent Chat and MCP

| Component | Purpose |
| --- | --- |
| Factory Agent Chat | A scoped, source-grounded management assistant using configured Search/Foundry and Factory operation adapters. |
| Factory MCP | MCP clients/servers and host adapters for available Factory capabilities. |
| Private Azure MCP example | A distinct narrow, read-only Azure resource-tool example for workloads. |
| Project001 Dev MCP/AI Gateway integration | An opt-in pipeline component with explicit image, identity and network prerequisites. |
| Factory Agent Chat live voice | An opt-in speech layer (Azure Voice Live) on the same governed chat: talk to the agent and watch the voice orb listen, think and speak. Needs the chat agent flag, an Entra registration and private connectivity to Foundry. |

These components do not bypass caller permissions or human approval. Enabling
a conversational interface does not grant access to every factory or turn
missing actions into successful operations.

<details markdown="1">
<summary>More info</summary>

Published references:
[dashboards](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/documentation/v2/30-39/32-dashboards.md),
[Factory Agent Chat](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/usecase_code/40-agent-factory/40-aifactory-agent/readme.md),
[Factory MCP](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/mcp/readme.md),
[private Azure MCP example](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/usecase_code/40-agent-factory/44-azure-mcp/readme.md),
[gateway integration](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/usecase_code/40-agent-factory/45-aifactory-mcp-gateway/readme.md),
[Agent Factory chat and live voice](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/documentation/v2/10-19/21-agent-factory-chat.md).

The local dual graph combines code relationships and architecture notes. It is
a navigation aid, not current Azure state. Unpublished graph/authentication or
multi-model health enhancements described in local release addenda are not
automatically present in published `main` or an installed application.

Cloud inference, monitoring queries and actual operations have their own
permissions and potential costs. A successful source build is not a live
deployment or compliance certification.

</details>
