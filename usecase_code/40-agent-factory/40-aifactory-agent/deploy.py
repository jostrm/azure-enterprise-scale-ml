from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
from pathlib import Path
from urllib.parse import urlsplit

from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import BlobServiceClient

from aifactory_agent.config import credential, load_settings
from aifactory_agent.costs import DEFAULT_VARIABLES_RELATIVE_PATH, default_template_source
from aifactory_agent.knowledge import _excluded
from aifactory_agent.workloads import package_sources

BASE = Path(__file__).resolve().parent
IMAGE = "mcr.microsoft.com/azure-cli@sha256:e3768dde8142efa45d8f356a317aaac77abd7da15ba3719b0a150e9453f251db"


def az(*args):
    executable = shutil.which("az")
    if not executable:
        raise RuntimeError("Azure CLI is required.")
    response = subprocess.run([executable, *args, "--output", "json", "--only-show-errors"],
                              capture_output=True, text=True, check=True, timeout=900)
    return json.loads(response.stdout) if response.stdout.strip() else None


def resource_names(settings):
    return {
        "searchName": urlsplit(settings.azure.search_endpoint).hostname.split(".")[0],
        "storageName": urlsplit(settings.azure.storage_endpoint).hostname.split(".")[0],
        "storageContainer": settings.azure.storage_container,
        "foundryAccount": settings.azure.foundry_account,
        "foundryProject": settings.azure.foundry_project,
        "agentName": settings.agent_name,
        "agentInvocation": settings.agent_invocation,
    }


def graph_bundle(settings) -> dict | None:
    config = settings.dual_graph
    if config is None:
        return None
    if config.expected_snapshot_id is None:
        raise RuntimeError("Graph packaging requires an approved expected_snapshot_id pin.")
    from aifactory_agent.dual_graph import DualGraphStore, GraphError
    immutable = config.snapshot_root.name == config.expected_snapshot_id
    try:
        bundle = DualGraphStore(
            config.snapshot_root, expected_snapshot_id=config.expected_snapshot_id,
            repository_root=None if immutable else settings.knowledge.repository_root,
        ).export_snapshot()
    except (GraphError, OSError) as error:
        raise RuntimeError("Graph snapshot failed integrity validation; no bundle was created.") from error
    if not immutable and bundle["freshness"]["status"] != "fresh":
        raise RuntimeError("A moving graph root must be fresh; select a reviewed immutable snapshot explicitly.")
    return bundle


