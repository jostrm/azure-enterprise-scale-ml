# databricks

**Purpose:** Configure existing Databricks clusters, notebook paths, wheel libraries and inference settings.

**Owner:** User-editable configuration.

**Edit/run guidance:** In your orange project, edit `job-template.json` and copy `inference-settings.example.json` / `azureml-step.example.json` to `inference-settings.local.json` / `azureml-step.local.json` (the names the leaf notebooks read); resolve every `<placeholder>` and select an existing cluster. The renderer refuses `new_cluster` definitions; compute must be governed outside the factory. Secrets are referenced by scope/key only and are never stored here.

**Status:** Maintained scaffold; rendering is offline and creating or running jobs needs an explicit `--execute`.

Typical commands from the factory root:

```powershell
.\.venv\Scripts\ml-model-factory.exe databricks-job render --scenario user-config\model\scenarios\titanic.json --pattern batch --orchestration databricks --template user-config\databricks\job-template.json --settings user-config\databricks\inference-settings.example.json --scenario-path /Workspace/Shared/ml-model-factory/user-config/model/scenarios/titanic.json --output job.batch.json
.\.venv\Scripts\ml-model-factory.exe databricks-job create --job job.batch.json --host https://adb-<id>.<region>.azuredatabricks.net --auth azure-cli --receipt databricks-run.json --execute
.\.venv\Scripts\ml-model-factory.exe databricks-job run --job-id <job-id> --host https://adb-<id>.<region>.azuredatabricks.net --auth azure-cli --receipt databricks-run.json --execute
```

Use `--pattern online` for the `register-serve` task and `--pattern streaming` for the continuous `stream-score` task. Streaming runs stay active until cancelled; the checkpoint root and Event Hubs secret scope must already exist.

[Shared backend code](../../accelerator/databricks/readme.md)

For Azure ML Databricks-step pipelines, render the referenced Databricks job with `databricks-job render --orchestration azureml` so inference tasks read `{{job.parameters.model_uri}}`; the AML step reads `model_uri.txt` from the training step and passes that job parameter while running only the selected task with `--only-task`. Use `azureml-step.example.json` as the AML pipeline config surface.

`databricks-job run` also supports `--only-task KEY`, repeatable; `--wait-for running|terminated`; `--new-run` to archive a non-succeeded receipt and intentionally start a new Databricks run.
