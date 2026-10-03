"""Use case 1 - read health: workload state, failing signals and their recent history.

    python 01_read_health.py --subscription <sub> --resource-group <project-rg> --name hm-<prefix>prj001-<loc>-dev-001
"""
import argparse

from _common import add_model_arguments, client_from

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
add_model_arguments(parser)
parser.add_argument("--hours", type=float, default=24, help="History window for failing signals.")
args = parser.parse_args()
client = client_from(args)

summary = client.summary()
root = summary["root"]
print(f"{root['displayName']}: {root['state']}")
for layer in summary["layers"]:
    print(f"  - {layer['displayName']}: {layer['state']}")

# Drill down: why is something degraded or unhealthy, and since when?
for problem in summary["problems"]:
    print(f"\n{problem['state']}: {' > '.join(problem['path'])}")
    transitions = client.history(problem["name"], hours=args.hours)
    if transitions:
        last = transitions[0]
        print(f"  state changed {last['previousState']} -> {last['newState']} at {last['occurredAt']}")
    for signal in problem["signals"]:
        print(f"  signal {signal['displayName']}: {signal['state']} (value {signal['value']})")
        if signal["name"] == "resource-health":
            continue
        points = client.signal_history(problem["name"], signal["name"], hours=args.hours)
        values = [p.get("value") for p in points if p.get("value") is not None]
        if values:
            print(f"    last {len(values)} values: min {min(values)}, max {max(values)}")

print(f"\nEntities without data: {len(summary['unknown'])}; signal errors: {len(summary['signalErrors'])}")
for hint in summary["hints"]:
    print(f"Hint: {hint}")

# Deployments and incidents annotated on the timeline (see use case 3).
for annotation in client.annotations("root", hours=args.hours):
    print(f"Annotation {annotation.get('createdAt')}: {annotation.get('description')}")
