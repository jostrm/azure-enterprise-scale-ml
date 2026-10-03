"""Use case 4 - AI triage of the current health with a Foundry model (e.g. GPT 6.1 Sol).

Reads the health summary, open alerts and recent transitions, and asks a model deployment
in the project's own Foundry account for a short triage note. Advisory only: nothing is changed.
The Foundry account of an AI Factory is private, so run this inside the factory network
(VPN, jump host, Container App). The caller needs Azure AI User or Cognitive Services OpenAI User.

    python 04_ai_triage.py --model-id <id> --foundry-endpoint https://<account>.openai.azure.com \
        --deployment aifactory-agent-gpt-6-1-sol
"""
import argparse

from _common import add_model_arguments, client_from
from aifactory_healthmodel.triage import triage

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
add_model_arguments(parser)
parser.add_argument("--foundry-endpoint", required=True)
parser.add_argument("--deployment", default="aifactory-agent-gpt-6-1-sol")
args = parser.parse_args()
client = client_from(args)

summary = client.summary()
alerts = client.alerts(hours=24)
histories = {p["name"]: client.history(p["name"], hours=24) for p in summary["problems"][:5]}
print(f"{summary['root']['displayName']}: {summary['root']['state']} "
      f"({len(summary['problems'])} problem(s), {len(alerts)} alert(s) in 24 h)\n")
print(triage(summary, alerts, histories, endpoint=args.foundry_endpoint, deployment=args.deployment))
