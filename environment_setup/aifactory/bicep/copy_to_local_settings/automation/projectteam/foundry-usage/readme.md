# Foundry usage PDF report

`foundry_usage_report.py` creates a PDF report for all Azure AI Foundry / Azure OpenAI resources and Azure AI Search services in one resource group. It reports the last 30 calendar days by default, with:

- deployment-level request and token metrics from Azure Monitor, when the metric exposes a deployment dimension;
- Azure OpenAI input, output, and cached-token metrics when available;
- AI Search request/query metrics;
- Log Analytics telemetry request, token, and approximate unique-session activity;
- a daily and hourly table report, a Foundry/OpenAI request line chart, and a Foundry/OpenAI token line chart.

The report is aggregate-only: no session or user identifiers are written to the PDF or optional debug JSON.

## Prerequisites

1. Send Foundry/Azure OpenAI `RequestResponse` and `Trace` diagnostic categories to a Log Analytics workspace. Enable Application Insights request telemetry if unique sessions are required. Application Insights components in the selected resource group are included automatically.
2. Assign the running identity:
   - **Reader** on the target resource group for resource discovery and Azure Monitor metrics.
   - **Log Analytics Reader** on the target Log Analytics workspace for telemetry.
3. Install the Python dependencies:

   ```bash
   python3 -m pip install -r requirements.txt
   ```

4. Authenticate with either `az login` (local execution) or a managed identity (Azure Automation / Hybrid Runbook Worker).
5. For the Bash diagnostic and saved-query utilities, install `jq` as well as Azure CLI.

## Verify and configure diagnostics

Use the verifier before running a usage report. It checks every Foundry/Azure OpenAI resource in the resource group for a diagnostic setting that targets the selected workspace, checks that `RequestResponse` and `Trace` are enabled, and reports the configured Log Analytics destination type.

```bash
./verify-and-configure-foundry-diagnostics.sh \
  --subscription-id "<subscription-id>" \
  --resource-group "<resource-group>" \
  --workspace-resource-id "/subscriptions/<subscription-id>/resourceGroups/<workspace-resource-group>/providers/Microsoft.OperationalInsights/workspaces/<workspace-name>"
```

Add `--apply` to create a missing workspace diagnostic setting or enable only the required categories. Existing categories and destinations are preserved. Add `--enable-azure-openai-request-usage --apply` to also collect the token-focused Azure OpenAI usage category, where the resource supports it. It requires permission to write diagnostic settings, such as **Monitoring Contributor**, on each Foundry/Azure OpenAI resource.

An unset or `AzureDiagnostics` destination type means the report and saved queries use `AzureDiagnostics`. A `Dedicated` destination means logs land in resource-specific tables, so identify the table in the Log Analytics portal and pass it with `--telemetry-table` when saving queries.

## Save portal queries

The following creates or updates three queries under the workspace's **Logs** > **Queries** experience. Each query is run successfully against the workspace before it is saved, and is grouped in the `AIFactory usage` category.

```bash
./save-foundry-usage-queries.sh \
  --subscription-id "<subscription-id>" \
  --resource-group "<resource-group>" \
  --workspace-resource-id "/subscriptions/<subscription-id>/resourceGroups/<workspace-resource-group>/providers/Microsoft.OperationalInsights/workspaces/<workspace-name>" \
  --telemetry-table AzureDiagnostics
```

The saved query display names are `AIFactory-usage-query-01 - Foundry requests per day`, `AIFactory-usage-query-02 - Azure OpenAI requests per day`, and `AIFactory-usage-query-03 - Foundry model deployment token usage`. The identity needs **Log Analytics Reader** to validate the query and `Microsoft.OperationalInsights/workspaces/savedSearches/write` permission, provided by **Log Analytics Contributor**, to save it.

## Run locally or on a Hybrid Runbook Worker

Run from this folder. `--as-of-date` is optional and is the inclusive end date; it must be `YYYY-MM-DD`. The script otherwise uses today in the selected time zone.

```bash
./run-foundry-usage-report.sh \
  --subscription-id "<subscription-id>" \
  --resource-group "<resource-group>" \
  --workspace-id "<log-analytics-workspace-customer-id>" \
  --time-zone "Europe/Berlin" \
  --as-of-date "2026-08-19" \
  --output "./output/foundry-usage-2026-08-19.pdf"
```

When `--output` is omitted, all PDFs are written to this folder's `output` directory. The command also writes `Model-Requests-report-YYYY-MM-DD.pdf` and `Foundry-Token-report-YYYY-MM-DD.pdf` beside the table report. Override their destinations with `--model-requests-output` and `--foundry-token-output`.

Find the workspace customer ID with:

```bash
az monitor log-analytics workspace show \
  --resource-group "<workspace-resource-group>" \
  --workspace-name "<workspace-name>" \
  --query customerId -o tsv
```

Use `--debug-json ./foundry-usage.json` only for troubleshooting or data validation; it contains aggregate report values.

## Azure Automation runbook

Azure Automation Python runbooks require their third-party packages to be available in the selected runtime environment. Import the packages from `requirements.txt` into that runtime, or use a Hybrid Runbook Worker with the dependencies installed. Use the same managed identity permissions listed above. Set the Automation variables below, then invoke the runbook with the corresponding arguments:

| Variable | Value |
| --- | --- |
| `AZURE_SUBSCRIPTION_ID` | Target subscription ID |
| `AZURE_RESOURCE_GROUP` | Resource group holding Foundry/OpenAI/Search |
| `LOG_ANALYTICS_WORKSPACE_ID` | Log Analytics workspace customer ID |

Publish `foundry_usage_report.py` to an HTTPS location readable by Azure Automation, then deploy the runbook:

```bash
az deployment group create \
  --resource-group "<automation-resource-group>" \
  --template-file foundry-usage-runbook.bicep \
  --parameters automationAccountName="<automation-account-name>" \
               automationAccountLocation="<automation-account-location>" \
               runbookContentUri="https://<storage-account>.blob.core.windows.net/<container>/foundry_usage_report.py?<sas>"
```

For a cloud Automation worker, write the output to an authenticated storage target or execute this on a Hybrid Runbook Worker with a persistent output directory. Azure Automation job output alone does not retain generated files. The runbook prints the PDF path on completion.

## Data coverage and limitations

Azure Monitor metric names and dimensions vary by resource kind, model API version, and region. The script discovers supported metrics dynamically and requests all metric definitions whose names indicate requests, calls, queries, tokens, or cache tokens. This avoids hard-coding model names and includes new deployments automatically. Metrics are primary for request and token totals.

Log Analytics adds approximate unique sessions from Application Insights `session_Id` or known session custom dimensions. Distinct sessions cannot be added across hour buckets without over-counting, so the report labels the session column accordingly. If diagnostics do not emit tokens or session identifiers, those fields remain zero while Azure Monitor metrics still populate available request/token usage.
