"""Several health models in one run: built-in, consumer and in-code definitions on one composition.

Shows the object-oriented core: the composition root (dependency injection), an infrastructure
family (Azure CLI or an offline inventory), the definition registry, the event bus (observer)
and the HealthModelService facade.

    # Offline demo on the anonymized test factory: no Azure access, nothing is written
    python usecase_code/06_multiple_models.py --demo

    # Against a factory: read-only plan; --apply deploys every planned model
    python usecase_code/06_multiple_models.py --consumer-root ..\\.. --variables-json aifactory/variables.json \\
        --environment dev --project 001 [--definitions-dir ..\\..\\aifactory\\healthmodels] [--apply]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aifactory_healthmodel import deploy, naming  # noqa: E402
from aifactory_healthmodel.application.events import CommandExecuted, EventBus, ModelPlanned  # noqa: E402
from aifactory_healthmodel.application.service import HealthModelService, RunRequest  # noqa: E402
from aifactory_healthmodel.bootstrap import Settings, create_services  # noqa: E402
from aifactory_healthmodel.domain.definitions import DefinitionRegistry  # noqa: E402
from aifactory_healthmodel.infrastructure.azure_cli import AzureCliInfrastructure  # noqa: E402
from aifactory_healthmodel.infrastructure.offline import OfflineInfrastructure  # noqa: E402

# A model defined in code: the data platform of one project (lakes, databases, pipelines).
DATA_PLATFORM = {
    "key": "data-platform",
    "description": "Data platform of one project: storage, databases and data pipelines.",
    "nameToken": "dat{project}",
    "home": "project",
    "rootDisplayName": "AI Factory data platform, project {project} ({env})",
    "layers": [
        {"key": "lake", "displayName": "Data lake and storage", "impact": "Standard",
         "select": {"profile": ["storage", "adls-gen2"]}},
        {"fromCatalog": True, "select": {"origin": "project", "layer": ["data", "analytics"]}},
    ],
    "healthObjective": 98,
}

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--demo", action="store_true", help="Plan offline on the anonymized test factory inventory.")
parser.add_argument("--definitions-dir", action="append", default=[], help="Consumer definitions folder (repeat).")
parser.add_argument("--apply", action="store_true", help="Deploy the planned models (writes to Azure).")
for name in ("consumer-root", "variables-json", "environment", "project"):
    parser.add_argument(f"--{name}")
args = parser.parse_args()

if args.demo:
    scope = naming.explicit(
        tenant_id="11111111-1111-1111-1111-111111111111", subscription_id="00000000-0000-0000-0000-0000000000aa",
        environment="dev", project_number="001", location="swedencentral", location_suffix="sdc",
        project_resource_group="spider-esml-project001-sdc-dev-001-rg",
        common_resource_group="spider-esml-common-sdc-dev-001", resource_group_prefix="spider-",
        resource_group_suffix="-001")
    infrastructure = OfflineInfrastructure.from_file(ROOT / "tests" / "fixtures" / "test-env-resources.json",
                                                     subscription_id=scope.subscription_id, tenant_id=scope.tenant_id)
else:
    if not (args.variables_json and args.environment and args.project):
        raise SystemExit("Pass --demo, or --variables-json, --environment and --project.")
    payload = naming.read_variables(deploy._bounded(Path(args.consumer_root or "."), args.variables_json))
    scope = naming.from_variables(payload, args.environment, args.project)
    infrastructure = AzureCliInfrastructure(scope.subscription_id)

mode = "deploy" if args.apply and not args.demo else "plan"
# 1. Composition root: one container per run; plan compositions get read-only proxies.
services = create_services(Settings(subscription_id=scope.subscription_id, tenant_id=scope.tenant_id,
                                    read_only=mode == "plan",
                                    definitions_dirs=tuple(Path(d) for d in args.definitions_dir)),
                           infrastructure=infrastructure)

# 2. Definitions: built in (project, common, agents) + consumer folders + one in code.
registry = services.get(DefinitionRegistry)
registry.add_document(DATA_PLATFORM, source="06_multiple_models.py")

# 3. Observer: react to planning and executed commands (dashboards, chat notifications, audit logs).
bus = services.get(EventBus)
bus.subscribe(ModelPlanned, lambda e: print(f"[event] planned {e.model}: {e.entities} entities"))
bus.subscribe(CommandExecuted, lambda e: print(f"[event] {e.description}"))

# 4. Facade: one call plans (or deploys) every model; nested models are ordered first.
report = services.get(HealthModelService).run(RunRequest(
    mode=mode, scope=scope, models=("project", "agents", "data-platform", "common"), work_root=ROOT,
    what_if=False))

for model in report["models"]:
    print(f"\n{model['definition']:>14}: {model['model']}  ({model['resourceGroup']})")
    print(f"{'':>16}{model['entities']} entities, {model['signals']} signals, layers {json.dumps(model['layers'])}")
    for write in model["writes"]:
        print(f"{'':>16}{'did' if model['azureWritesPerformed'] else 'would'}: {write}")
