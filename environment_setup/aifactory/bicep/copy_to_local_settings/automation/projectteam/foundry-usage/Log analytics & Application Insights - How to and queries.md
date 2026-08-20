# Log Analytics & Application Insights - How to and queries

Use this guide to explore Foundry and Azure OpenAI usage yourself, then turn the results into the same daily charts as the PDF reports.

## Before you start

Your Foundry or Azure OpenAI resource must send the `RequestResponse` and `Trace` diagnostic categories to the Log Analytics workspace. The identity opening the workspace needs **Log Analytics Reader** permission. Run `verify-and-configure-foundry-diagnostics.sh` to check this automatically; add `--apply` to create or repair the workspace diagnostic setting. Open the Azure portal, then search for and select the relevant **Log Analytics workspace**.

The report queries use `AzureDiagnostics`. The verifier reports the diagnostic setting's `logAnalyticsDestinationType`: unset or `AzureDiagnostics` uses this table; `Dedicated` writes to resource-specific tables. For a dedicated destination, select **Logs**, inspect the tables list, and replace `AzureDiagnostics` with the appropriate Cognitive Services table.

## Run a query and make a chart

1. In the Log Analytics workspace, select **Logs** from the left navigation. If you started from Application Insights, select **Monitoring** > **Logs** instead.
2. Select **New query**, paste a query below, and update the `ResourceId` value.
3. Set the portal time range to **Last 30 days**, or leave the query's `ago(30d)` filter in place.
4. Select **Run**.
5. Select **Chart**, choose **Time chart**, and set the aggregation to `Sum` or `Count` as appropriate. For a separate line per model deployment, choose **Split by** > `ModelDeployment`.
6. Select **Save** to add the chart to a Log Analytics dashboard or Azure dashboard.

For a point-and-click view, open the Foundry, Azure OpenAI, or Application Insights resource, then select **Monitoring** > **Insights** to review the built-in overview. Select **Monitoring** > **Metrics** to create a custom chart. Set the time range to 30 days and add request/token metrics such as `ModelRequests`, `InputTokens`, and `OutputTokens`. Use **Apply splitting** only when a deployment dimension is offered.

## Shared query setup

The following expressions normalize the resource ID, model deployment name, and diagnostic JSON fields. Paste them before the query body when using the queries below.

```kusto
let ResourceId = tolower("/subscriptions/<subscription-id>/resourceGroups/<resource-group>/providers/Microsoft.CognitiveServices/accounts/<foundry-or-openai-resource>");
let StartTime = ago(30d);
let UsageEvents =
    AzureDiagnostics
    | where TimeGenerated >= StartTime
    | where tolower(ResourceProvider) == "microsoft.cognitiveservices"
    | extend ActualResourceId = tolower(iff(
        isnotempty(tostring(column_ifexists("_ResourceId", ""))),
        tostring(column_ifexists("_ResourceId", "")),
        tostring(column_ifexists("ResourceId", ""))))
    | where ActualResourceId == ResourceId
    | extend Properties = todynamic(column_ifexists("properties_s", "{}"))
    | extend ModelDeployment = coalesce(
        tostring(Properties["modelDeploymentName"]),
        tostring(Properties["deploymentName"]),
        tostring(Properties["deployment"]),
        tostring(Properties["model"]),
        "Unspecified");
```

## Requests per day for Foundry models

Set `ResourceId` in the shared setup to the Foundry account. This counts the diagnostic request events and produces a line per model deployment.

```kusto
UsageEvents
| where Category in~ ("RequestResponse", "Trace")
| summarize Requests = count() by Day = bin(TimeGenerated, 1d), ModelDeployment
| order by Day asc
| render timechart
```

## Requests per day for Azure OpenAI models

Run the same request query, but set `ResourceId` to the Azure OpenAI account instead. This keeps Foundry and Azure OpenAI usage separate.

```kusto
UsageEvents
| where Category in~ ("RequestResponse", "Trace")
| summarize Requests = count() by Day = bin(TimeGenerated, 1d), ModelDeployment
| order by Day asc
| render timechart
```

## Token usage for model deployments

Set `ResourceId` to the Foundry or Azure OpenAI account. Enable the `AzureOpenAIRequestUsage` diagnostic category with `verify-and-configure-foundry-diagnostics.sh --enable-azure-openai-request-usage --apply`; this query returns input, output, and cached token totals by deployment and day. Fields absent from the diagnostic payload are reported as zero.

```kusto
UsageEvents
| where Category == "AzureOpenAIRequestUsage"
| extend InputTokens = coalesce(
    todouble(Properties["inputTokens"]),
    todouble(Properties["promptTokens"]),
    todouble(Properties["input_tokens"]),
    0.0)
| extend OutputTokens = coalesce(
    todouble(Properties["outputTokens"]),
    todouble(Properties["completionTokens"]),
    todouble(Properties["output_tokens"]),
    0.0)
| extend CachedTokens = coalesce(
    todouble(Properties["cachedTokens"]),
    todouble(Properties["cacheReadInputTokens"]),
    todouble(Properties["cached_tokens"]),
    0.0)
| summarize
    InputTokens = sum(InputTokens),
    OutputTokens = sum(OutputTokens),
    CachedTokens = sum(CachedTokens)
    by Day = bin(TimeGenerated, 1d), ModelDeployment
| order by Day asc
```

To chart total token usage, append:

```kusto
| extend TotalTokens = InputTokens + OutputTokens + CachedTokens
| project Day, ModelDeployment, TotalTokens
| render timechart
```

## Application Insights sessions and requests

Application Insights is useful for application-level request volume and approximate session counts. Open the Application Insights resource, select **Monitoring** > **Logs**, and run:

```kusto
AppRequests
| where TimeGenerated >= ago(30d)
| summarize
    Requests = count(),
    ApproximateSessions = dcountif(session_Id, isnotempty(session_Id))
    by Day = bin(TimeGenerated, 1d)
| order by Day asc
| render timechart
```

This counts calls reaching the application, not necessarily calls reaching a specific Foundry deployment. To attribute application requests to a deployment, include the deployment name in an Application Insights custom dimension and extract it with `customDimensions["modelDeploymentName"]`.
