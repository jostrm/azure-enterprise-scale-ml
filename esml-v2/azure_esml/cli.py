"""The same lake mapping and pipeline document for SDK v2 and CLI v2."""

import argparse
import json
from pathlib import Path
import sys

from ml_model_factory.config import load_json, write_json
from ml_model_factory.tags import assert_scope

from .domain_layer.contracts import PipelineRequest, PipelineType
from .domain_layer.project import ESMLProject


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    render = commands.add_parser("render", help="Generate a lake-connected pipeline without Azure writes")
    render.add_argument("--settings", required=True, type=Path)
    render.add_argument("--type", required=True, choices=[kind.value for kind in PipelineType])
    render.add_argument("--date", required=True, help="Explicit UTC data date, also supports historical partitions")
    render.add_argument("--run-id", required=True)
    render.add_argument("--data-version")
    render.add_argument("--snapshot-id")
    render.add_argument("--model-version")
    render.add_argument("--model-number", type=int)
    render.add_argument("--no-reuse", action="store_true")
    render.add_argument("--output", required=True, type=Path)
    for name in ("submit", "status", "connect-datastore"):
        command = commands.add_parser(name)
        command.add_argument("--settings", required=True, type=Path)
        command.add_argument("--backend", choices=("sdk", "cli"), default="sdk")
        command.add_argument("--credential", choices=("azure_cli", "managed_identity"), default="azure_cli")
        command.add_argument("--managed-identity-client-id")
        if name == "submit":
            command.add_argument("--pipeline", required=True, type=Path)
        if name == "status":
            command.add_argument("--job", required=True)
        if name == "connect-datastore":
            command.add_argument("--execute", action="store_true")
    compare = commands.add_parser("compare-models")
    compare.add_argument("--policy", type=Path, required=True)
    compare.add_argument("--candidate", type=Path, required=True)
    champion = compare.add_mutually_exclusive_group(required=True)
    champion.add_argument("--champion", type=Path)
    champion.add_argument("--no-champion", action="store_true")
    compare.add_argument("--output", type=Path, required=True)
    seed = commands.add_parser("lake-seed", help="Stage verified Kaggle master, shared silver, project IN and gold locally")
    for name in ("settings", "source-root", "scenario-root", "root"):
        seed.add_argument("--" + name, type=Path, required=True)
    seed.add_argument("--version", required=True)
    publish = commands.add_parser("lake-publish", help="Preview or explicitly publish the exact reviewed lake plan")
    publish.add_argument("--root", type=Path, required=True)
    publish.add_argument("--plan", type=Path, required=True)
    publish.add_argument("--tenant-id")
    publish.add_argument("--subscription-id", help="Bind CLI authentication to a verified subscription in the selected tenant")
    publish.add_argument("--execute", action="store_true")
    for name in ("shareback-silver", "resolve-silver"):
        command = commands.add_parser(name, help="Publish or resolve an exact producer/variation silver product in a local/mounted catalog")
        for field in ("settings", "request", "root", "output"):
            command.add_argument("--" + field, type=Path, required=True)
    return root


def _project(args):
    from .base_layer.azure_ml import AzureMLCLIBackend, AzureMLSDKBackend
    project = ESMLProject.from_json(args.settings)
    if args.backend == "cli":
        if args.credential != "azure_cli" or args.managed_identity_client_id:
            raise ValueError("CLI backend uses the explicitly signed-in Azure CLI identity; use SDK for managed identity")
        backend = AzureMLCLIBackend(project.target)
    elif args.credential == "managed_identity":
        backend = AzureMLSDKBackend.from_managed_identity(project.target, client_id=args.managed_identity_client_id)
    else:
        if args.managed_identity_client_id:
            raise ValueError("--managed-identity-client-id requires --credential managed_identity")
        backend = AzureMLSDKBackend.from_cli(project.target)
    return ESMLProject(project.settings, backend=backend)


