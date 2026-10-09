"""Use case 2 - read and manage health-state alerts.

Reading is always safe. Changing alert configuration or alert state needs --apply.

    # list alerts of the last 7 days
    python 02_alerts.py --model-id <id> --hours 168
    # acknowledge one alert
    python 02_alerts.py --model-id <id> --acknowledge <alert-id> --apply
    # alert the Generative AI layer as Sev1 on Unhealthy and Sev3 on Degraded, notifying an action group
    python 02_alerts.py --model-id <id> --entity layer-genai --unhealthy Sev1 --degraded Sev3 \
        --action-group-id /subscriptions/<sub>/resourceGroups/<rg>/providers/microsoft.insights/actionGroups/<ag> --apply

Defaults deployed by bicep/main.bicep (alertPolicy): root Unhealthy Sev1, root Degraded Sev3,
each layer Unhealthy Sev2, no per-resource alerts. Change them for every model with the
--alert-policy file of 'aif_healthmodel.py deploy', or per entity at runtime as shown here.
"""
import argparse

from _common import add_model_arguments, client_from

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
add_model_arguments(parser)
parser.add_argument("--hours", type=int, default=24, choices=(1, 24, 168, 720))
parser.add_argument("--acknowledge", metavar="ALERT_ID")
parser.add_argument("--close", metavar="ALERT_ID")
parser.add_argument("--entity", help="Entity whose alert configuration to change (e.g. layer-genai or root).")
parser.add_argument("--unhealthy", help="Severity Sev0-Sev4, or off.")
parser.add_argument("--degraded", help="Severity Sev0-Sev4, or off.")
parser.add_argument("--action-group-id", action="append", default=[])
parser.add_argument("--apply", action="store_true", help="Perform the change (otherwise print what would change).")
args = parser.parse_args()
client = client_from(args)

# 1. Read alerts fired by the health model (Azure Monitor alerts, monitorService 'Health Model').
alerts = client.alerts(hours=args.hours)
for alert in alerts:
    print(f"{alert['severity']} {alert['state']:<12} {alert['condition']:<9} {alert['firedAt']} "
          f"{alert['entityDisplayName'] or alert['entity']}")
    print(f"   {alert['id']}")
    if alert.get("timeline"):
        print(f"   timeline: {alert['timeline']}")
print(f"{len(alerts)} alert(s); open: {sum(1 for a in alerts if a['condition'] == 'Fired')}")

# 2. Acknowledge or close an alert (the alert resolves by itself when the entity recovers).
for alert_id, state in ((args.acknowledge, "Acknowledged"), (args.close, "Closed")):
    if alert_id:
        if args.apply:
            client.change_alert_state(alert_id, state, comment="Updated by AI Factory health model use case 2")
            print(f"{state}: {alert_id}")
        else:
            print(f"Would set {alert_id} to {state} (add --apply).")

# 3. Configure alerts on one entity (read-modify-write that keeps its signals untouched).
if args.entity and (args.unhealthy or args.degraded):
    changes = {}
    for key in ("unhealthy", "degraded"):
        value = getattr(args, key)
        if value:
            # Only the given fields change; existing action groups are kept unless replaced.
            config = {"severity": value}
            if args.action_group_id:
                config["actionGroupIds"] = args.action_group_id
            changes[key] = None if value == "off" else config
    if args.apply:
        client.set_entity_alerts(args.entity, **changes)
        print(f"Alerts on {args.entity}: {client.entity(args.entity)['properties'].get('alerts')}")
    else:
        print(f"Would set alerts on {args.entity}: {changes} (add --apply).")
