"""add-aifactory-agent-chat --to-project NNN: deploy or update the AI Factory Agent chat for one project from a terminal.

ADO-azurefactory.sh and GHA-azurefactory.sh forward here through lib/layout_router.sh. The only customer-specific input is
configuration: the project's own variables file (registered layout: azurefactory/factories/*/scalesets/*/projects/
projectNNN/variables.json; legacy layout: aifactory/variables.json) and, optionally, the agent configuration it names in
aifactoryAgentConfigFile. Its Dev section is mapped to the project pipeline variable names, and the same two launchers as
the project pipeline run with the signed-in Azure CLI identity: 46-factory-chat-agent (the Foundry Agent), then
47-aifactory-agent-live-voice (the private chat application with voice). Plan is the default and only reads Azure.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

USAGE = ("Usage: <ADO|GHA>-azurefactory.sh add-aifactory-agent-chat --to-project <NNN> [--environment dev] "
         "[--consumer-root <repo>] [--config <variables.json>] [--agent-config <agent.json>] [--without-voice] [--apply]")
SUBMODULE = "azure-enterprise-scale-ml"
AGENT_FACTORY = Path("usecase_code/40-agent-factory")
PROJECT = re.compile(r"^\d{1,3}$")
REQUIRED_FOR_VOICE = ("aifactoryAgentEntraAppId", "aifactoryAgentReaderObjectIds")


class UsageError(ValueError):
    """Invalid invocation: nothing has run."""


def parse(arguments: list[str]) -> dict:
    options = {"environment": "dev", "consumer_root": os.getcwd(), "config": "", "agent_config": None,
               "voice": True, "apply": False, "project": ""}
    # -toProject is the short form that matches the -addAIFactoryAgentChat action alias.
    values = {"--to-project": "project", "-toProject": "project", "--environment": "environment",
              "--consumer-root": "consumer_root", "--config": "config", "--agent-config": "agent_config"}
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in values:
            if index + 1 >= len(arguments) or arguments[index + 1].startswith("--"):
                raise UsageError(f"{argument} requires a value." if argument != "--to-project"
                                 else "--to-project is required (a 3-digit project number such as 001).")
            options[values[argument]] = arguments[index + 1]
            index += 2
            continue
        if argument == "--apply":
            options["apply"] = True
        elif argument == "--without-voice":
            options["voice"] = False
        else:
            raise UsageError(f"Unsupported argument: {argument}. {USAGE}")
        index += 1
    if not options["project"]:
        raise UsageError("--to-project is required (a 3-digit project number such as 001).")
    if not PROJECT.fullmatch(options["project"]) or int(options["project"]) == 0:
        raise UsageError(f"--to-project must be a 3-digit project number such as 001 (got '{options['project']}').")
    options["project"] = options["project"].zfill(3)
    if options["environment"] != "dev":
        raise UsageError("add-aifactory-agent-chat supports Dev only: the agent application is restricted to the Dev scope.")
    return options


def resolve_configuration(root: Path, project: str, explicit: str) -> Path:
    if explicit:
        path = Path(explicit) if Path(explicit).is_absolute() else root / explicit
        if not path.is_file():
            raise UsageError(f"--config file not found: {explicit}")
        return path
    matches = sorted(root.glob(f"azurefactory/factories/*/scalesets/*/projects/project{project}/variables.json"))
    if len(matches) > 1:
        raise UsageError(f"project{project} has {len(matches)} variables files under azurefactory/factories; "
                         "pass --config with the one to use.")
    if matches:
        return matches[0]
    legacy = root / "aifactory/variables.json"
    if legacy.is_file():
        return legacy
    raise UsageError(f"No variables file found for project{project}; pass --config <variables.json>.")


def display(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def pipeline_values(path: Path, root: Path, options: dict) -> dict:
    shown = display(path, root)
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError:
        raise UsageError(f"{shown} is not valid JSON.") from None
    section = document.get("dev", document) if isinstance(document, dict) else None
    if not isinstance(section, dict):
        raise UsageError(f"{shown} has no Dev configuration section.")
    values = {key: ("true" if value else "false") if isinstance(value, bool) else str(value)
              for key, value in section.items() if isinstance(value, (str, int, float, bool))}
    found = values.get("project_number_000", "").strip().zfill(3)
    if found != options["project"]:
        raise UsageError(f"{shown}: project_number_000 is {found or '(missing)'}, not {options['project']}. "
                         "Pass --config with that project's own variables file.")
    values.update({
        "dev_test_prod": "dev", "dev_test_prod_sub_id": values.get("dev_sub_id", ""),
        "project_number_000": options["project"],
        "enableFactoryChatAgent": "true", "enableAIFactoryAgentLiveVoice": "true" if options["voice"] else "false",
        "deleteAllForProject": "false", "deleteAllServicesForProject": "false",
        "BUILD_SOURCESDIRECTORY": str(root),
    })
    if options["agent_config"] is not None:
        values["aifactoryAgentConfigFile"] = options["agent_config"]
    if options["voice"]:
        missing = [name for name in REQUIRED_FOR_VOICE if not values.get(name, "").strip()]
        if missing:
            raise UsageError(f"Add {', '.join(missing)} to the dev section of {shown} (or run with --without-voice).")
    return values


def launcher(root: Path, folder: str):
    for base in (root / SUBMODULE, Path(__file__).resolve().parents[2]):
        path = base / AGENT_FACTORY / folder / "deploy.py"
        if path.is_file():
            spec = importlib.util.spec_from_file_location(f"aifactory_{folder.replace('-', '_')}", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module.run
    raise UsageError(f"The accelerator launcher {AGENT_FACTORY / folder / 'deploy.py'} is missing; update the submodule.")


def main(argv=None, chat_runner=None, voice_runner=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    provider = argv.pop(0) if argv and argv[0] in ("ado", "gha") else "ado"
    if any(item in ("--help", "-h") for item in argv):
        print(USAGE, file=sys.stderr)
        return 0
    try:
        options = parse(argv)
        root = Path(options["consumer_root"]).resolve()
        path = resolve_configuration(root, options["project"], options["config"])
        values = pipeline_values(path, root, options)
        chat_runner = chat_runner or launcher(root, "46-factory-chat-agent")
        if options["voice"]:
            voice_runner = voice_runner or launcher(root, "47-aifactory-agent-live-voice")
    except UsageError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    environ = {**os.environ, **values}
    command = SimpleNamespace(command="apply" if options["apply"] else "plan", apply=options["apply"])
    steps = {}
    try:
        steps["factory_chat_agent"] = chat_runner(command, environ)
        if options["voice"]:
            steps["agent_chat_application"] = voice_runner(command, environ)
    except (ValueError, RuntimeError) as error:
        print(f"AI Factory Agent chat error: {error}", file=sys.stderr)
        return 1
    print(json.dumps({
        "action": "add-aifactory-agent-chat", "orchestrator": provider, "project": options["project"],
        "environment": options["environment"], "configuration": display(path, root),
        "mode": command.command, "mutations": options["apply"], "voice": options["voice"], "steps": steps,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
