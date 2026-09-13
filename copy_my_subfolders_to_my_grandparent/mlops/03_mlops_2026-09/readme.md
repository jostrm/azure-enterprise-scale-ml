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

## Opt-in candidate/champion selection

Without selection configured, training keeps the existing behavior: a successful
pipeline that passes the registration quality/lineage gate is registered as a
candidate. **Configure selection to prevent automatic registration of a model
that does not beat the champion.** This does not switch endpoint traffic.

Both ADO and GitHub read the same optional object from the environment-specific
runtime JSON (no additional workflow inputs or SDK v1 configuration):

```json
{
  "model_selection": {
    "policy": "..\\model-selection.json",
    "champion_evaluation": "champions\\reviewed-comparison.json"
  }
}
```

Add this object alongside the existing runtime fields. Selection file paths
resolve relative to the **runtime JSON's directory**, not the runner's working
directory; absolute paths also work. Choose the paths for your checkout layout.
The editable canonical policy is
[`usecase_code/50-ml-model-factory/model-selection.json`](../../../usecase_code/50-ml-model-factory/model-selection.json).
It has profiles for all seven supported tasks. Each selected metric has its own
maximize/minimize direction and signed `min_delta`: positive requires improvement,
negative allows a bounded regression. Absolute deltas use metric units; relative
deltas divide direction-correct improvement by the champion's absolute value.
Every selected rule must pass; there is no weighted score across unlike metrics.

Use a reviewed, immutable champion's `comparison.json` produced by the evaluation
wrapper on the same scoped held-out data and feature contract. Missing/undefined
selected metrics or incompatible evidence block registration. The current
candidate is **never** supplied as a manual file: CI downloads the completed job's
named `report` output through SDK v2 and requires exactly one `comparison.json`.
Its factory/project/environment, use case and task must match this run. The
existing server-side status, quality and lineage registration checks still apply.
For a winning candidate, CI also passes the same loaded policy and champion to
the SDK registration gate. That gate downloads and rechecks the report immediately
before writing the registry, verifies evidence against model/metrics lineage, and
adds winner/policy/evidence tags. CI's earlier comparison is not a registration
authorization token.

For a deliberate first model, replace `champion_evaluation` with
`"no_champion": true`; the policy must also permit initial selection. A missing
champion file never means bootstrap. The standalone training command also accepts
`--selection-policy POLICY` plus exactly one of
`--champion-evaluation EVIDENCE` or `--no-champion`. These flags replace the entire
runtime selection object and use the same runtime-relative path resolution.

Outcomes:

- `candidate_wins`: continue through the existing registration gate; write
  `registered-model.json` only after registration returns a model ID.
- `champion_kept`: successful training with registration skipped, no receipt,
  and a structured JSON outcome on stdout.
- `blocked`: fail with actionable reasons; do not write to the model registry.

CI saves `selection-decision.json` with the actual submitted job, named output,
policy/evidence hashes and comparison details, plus `training-status.json`.
The registration gate's independent result is saved as
`registration-selection-decision.json` when reached.
Workflows publish the status/decision artifacts even for a blocked comparison;
the registration artifact is conditional on an actual receipt. Review these
artifacts as provenance, not as a substitute for the registration gate. Deployment
remains a separate, explicitly approved action with an explicit model ID.
