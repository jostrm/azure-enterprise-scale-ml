[Docs](../README.md) › [Usage docs](README.md)

# Quickstart: Train your first model in your ESAF project

In this quickstart, you validate a scenario and train your first model on your own machine. A **scenario** is
one JSON file that names your data, your features, your model and the quality gates it must pass.

> [!TIP]
> This page gives you the short path. The template's own guide has every option:
> [ML Model Factory: your configuration](../../../usecase_code/50-ml-model-factory/user-config/readme.md#project-team-quickstart).

You train locally first. The same scenario then runs in Azure Machine Learning in your ESAF project.

## Prerequisites

- The [usage prerequisites](prerequisites.md): an ESAF project, access to it and Python 3.10 to 3.13.
- A local `diabetes.csv` that matches the
  [scenario's features and label](../../../usecase_code/50-ml-model-factory/user-config/model/scenarios/diabetes.json).
  The data isn't bundled. Check its license before you use it.

## Prepare your environment

1. Open PowerShell in your checkout of this repository.
2. Create the environment and install the package:

   ```powershell
   Set-Location .\usecase_code\50-ml-model-factory
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -e ".[train]"
   ```

## Validate the scenario

Check the scenario, then list the routes it can take. Neither step calls Azure:

```powershell
.\.venv\Scripts\python.exe -m ml_model_factory validate --scenario user-config\model\scenarios\diabetes.json
.\.venv\Scripts\python.exe -m ml_model_factory usecases --pattern batch --task-folder classification --technology notebook
```

## Train and evaluate the model

Save this as `train_local.py` in the same folder, then run it with `.\.venv\Scripts\python.exe .\train_local.py`:

```python
import json
from pathlib import Path
from uuid import uuid4
from ml_model_factory.config import load_json, validate_scenario
from ml_model_factory.data import prepare
from ml_model_factory.training import train
from ml_model_factory.evaluation import evaluate

scenario = validate_scenario(load_json(Path("user-config/model/scenarios/diabetes.json")))
csv_path = Path(input("Path to your local diabetes.csv: ").strip()).resolve(strict=True)
run_dir = Path("ml-environment/outputs/diabetes") / ("local-" + uuid4().hex)
prepared, model, report = run_dir / "prepared", run_dir / "model", run_dir / "report"
manifest = prepare(scenario, csv_path, prepared)
train(scenario, prepared, model)
evaluation = evaluate(scenario, prepared, model, report)
print(json.dumps({"output": str(run_dir), "metrics": evaluation["metrics"]}, indent=2))
```

The script prepares the data, trains the model and checks it against the scenario's quality gates. It writes
only local files. It registers no model and deploys no endpoint.

## Verify the result

The script prints the output folder and the metrics. In that folder you find:

| File | What it tells you |
|---|---|
| `prepared\manifest.json` | Shows how the data was split. |
| `report\metrics.json` | Lists the model's metrics. |
| `report\quality-gate.json` | States whether the model passed its gates. |
| `report\responsible-ai.json` | Summarizes the responsible AI checks. |

A failed gate raises an error. Investigate it; don't change the gate to make it pass.

This scenario is a teaching example. It isn't clinical decision support.

## Clean up resources

Nothing was created in Azure. Remove the local output and the environment:

```powershell
Remove-Item -Recurse -Force .\ml-environment\outputs\diabetes, .\.venv
```

## Next step

**Back:** [Quickstart: Run your first agent in your ESAF project](01-first-agent.md)

**Next:** [View your project dashboards](dashboards.md)

Related:

- [Azure test status](../../../usecase_code/50-ml-model-factory/readme.md#azure-test-status): which cloud
  routes are tested. Batch classification with an Azure Machine Learning pipeline is one of them.
- [Use-case catalog](../../../usecase_code/50-ml-model-factory/usecase-type/readme.md): batch, online and
  streaming patterns.
- [MLOps](../30-39/37-mlops.md): from a trained model to a monitored one.
