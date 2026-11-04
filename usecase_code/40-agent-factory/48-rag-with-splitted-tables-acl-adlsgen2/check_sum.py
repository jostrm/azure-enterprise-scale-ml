"""Score saved LLM sales answers offline; no Azure authentication or model calls."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_factory.cli import write_json
from sales_demo.configuration import load_config, read_json
from sales_demo.sum_evaluation import load_expected, score_response


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--config", type=Path, required=True)
    result.add_argument("--oracle", type=Path, required=True)
    result.add_argument("--result", type=Path, required=True, nargs="+")
    result.add_argument("--output", type=Path, required=True)
    return result


def run(args):
    config = load_config(args.config)
    output = args.output.resolve()
    protected = {path.resolve() for path in (args.config, args.oracle, *args.result)}
    roots = (Path(__file__).resolve().parent, Path(config["artifacts_root"]).resolve())
    if output in protected or any(output == root or output.is_relative_to(root) for root in roots):
        raise ValueError("Save the score outside the template/data roots and never overwrite its inputs.")
    expected = load_expected(config, args.oracle)
    cases = [{"file": str(path), **score_response(read_json(path), expected)} for path in args.result]
    report = {"passed": all(case["passed"] for case in cases),
              "mode": "offline-post-inference", "model_calls": False, "cases": cases}
    write_json(output, report)
    return report


if __name__ == "__main__":
    report = run(parser().parse_args())
    print(json.dumps(report, indent=2))
    sys.exit(0 if report["passed"] else 2)
