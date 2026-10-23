"""Late project-pipeline step for the opt-in live voice of the AI Factory Agent chat application (any project, Dev).

Reads the pipeline variables by their exact names from the environment, validates them offline, and then plans
(Azure GET only) or applies (the agent's own ownership-checked operator commands). Disabled flags and Stage/Prod
runs exit cleanly without contacting Azure; invalid combinations fail instead of being ignored.

aifactoryAgentConfigFile optionally names the customer's own agent configuration, a JSON file relative to the consumer
checkout (BUILD_SOURCESDIRECTORY in Azure DevOps, GITHUB_WORKSPACE in GitHub Actions).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_factory.agent_live_voice import (  # noqa: E402
    LiveVoiceIntegration, LiveVoiceRequest, decide, subprocess_runner)
from agent_factory.azure import AzureSession  # noqa: E402

INPUTS = (
    "enableFactoryChatAgent", "enableAIFactoryAgentLiveVoice",
    "enableContainerApps", "enableAIFoundry", "enableAISearch", "deleteAllServicesForProject", "deleteAllForProject",
    "dev_test_prod_sub_id", "tenantId", "dev_test_prod", "project_number_000", "admin_location",
    "admin_aifactoryPrefixRG", "projectPrefix", "admin_locationSuffix", "admin_aifactorySuffixRG",
    "projectSuffix", "projectResourceGroup", "modelGPTXName", "aifactoryAgentEntraAppId",
    "aifactoryAgentContainerAppsEnvironment", "aifactoryAgentReaderObjectIds", "aifactoryAgentVoiceName",
    "aifactoryAgentVoiceLanguages", "aifactoryAgentConfigFile", "aifactoryAgentModelDeployment",
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def work_directory(environ) -> Path:
    """Generated configuration and the isolated virtual environment live outside the repository checkout."""
    base = environ.get("RUNNER_TEMP") or environ.get("AGENT_TEMPDIRECTORY") or tempfile.gettempdir()
    return Path(base) / "aifactory-agent-live-voice"


def consumer_root(environ) -> Path:
    """The consumer checkout that contains this accelerator as its azure-enterprise-scale-ml submodule."""
    for name in ("BUILD_SOURCESDIRECTORY", "GITHUB_WORKSPACE"):
        if environ.get(name):
            return Path(environ[name])
    return REPOSITORY_ROOT.parent


def load_customer_configuration(relative: str, root: Path) -> dict:
    base = root.resolve()
    path = (base / relative).resolve()
    if not path.is_relative_to(base):
        raise ValueError(f"aifactoryAgentConfigFile must point inside the repository checkout: {relative}")
    if not path.is_file():
        raise ValueError(f"aifactoryAgentConfigFile not found in the repository checkout: {relative}")
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError:
        raise ValueError(f"aifactoryAgentConfigFile is not valid JSON: {relative}") from None
    if not isinstance(document, dict):
        raise ValueError(f"aifactoryAgentConfigFile must contain a JSON object: {relative}")
    return document


def run(args, environ=os.environ, session_factory=AzureSession, runner=subprocess_runner) -> dict:
    request = LiveVoiceRequest.from_values({name: environ.get(name) for name in INPUTS})
    if request.enable_live_voice and request.config_file:
        request = replace(request, config_overlay=load_customer_configuration(request.config_file, consumer_root(environ)))
    decision = decide(request)
    if args.command == "apply" and not args.apply:
        raise ValueError("apply requires --apply.")
    if not decision.act:
        return {"mode": "skipped", "reason": decision.reason, "mutations": False}
    if args.command == "validate":
        return {"mode": "validated", "reason": decision.reason, "voice": decision.voice, "mutations": False}
    session = session_factory(request.subscription_id, request.tenant_id)
    engine = LiveVoiceIntegration(session, runner, work_dir=work_directory(environ), repository_root=REPOSITORY_ROOT)
    return engine.run(request, apply=args.command == "apply")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate", "plan", "apply"])
    parser.add_argument("--apply", action="store_true", help="Required with apply; plan and validate never write.")
    try:
        result = run(parser.parse_args())
    except (ValueError, RuntimeError) as error:
        print(f"AI Factory Agent live voice configuration error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
