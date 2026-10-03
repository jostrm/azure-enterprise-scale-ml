"""aif-healthmodel: deploy AI Factory health models and operate them.

  plan | deploy                     model lifecycle (see deploy.py)
  status                            root/layer health, failing signals, entities without data
  alerts | alert-state              read health-state alerts, acknowledge or close them
  history                           entity state transitions or one signal's values
  report                            ingest an externally evaluated signal (probe, smoke test)
  annotate                          add a timeline annotation (deployment, incident, change)
  set-alert                         change an entity's health-state alert severity/action groups
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import deploy, naming
from .azure import AzCliTransport, TokenTransport
from .catalog import HEALTH_STATES, SEVERITIES
from .client import ALERT_STATES, HealthModelClient

LIFECYCLE = ("plan", "deploy")
FAIL_ORDER = {"Degraded": 1, "Unhealthy": 2}


def make_transport(auth: str):
    if auth == "identity":
        try:
            from azure.identity import DefaultAzureCredential
        except ImportError:
            raise RuntimeError("--auth identity requires the azure-identity package.") from None
        return TokenTransport(DefaultAzureCredential())
    return AzCliTransport()


def model_id_from(args) -> str:
    if args.model_id:
        return args.model_id
    if args.subscription and args.resource_group and args.name:
        return (f"/subscriptions/{args.subscription}/resourceGroups/{args.resource_group}"
                f"/providers/Microsoft.CloudHealth/healthmodels/{args.name}")
    if args.variables_json and args.environment and args.project:
        payload = naming.read_variables(deploy._bounded(Path(args.consumer_root or os.getcwd()), args.variables_json))
        scope = naming.from_variables(payload, args.environment, args.project)
        group = scope.project_resource_group if args.scope == "project" else scope.common_resource_group
        return (f"/subscriptions/{scope.subscription_id}/resourceGroups/{group}"
                f"/providers/Microsoft.CloudHealth/healthmodels/{scope.model_name(args.scope)}")
    raise ValueError("Identify the model with --model-id, with --subscription/--resource-group/--name, "
                     "or with --variables-json/--environment/--project [--scope].")


def print_status(summary: dict) -> None:
    root = summary["root"]
    print(f"{root['displayName']}  [{root['state']}]")
    for layer in summary["layers"]:
        print(f"  {layer['displayName']}  [{layer['state']}]")
    if summary["problems"]:
        print(f"\nProblems ({len(summary['problems'])}):")
        for problem in summary["problems"]:
            print(f"  {problem['state']:<10} {problem['displayName']}")
            print(f"             {' > '.join(problem['path'])}")
            for signal in problem["signals"]:
                value = "" if signal.get("value") is None else f", value {signal['value']}"
                print(f"             - {signal['displayName']} ({signal['name']}): {signal['state']}{value}"
                      f" at {signal.get('reportedAt') or 'n/a'}")
    if summary["unknown"]:
        print("\nNo data (Unknown): " + ", ".join(item["displayName"] for item in summary["unknown"]))
    if summary.get("signalErrors"):
        print(f"\nSignal errors ({len(summary['signalErrors'])}):")
        for item in summary["signalErrors"][:10]:
            print(f"  {item['displayName']} / {item['signal']}: {item['error'][:160]}")
    for hint in summary.get("hints", []):
        print(f"\nHint: {hint}")
    counts = ", ".join(f"{state} {count}" for state, count in sorted(summary["counts"].items()))
    print(f"\nEntities: {counts}")


def _status(client, args) -> int:
    summary = client.summary()
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print_status(summary)
    if args.fail_on and FAIL_ORDER.get(summary["root"]["state"], 0) >= FAIL_ORDER[args.fail_on]:
        return 3
    return 0


def _alerts(client, args) -> int:
    alerts = client.alerts(hours=args.hours, state=args.state)
    if args.json:
        print(json.dumps(alerts, indent=2))
    else:
        for alert in alerts:
            print(f"{alert['severity']}  {alert['state']:<12} {alert['condition'] or '':<9} {alert['firedAt']}  "
                  f"{alert['entity']}  {alert['name']}\n      {alert['id']}")
        print(f"{len(alerts)} health model alert(s) in the last {args.hours} hour(s).")
    return 0


def _history(client, args) -> int:
    rows = (client.signal_history(args.entity, args.signal, hours=args.hours) if args.signal
            else client.history(args.entity, hours=args.hours))
    print(json.dumps(rows, indent=2))
    return 0


def _report(client, args) -> int:
    kwargs = {"expires_in_minutes": args.expires}
    if args.value is not None:
        kwargs = {"value": args.value, **kwargs}
    if args.context:
        kwargs["context"] = args.context
    client.ingest_health_report(args.entity, args.signal, args.state, **kwargs)
    print(f"Reported {args.signal}={args.state} on {args.entity} (expires in {args.expires} minutes).")
    return 0


def _annotate(client, args) -> int:
    details = {}
    for item in args.detail:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise ValueError(f"--detail must be key=value, got {item!r}.")
        details[key] = value
    print(json.dumps(client.add_annotation(args.entity, details, args.description), indent=2))
    return 0


def _set_alert(client, args) -> int:
    if args.unhealthy is None and args.degraded is None:
        raise ValueError("Pass --unhealthy and/or --degraded (a severity Sev0-Sev4, or off).")
    changes = {}
    for key in ("unhealthy", "degraded"):
        value = getattr(args, key)
        if value is None:
            continue
        if value == "off":
            changes[key] = None
            continue
        config = {"severity": value}
        if args.action_group_id:
            config["actionGroupIds"] = list(args.action_group_id)
        if args.description:
            config["description"] = args.description
        changes[key] = config
    client.set_entity_alerts(args.entity, **changes)
    print(f"Updated health-state alerts on {args.entity}: {json.dumps(changes)}")
    return 0


def _alert_state(client, args) -> int:
    client.change_alert_state(args.alert_id, args.state, args.comment)
    print(f"Alert set to {args.state}.")
    return 0


HANDLERS = {"status": _status, "alerts": _alerts, "history": _history, "report": _report,
            "annotate": _annotate, "set-alert": _set_alert, "alert-state": _alert_state}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aif-healthmodel", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in LIFECYCLE:
        commands.add_parser(name, help=f"{name} the health model(s); see '{name} --help'.", add_help=False)

    def runtime(name, help_text):
        sub = commands.add_parser(name, help=help_text)
        group = sub.add_argument_group("model")
        group.add_argument("--model-id")
        group.add_argument("--subscription")
        group.add_argument("--resource-group")
        group.add_argument("--name")
        group.add_argument("--consumer-root")
        group.add_argument("--variables-json")
        group.add_argument("--environment", choices=sorted(naming.ENVIRONMENTS))
        group.add_argument("--project")
        group.add_argument("--scope", choices=("project", "common"), default="project")
        sub.add_argument("--auth", choices=("cli", "identity"), default="cli",
                         help="cli = signed-in Azure CLI; identity = azure-identity DefaultAzureCredential.")
        return sub

    status = runtime("status", "Current health with failing signals.")
    status.add_argument("--json", action="store_true")
    status.add_argument("--fail-on", choices=sorted(FAIL_ORDER), help="Exit 3 when the root is at least this bad.")
    alerts = runtime("alerts", "Health-state alerts fired by the model.")
    alerts.add_argument("--hours", type=int, default=24, choices=(1, 24, 168, 720))
    alerts.add_argument("--state", choices=ALERT_STATES)
    alerts.add_argument("--json", action="store_true")
    history = runtime("history", "Entity state transitions, or one signal's history.")
    history.add_argument("--entity", default="root")
    history.add_argument("--signal")
    history.add_argument("--hours", type=float, default=24)
    report = runtime("report", "Ingest an externally evaluated signal.")
    report.add_argument("--entity", default="root")
    report.add_argument("--signal", required=True)
    report.add_argument("--state", required=True, choices=HEALTH_STATES)
    report.add_argument("--value", type=float)
    report.add_argument("--expires", type=int, default=60, help="Minutes until the report expires (1-10080).")
    report.add_argument("--context")
    annotate = runtime("annotate", "Add a data annotation to the health timeline.")
    annotate.add_argument("--entity", default="root")
    annotate.add_argument("--detail", action="append", required=True, help="key=value (repeat, max 10).")
    annotate.add_argument("--description")
    set_alert = runtime("set-alert", "Change an entity's health-state alerts.")
    set_alert.add_argument("--entity", required=True)
    set_alert.add_argument("--unhealthy", choices=(*SEVERITIES, "off"))
    set_alert.add_argument("--degraded", choices=(*SEVERITIES, "off"))
    set_alert.add_argument("--action-group-id", action="append", default=[])
    set_alert.add_argument("--description")
    alert_state = runtime("alert-state", "Acknowledge, close or reopen an alert.")
    alert_state.add_argument("--alert-id", required=True)
    alert_state.add_argument("--state", required=True, choices=ALERT_STATES)
    alert_state.add_argument("--comment")
    return parser


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in LIFECYCLE:
        return deploy.main(argv)
    try:
        args = build_parser().parse_args(argv)
        client = HealthModelClient(model_id_from(args), make_transport(args.auth))
        return HANDLERS[args.command](client, args)
    except (ValueError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
