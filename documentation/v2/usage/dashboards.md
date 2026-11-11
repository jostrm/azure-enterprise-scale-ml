[Docs](../README.md) › [Usage docs](README.md)

# View your project dashboards

Your ESAF project comes with dashboards that answer three questions: what does it cost, how much is it used,
and is it healthy? This page shows where each dashboard lives and how to open it for your project.

Before you start, check the [usage prerequisites](prerequisites.md). You also need the Reader role on your
project's resource group, which your project's Entra group gives you.

## Where the dashboards live

| Dashboard | Where it lives | Best for |
|---|---|---|
| Project dashboard | Azure portal, in your project's resource group | A daily look at cost, usage and shortcuts to your services |
| My Project - Usage and Cost workbook | Azure Monitor, linked from the project dashboard | Token usage per model, resources per region and health |
| Monitoring in the ESAF app | The desktop app your platform team runs | Reports across projects: value, cost, quality and security |

All three read the same Azure sources: Cost Management for cost, and Azure Monitor for usage and health.

## Open your project dashboard

1. In the [Azure portal](https://portal.azure.com), open your project's resource group.
2. Filter the resources on the type **Shared dashboard**.
3. Select your project's dashboard, then select **Go to dashboard**.

To find the resource group from a terminal:

```powershell
az group list --subscription <your subscription ID> --query "[?contains(name, 'project001')].name" --output table
```

Your platform team deploys the dashboard with your project. If you can't find it, ask them to deploy it.

## Read the project dashboard

| Area | What you see |
|---|---|
| Resource group, on the left | Lists every resource in your project. |
| Cost analysis, on the right | Shows this month's accumulated cost for your project. |
| Shortcuts | Open Foundry, Storage, Key Vault, AI Search and Application Insights. Azure Machine Learning, Databricks and Data Factory appear when your project has them. |
| Daily cost charts | Show the daily total, and the daily total per service, with Azure's forecast. |
| Foundry tiles | Show requests, calls and content safety counts for the past 30 days. |
| Report cards | Open the Usage and Cost workbook. |

The two cost charts show the same cost in two ways. Don't add them together.

## Read cost, usage and health

| Question | Where to look | Keep in mind |
|---|---|---|
| What does my project cost? | **Cost analysis** and the daily cost charts | These show actual billed cost. A forecast is a prediction, not a charge. |
| How much is it used? | The Foundry tiles and **View** > **Model tokens** in the workbook | Token counts are usage, not cost. Don't turn them into money yourself. |
| Is it healthy? | The workbook's health section and Application Insights | A number on the region map counts resources, not incidents. |

Change the time range at the top of the dashboard. It starts at the past 30 days.

## Ask in the ESAF app

Your platform team can also open your project in the ESAF app, under **Monitoring** > **My Project**. It
shows usage and outcomes beside a separate **Cost** tab, for one project and one environment at a time. Ask
them for a report when you need numbers across several projects.

**Next:** [Usage docs](README.md)

Related: [Tutorial: FinOps monitoring](../20-29/tutorial-fiops.md) ·
[Monitoring: value, cost and trust](../30-39/32-dashboards.md), the full reference for platform teams
