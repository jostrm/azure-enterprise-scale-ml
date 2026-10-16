"""Plan/deploy a synthetic multi-index Playground experiment without a calculator."""
import argparse
import json
from pathlib import Path

import main as common
from agent_factory.cli import write_json
from agent_factory.discovery import discover
from sales_demo.configuration import load_config, read_json
from sales_demo.retrieval_experiment import Experiment, build_documents, definitions, instructions, whole_table_documents


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("command", choices=["plan", "configure", "verify", "probe", "deploy", "ask", "full-text-sum"])
    result.add_argument("--config", type=Path, required=True)
    result.add_argument("--apply", action="store_true")
    result.add_argument("--allow-paid", action="store_true")
    result.add_argument("--input")
    result.add_argument("--output", type=Path)
    return result


def run(args):
    if args.command in {"configure", "deploy"} and not args.apply:
        raise ValueError("Cloud writes require --apply.")
    if args.command in {"configure", "probe", "ask", "full-text-sum"} and not args.allow_paid:
        raise ValueError("Embedding or model calls require --allow-paid.")
    if args.command == "full-text-sum" and args.input is not None:
        raise ValueError("full-text-sum uses its fixed audit prompt; omit --input.")
    config = load_config(args.config)
    state = common.external_output(args.config.resolve().parent / "retrieval-only-experiment")
    if args.command == "plan":
        docs = (whole_table_documents(config) if config.get("retrieval_experiment", {}).get("ingestion")
                == "native-whole-table" else build_documents(config))
        result = definitions(config, docs)
        return {
            **result, "instructions": instructions(),
            "source_rows": {p["id"]: p["row_count"] for p in config["partitions"]},
            "chunk_tokens": {key: [item["input_tokens"] for item in values] for key, values in docs.items()},
            "model_deployment": config.get("retrieval_experiment", {}).get("model_deployment")
                                or config["model_deployment"],
            "requires_approval": [
                "Separate synthetic project-readable indexes; not personal native-ACL enforcement.",
                "Foundry project managed identity Search Index Data Reader on the selected demo service.",
                "Native whole-table data sources/indexers, knowledge sources/base, project connection and retrieval-only agent."
                if result["ingestion"] == "native-whole-table" else
                "Six embeddings, new native knowledge sources/base, project connection and retrieval-only prompt agent.",
            ],
            "cloud_mutations": False, "model_calls": False,
        }
    session, factory = common.operator(config)
    target = discover(factory, session)
    experiment = Experiment(config, session, target, state)
    deployment = state / "agent.json"
    if args.command == "configure":
        result = experiment.configure(apply=args.apply, allow_paid=args.allow_paid)
    elif args.command == "verify":
        result = experiment.verify()
    elif args.command == "probe":
        if not args.input or not args.input.strip() or len(args.input) > 8000:
            raise ValueError("Supply one bounded retrieval question.")
        result = experiment.retrieval_probe(args.input, allow_paid=args.allow_paid)
    elif args.command == "deploy":
        result = experiment.deploy(apply=args.apply)
        write_json(deployment, result)
    elif args.command == "full-text-sum":
        result = experiment.full_text_sum(read_json(deployment), allow_paid=args.allow_paid)
    else:
        result = experiment.ask(read_json(deployment), args.input, allow_paid=args.allow_paid)
    write_json(state / (args.command + ".json"), result)
    return result


if __name__ == "__main__":
    args = parser().parse_args()
    result = run(args)
    if args.output:
        write_json(common.external_output(args.output), result)
    print(json.dumps(result, indent=2))
