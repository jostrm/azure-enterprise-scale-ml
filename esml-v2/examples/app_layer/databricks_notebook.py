# Databricks notebook source
"""Example existing notebook job for the three all-DBX inference steps.

Install a pinned azure-esml-sdk[train] on the job cluster beforehand. Configure
job parameters context, inputs, outputs (all JSON strings); Databricks pushes
these parameters into the notebook widgets. Configure the cluster's identity
to access the bridge's WASBS container without embedding credentials here.

This driver-sized raw/Delta/Parquet example reuses the same pandas/MLflow runtime as
Azure ML, not a distributed Spark implementation. Training/splitting/evaluation
replacements require customer notebooks implementing their declared ports.
"""

import json
from pathlib import Path
import shutil
from uuid import uuid4

from azure_esml.domain_layer.contracts import StepType
from azure_esml.domain_layer.databricks import SCHEMA
from azure_esml.domain_layer.runtime import run_operation


def execute(dbutils, *, work_root=".esml-databricks"):
    context, inputs, outputs = (
        json.loads(dbutils.widgets.get(name)) for name in ("context", "inputs", "outputs")
    )
    operation = {
        StepType.IN_2_BRONZE.value: "in2bronze",
        StepType.BRONZE_2_SILVER.value: "bronze2silver",
        StepType.IN_2_SILVER.value: "in2silver",
        StepType.SILVER_MERGED_2_GOLD.value: "merge",
        StepType.INFERENCE_GOLD.value: "inference",
    }[context["step"]]
    if set(outputs) != {"output"}:
        raise ValueError("This example requires the single output port")
    root = (Path(work_root) / uuid4().hex).absolute()
    root.mkdir(parents=True)
    try:
        local_inputs = {}
        for name, uri in inputs.items():
            if not name.isidentifier() or not uri.startswith("wasbs://"):
                raise ValueError("Expected named WASBS input folders")
            target = root / name
            if not dbutils.fs.cp(uri, target.as_uri(), recurse=True):
                raise RuntimeError(f"Could not download {name}")
            local_inputs[name] = target
        model = local_inputs.pop("model", None)
        labels = context.get("input_labels", {})
        local_inputs = {labels.get(name, name): path for name, path in local_inputs.items()}
        output = root / "result"
        run_operation(operation, context, output, inputs=local_inputs, model=model)
        if not outputs["output"].startswith("wasbs://"):
            raise ValueError("Expected the bridge's predetermined WASBS output folder")
        if not dbutils.fs.cp(output.as_uri(), outputs["output"], recurse=True):
            raise RuntimeError("Could not upload output")
    finally:
        shutil.rmtree(root)
    dbutils.notebook.exit(json.dumps({"schema": SCHEMA, "outputs": outputs}))


if __name__ == "__main__":
    execute(dbutils)  # noqa: F821 - supplied by the Databricks notebook runtime
