# Latest version of MLOps

- Using Infra som Enteprise Scale AI Factory, with Dev, Stage, Prod environment. 
- Leveraging the Enteprrise Scale AI Factory UX; considering "AI Factory" view with MLOps, and DataOps

## Model identity for SDK/CLI v2 registration

The current model-factory registration path requires explicit `aifactory`,
three-digit `project`, and `environment_name` in runtime JSON, or matching lake
scope. `environment_name` means dev/test/prod; runtime `environment` remains the
Azure ML environment asset. Do not confuse these two values.

Both SDK and CLI v2 use the same model-tag dictionary and quality/lineage gate.
Tags must agree with the selected factory, project, environment, use case and
dataset/snapshot/run paths. Missing or conflicting identity stops registration.
Registered models remain candidates until a separate promotion/deployment decision.
CI does not silently rewrite training origin when selecting a deployment target.

See [MLOps and model tags](../../../documentation/v2/30-39/37-mlops.md)
and [the lake layout](../../../documentation/v2/30-39/34-datalake-onboard-data.md)
for the full execution and storage contracts.

