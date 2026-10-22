"""S09: show per-folder ADLS Gen2 ACLs through Storage, AI Search and a Foundry agent (synthetic data only)."""
import argparse
import base64
import json
from pathlib import Path

import main as common
from agent_factory.cli import write_json
from agent_factory.discovery import discover
from sales_demo.acl_scenario import AclScenario, load_scenario, reader_condition
from sales_demo.configuration import load_config, read_json
from sales_demo.identity import SEARCH, STORAGE, AzureCliTokenProvider

USER_COMMANDS = {"whoami", "storage-check", "search", "retrieve", "ask"}


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("command", choices=["plan", "condition", "root-acl", "publish", "configure", "deploy",
                                            *sorted(USER_COMMANDS)])
    result.add_argument("--config", type=Path, required=True)
    result.add_argument("--scenario", type=Path, required=True, help="Consumer S09 approval and identities (JSON).")
    result.add_argument("--profile", type=Path,
                        help="AZURE_CONFIG_DIR of the separately signed-in end user; omit for the operator.")
    result.add_argument("--input", default="List every document you can find with its access marker.")
    result.add_argument("--apply", action="store_true")
    result.add_argument("--allow-paid", action="store_true")
    result.add_argument("--output", type=Path)
    return result


def who(token):
    """Display-only claims; Storage and Search validate the token themselves."""
    payload = token.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    return {"upn": claims.get("upn") or claims.get("preferred_username") or claims.get("unique_name"),
            "oid": claims.get("oid")}


def run(args):
    config = load_config(args.config)
    scenario = AclScenario(config, load_scenario(read_json(args.scenario)), None, None)
    if args.command == "plan":
        return {**scenario.plan, "search_reader_condition": reader_condition(scenario.plan)}
    if args.command == "condition":
        return {"search_identity": config["search_identity_object_id"], "role": "Storage Blob Data Reader",
                "scope_container": config["container"], "condition": reader_condition(scenario.plan)}
    session, factory = common.operator(config)
    scenario.session = session
    if args.command == "root-acl":
        acl = scenario.storage().root_acl()
        return {"root_acl": acl, "required_change": scenario.root_acl_change(acl)}
    if args.command in {"configure", "deploy", "ask"}:
        scenario.target = discover(factory, session)
    if args.command == "publish":
        return scenario.publish(apply=args.apply, root_acl=scenario.storage().root_acl())
    if args.command == "configure":
        return scenario.configure(apply=args.apply)
    if args.command == "deploy":
        return scenario.deploy(apply=args.apply)
    user = AzureCliTokenProvider(config["tenant_id"], config["subscription_id"], config_dir=args.profile)
    search_token = user.token(SEARCH)
    identity = who(search_token)
    if args.command == "whoami":
        return identity
    if args.command == "storage-check":
        result = scenario.storage_check(scenario.storage(user))
    elif args.command == "search":
        result = scenario.search(search_token)
    elif args.command == "retrieve":
        result = scenario.retrieve(search_token, args.input)
    else:
        result = scenario.ask(search_token, args.input, allow_paid=args.allow_paid)
    expected = scenario.plan["expected_access"].get(identity["oid"])
    return {"identity": identity, "result": result, "expected_titles": expected}


if __name__ == "__main__":
    arguments = parser().parse_args()
    output = run(arguments)
    if arguments.output:
        write_json(common.external_output(arguments.output), output)
    print(json.dumps(output, indent=2, ensure_ascii=False))
