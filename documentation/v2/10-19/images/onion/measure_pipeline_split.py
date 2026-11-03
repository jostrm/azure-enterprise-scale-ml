#!/usr/bin/env python3
"""Split each measured pipeline run of onion-layers-v2.json into L3 / L4 / L5 minutes from its GitHub step times.

    python measure_pipeline_split.py --repo jostrm/azure-enterprise-scale-byor-138

Needs `gh` with read access to the consumer repository. Prints one "split" object per run to copy into the data file.
The rule (evidence R4 in onion-layers-v2.json):

* L5 Azure Resource Manager: steps that deploy or delete in Azure - the numbered az deployment steps (the Bicep
  compile runs inside them), deletes, purges, waits for Azure, and the worker's reviewed-plan execution.
* L4 pipeline-called scripts: checks, parameter generation, reports and other script steps.
* L3 pipelines: the rest of the run's wall clock - queue, runner setup, checkout, login and the gaps between jobs.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "onion-layers-v2.json"
AZURE_WORK = re.compile(r"delete|purge|wait|rehydrate|execute only the protected reviewed plan|deploy|approve", re.I)
SCRIPT = re.compile(r"check(?!out)|generate|reconcile|prepare|preflight|report|calc", re.I)
DEPLOYMENT = re.compile(r"^\d+[a-z]?\d*[-_]")


def minutes(start: str, end: str) -> float:
    parse = lambda value: datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (parse(end) - parse(start)).total_seconds() / 60


def layer_of(step: str) -> str:
    if AZURE_WORK.search(step):
        return "l5"
    if SCRIPT.search(step):
        return "l4"
    return "l5" if DEPLOYMENT.match(step) else "l3"


def split(run: dict) -> dict:
    wall = minutes(run["createdAt"], run["updatedAt"])
    spent = {"l4": 0.0, "l5": 0.0}
    for job in run["jobs"]:
        for step in job["steps"]:
            if step.get("startedAt") and step.get("completedAt"):
                layer = layer_of(step["name"])
                if layer != "l3":
                    spent[layer] += minutes(step["startedAt"], step["completedAt"])
    return {"l3": round(wall - spent["l4"] - spent["l5"], 1), "l4": round(spent["l4"], 1), "l5": round(spent["l5"], 1)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--data", type=Path, default=DATA)
    args = parser.parse_args()
    for entry in json.loads(args.data.read_text(encoding="utf-8"))["runs"]:
        if entry.get("run_id"):
            raw = subprocess.run(["gh", "run", "view", entry["run_id"], "-R", args.repo, "--json", "jobs,createdAt,updatedAt"],
                                 check=True, capture_output=True, text=True).stdout
            print(entry["id"], json.dumps(split(json.loads(raw))))


if __name__ == "__main__":
    main()