def execute(args):
    if args.command in ("shareback-silver", "resolve-silver"):
        from .domain_layer.shareback import SilverShareback
        from .domain_layer.shared_lake import SharedLake
        settings = load_json(args.settings)
        catalog = SilverShareback(args.root, SharedLake(settings["aifactory"], settings["environment"],
                                                        settings.get("prefix", "mlops/v1")))
        request = load_json(args.request)
        allowed = ({"dataset", "producer_project", "variation", "version", "source_key", "table_relative",
                    "owner", "allowed_projects", "mode"} if args.command == "shareback-silver"
                   else {"dataset", "producer_project", "variation", "version", "consumer_project"})
        if set(request) - allowed:
            raise ValueError("Unsupported silver request fields")
        required = ({"dataset", "producer_project", "variation", "version", "source_key", "owner", "allowed_projects"}
                    if args.command == "shareback-silver" else allowed)
        if required - set(request):
            raise ValueError("Missing silver request fields: " + ", ".join(sorted(required - set(request))))
        result = catalog.publish(**request) if args.command == "shareback-silver" else catalog.resolve(**request)
        write_json(args.output, result)
        return result
    if args.command == "lake-seed":
        from .domain_layer.lake_seed import stage_kaggle_examples
        result = stage_kaggle_examples(load_json(args.settings), source_root=args.source_root,
                                      scenario_root=args.scenario_root, root=args.root, version=args.version)
        return {key: result[key] for key in ("state", "version", "samples", "azure_written")} | {
            "files": result["plan"]["files"], "bytes": result["plan"]["bytes"],
            "plan": str(args.root / "publication-plan.json"), "target": result["plan"]["target"],
        }
    if args.command == "lake-publish":
        from .domain_layer.lake_publication import publish
        plan = load_json(args.plan)
        if not args.execute:
            return plan
        if not args.tenant_id:
            raise ValueError("Explicit --tenant-id is required for lake publication")
        from uuid import UUID
        from azure.identity import AzureCliCredential
        tenant = str(UUID(args.tenant_id))
        if args.subscription_id:
            from ml_model_factory.project import azure_cli
            subscription = str(UUID(args.subscription_id))
            account = azure_cli("account", "show", "--subscription", subscription)
            if (str(account.get("id", "")).lower() != subscription
                    or str(account.get("tenantId", "")).lower() != tenant):
                raise ValueError("Selected subscription does not belong to the requested tenant")
            # Azure CLI rejects --tenant together with --subscription when acquiring a token.
            credential = AzureCliCredential(subscription=subscription, process_timeout=60)
        else:
            credential = AzureCliCredential(tenant_id=tenant, process_timeout=60)
        return publish(args.root, plan, credential=credential)
    if args.command == "render":
        project = ESMLProject.from_json(args.settings)
        request = PipelineRequest(args.date, args.run_id, args.data_version, args.snapshot_id,
                                  args.model_version, not args.no_reuse)
        plan = project.create_pipeline(PipelineType(args.type), request, output=args.output, model_number=args.model_number)
        return {"pipeline": str(plan.yaml_path), "experiment_name": plan.document["experiment_name"],
                "steps": len(plan.document["jobs"]), "cloud_submitted": False}
    if args.command == "compare-models":
        from ml_model_factory.selection import compare
        decision = compare(load_json(args.policy), load_json(args.candidate),
                           load_json(args.champion) if args.champion else None)
        write_json(args.output, decision)
        return decision
    if args.command == "connect-datastore" and not args.execute:
        project = ESMLProject.from_json(args.settings)
        return {"preview": True, "workspace": project.target.workspace_name,
                "storage": project.settings.storage, "credentials": "identity only",
                "changes": "Create missing AML datastore binding only; no storage/RBAC/network provisioning"}
    project = _project(args)
    if args.command == "connect-datastore":
        return project.connect_datastore()
    if args.command == "submit":
        import yaml
        document = yaml.safe_load(args.pipeline.read_text(encoding="utf-8"))
        return project.submit_document(document, args.pipeline.resolve().parent)
    if args.command == "status":
        job = project.backend.get_job(args.job)
        assert_scope(job.get("tags", {}), project.settings.scope)
        return job
    raise ValueError(f"Unknown command {args.command}")


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result = execute(args)
    except (ValueError, OSError, RuntimeError, ImportError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, allow_nan=False))
    return 2 if result.get("decision") == "blocked" else 0