def package(settings, client_id: str, destination: Path) -> dict:
    wheels = BASE / ".build" / "wheels"
    if not wheels.exists() or not list(wheels.glob("*.whl")):
        raise RuntimeError("Download the locked Linux CPython 3.12 wheels before packaging.")
    root = settings.knowledge.repository_root
    graph = graph_bundle(settings)
    cloud = settings.model_dump(mode="json")
    cloud["azure"]["credential"] = "managed_identity"
    cloud["azure"]["managed_identity_client_id"] = client_id
    cloud["knowledge"]["repository_root"] = "/tmp/agent-app/repository"
    if graph is not None:
        cloud["dual_graph"].update(
            snapshot_root="/tmp/agent-app/dual_graph/snapshots/" + graph["snapshot_id"],
            expected_snapshot_id=graph["snapshot_id"], allow_source_access=False,
        )
    workload_sources = list(package_sources(settings))
    cloud["workloads"]["repository_root"] = "/tmp/agent-app/workload_sources"
    template, template_hash = default_template_source(root, settings.costs)
    if template.is_symlink() or template.stat().st_size > 2_000_000:
        raise RuntimeError("The approved cost template must be a bounded regular file.")
    with template.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != template_hash.lower():
            raise RuntimeError("The default cost template changed from its trusted SHA-256 pin.")
    cloud["costs"]["default_variables_path"] = DEFAULT_VARIABLES_RELATIVE_PATH.as_posix()
    cloud["costs"]["default_variables_sha256"] = template_hash.lower()
    if settings.azure.application_insights_name:
        scope = next(iter(settings.scopes.values()))
        monitoring = az("resource", "show", "--subscription", str(scope.subscription_id),
                        "--resource-group", scope.resource_group,
                        "--resource-type", "Microsoft.Insights/components",
                        "--name", settings.azure.application_insights_name,
                        "--api-version", "2020-02-02")
        cloud["azure"]["application_insights_connection_string"] = monitoring["properties"]["ConnectionString"]
    build = BASE / ".build"
    build.mkdir(exist_ok=True)
    config = build / "config.json"
    config.write_text(json.dumps(cloud, indent=2), encoding="utf-8")
    members = []
    def normalize(info):
        if "__pycache__" in info.name:
            return None
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        info.mtime = 0
        return info

    with destination.open("wb") as output, gzip.GzipFile(fileobj=output, mode="wb", mtime=0, filename="") as compressed, tarfile.open(fileobj=compressed, mode="w") as archive:
        for relative in ("aifactory_agent", "requirements.lock.txt"):
            archive.add(BASE / relative, arcname=relative, filter=normalize)
        archive.add(config, arcname="config.json", filter=normalize)
        if graph is not None:
            for relative, content in sorted(graph["files"].items()):
                entry = tarfile.TarInfo("dual_graph/snapshots/" + graph["snapshot_id"] + "/" + relative)
                entry.size = len(content)
                entry.mode = 0o444
                archive.addfile(normalize(entry), io.BytesIO(content))
        archive.add(wheels, arcname="wheels", filter=normalize)
        archive.add(BASE.parent / "agent_factory", arcname="shared/agent_factory",
                    filter=normalize)
        archive.add(root / "environment_setup" / "azurefactory-cli" / "src",
                    arcname="repository/environment_setup/azurefactory-cli/src",
                    filter=normalize)
        archive.add(template, arcname="repository/" + DEFAULT_VARIABLES_RELATIVE_PATH.as_posix(), filter=normalize)
        workload_directory = tarfile.TarInfo("workload_sources")
        workload_directory.type = tarfile.DIRTYPE
        workload_directory.mode = 0o755
        archive.addfile(workload_directory)
        for source, relative in workload_sources:
            archive.add(source, arcname=relative, recursive=False, filter=normalize)
        # Only the configured text corpus is packaged; never copy the checkout or .git.
        for pattern in settings.knowledge.includes:
            for path in root.glob(pattern):
                if not path.is_file() or path.is_symlink():
                    continue
                relative = path.relative_to(root).as_posix()
                if relative in members or _excluded(relative, settings):
                    continue
                if path.suffix.lower() not in {".md", ".py"}:
                    continue
                archive.add(path, arcname="repository/" + relative, filter=normalize)
                members.append(relative)
    with destination.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"sha256": digest, "source_files": len(members), "bytes": destination.stat().st_size}


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--config", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--app-name", default="aifactory-agent-project001-dev")
    parser.add_argument("--identity-name", default="mi-aifactory-agent-dev")
    parser.add_argument("--refresh-job-name", default="aifactory-agent-refresh-dev")
    parser.add_argument("--refresh-identity-name", default="mi-aifactory-agent-refresh-dev")
    parser.add_argument("--refresh-schedule", default="0 3 * * *")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = load_settings(args.config)
    scopes = list(settings.scopes.values())
    scope = scopes[0]
    if any(item.subscription_id != scope.subscription_id or item.resource_group != scope.resource_group
           for item in scopes):
        raise ValueError("One approved resource group per deployment is required.")
    if scope.environment != "dev":
        raise ValueError("This first deployment command is restricted to an approved DEV scope.")
    names = resource_names(settings)
    env = az("resource", "show", "--subscription", str(scope.subscription_id),
             "--resource-group", scope.resource_group, "--resource-type", "Microsoft.App/managedEnvironments",
             "--name", args.environment, "--api-version", "2025-01-01")
    if not env["properties"].get("vnetConfiguration", {}).get("internal"):
        raise ValueError("The existing Container Apps environment must be internal; public networking is not enabled by this deployment.")
    plan = {"resource_group": scope.resource_group, "subscription": str(scope.subscription_id),
            "additions": [args.identity_name, args.app_name, args.refresh_identity_name, args.refresh_job_name],
            "reuse": {"environment": args.environment, **names},
            "image": IMAGE, "network_changes": False,
            "identity_permissions": ["Search index data read", "Owned Blob container read/write",
                                    "OpenAI embeddings/inference",
                                    ("Invocation of the configured agent endpoint only" if settings.agent_invocation == "agent_endpoint"
                                     else "Foundry project Responses execution"),
                                    "Resource-group inventory read"],
            "refresh_job": {"schedule_utc": args.refresh_schedule, "source": "approved immutable repository snapshot",
                            "permissions": ["Search schema read/documents write", "Owned Blob state", "Embeddings"]},
            "entra_changes": False, "factory_api_host": False}
    if not args.apply:
        print(json.dumps(plan, indent=2))
        return
    common = ("--subscription", str(scope.subscription_id), "--resource-group", scope.resource_group)
    existing = az("resource", "list", *common)
    for item in existing:
        if item["name"] in {args.app_name, args.identity_name, args.refresh_job_name, args.refresh_identity_name}:
            if (item.get("tags") or {}).get("managed-by") != "enterprise-scale-ai-factory-agent":
                raise RuntimeError(f"Refusing to modify an existing unowned resource: {item['name']}.")
    identity = az("deployment", "group", "create", *common, "--name", "aifactory-agent-identity",
                  "--template-file", str(BASE / "infra" / "identity.bicep"),
                  "--parameters", f"location={settings.location}", f"identityName={args.identity_name}",
                  *(f"{key}={value}" for key, value in names.items()))
    client_id = identity["properties"]["outputs"]["clientId"]["value"]
    bundle = BASE / ".build" / "agent-bundle.tar.gz"
    result = package(settings, client_id, bundle)
    blob_name = f"deployments/{result['sha256']}/agent-bundle.tar.gz"
    with BlobServiceClient(settings.azure.storage_endpoint, credential(settings)) as blobs:
        target = blobs.get_blob_client(settings.azure.storage_container, blob_name)
        try:
            existing_bundle = target.get_blob_properties()
        except ResourceNotFoundError:
            with bundle.open("rb") as stream:
                target.upload_blob(stream, overwrite=False,
                                   metadata={"sha256": result["sha256"], "owner": "aifactory-agent"})
        else:
            if (existing_bundle.metadata.get("sha256") != result["sha256"]
                    or existing_bundle.size != result["bytes"]):
                raise RuntimeError("An existing immutable deployment bundle has conflicting metadata.")
    parameters = {
        "location": settings.location, "appName": args.app_name,
        "environmentName": args.environment, "identityName": args.identity_name,
        "image": IMAGE, "storageAccount": names["storageName"],
        "storageContainer": names["storageContainer"], "bundleBlob": blob_name,
        "bundleSha256": result["sha256"],
        "bootstrapCommand": (BASE / "infra" / "bootstrap.sh").read_text(encoding="utf-8"),
    }
    parameter_file = BASE / ".build" / "app.parameters.json"
    parameter_file.write_text(json.dumps({
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
        "contentVersion": "1.0.0.0", "parameters": {key: {"value": value} for key, value in parameters.items()},
    }), encoding="utf-8")
    deployed = az("deployment", "group", "create", *common, "--name", "aifactory-agent-app",
                  "--template-file", str(BASE / "infra" / "application.bicep"),
                  "--parameters", "@" + str(parameter_file))
    refresh_parameters = {
        "location": settings.location, "jobName": args.refresh_job_name,
        "environmentName": args.environment, "identityName": args.refresh_identity_name,
        "image": IMAGE, "searchName": names["searchName"], "foundryAccount": names["foundryAccount"],
        "storageAccount": names["storageName"], "storageContainer": names["storageContainer"],
        "bundleBlob": blob_name, "bundleSha256": result["sha256"],
        "bootstrapCommand": parameters["bootstrapCommand"], "schedule": args.refresh_schedule,
    }
    refresh_file = BASE / ".build" / "refresh.parameters.json"
    refresh_file.write_text(json.dumps({
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
        "contentVersion": "1.0.0.0", "parameters": {key: {"value": value} for key, value in refresh_parameters.items()},
    }), encoding="utf-8")
    refresh = az("deployment", "group", "create", *common, "--name", "aifactory-agent-refresh",
                 "--template-file", str(BASE / "infra" / "refresh.bicep"),
                 "--parameters", "@" + str(refresh_file))
    print(json.dumps({"plan": plan, "bundle": result, "deployment_state": deployed["properties"]["provisioningState"],
                      "outputs": deployed["properties"]["outputs"],
                      "refresh_job_outputs": refresh["properties"]["outputs"]}, indent=2))


if __name__ == "__main__":
    main()
