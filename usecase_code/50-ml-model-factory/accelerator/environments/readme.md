# environments

**Purpose:** Maintain default dependency specifications used by Azure ML jobs.

**Owner:** Maintainer-owned defaults.

**Edit/run guidance:** These YAML files are environment build specifications, not deployed Azure resources. Select pinned references in project settings; put custom overrides in user-config/model/environments.

**Status:** Maintained scaffold; local/cloud execution is explicit, never automatic.

`azureml-serving-*.yml` add `azureml-inference-server-http` for custom-code online scoring;
stream jobs add `azure-eventhub` and `azure-identity` to the task's training base at render time.
AutoML image evaluation, scoring and streaming need explicitly pinned environments in runtime JSON.

[Model-factory guide](../../readme.md)
