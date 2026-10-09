"""Shared helpers for the use case examples (model identification and authentication)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aifactory_healthmodel.bootstrap import runtime_transport  # noqa: E402
from aifactory_healthmodel.client import HealthModelClient  # noqa: E402


def add_model_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model-id", help="Health model resource ID.")
    parser.add_argument("--subscription")
    parser.add_argument("--resource-group")
    parser.add_argument("--name", help="Health model name, e.g. hm-spider-prj001-sdc-dev-001.")
    parser.add_argument("--auth", choices=("cli", "identity"), default="cli",
                        help="cli = signed-in Azure CLI; identity = azure-identity DefaultAzureCredential "
                             "(managed identity in Container Apps, Functions or AKS).")


def client_from(args, read_only: bool = False) -> HealthModelClient:
    """Client over a resilient transport (retry + circuit breaker); read_only blocks every write."""
    transport = runtime_transport(args.auth, read_only=read_only)
    if args.model_id:
        return HealthModelClient(args.model_id, transport)
    if not (args.subscription and args.resource_group and args.name):
        raise SystemExit("Pass --model-id, or --subscription, --resource-group and --name.")
    return HealthModelClient.from_names(args.subscription, args.resource_group, args.name, transport)
