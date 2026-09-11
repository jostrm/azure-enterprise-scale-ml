"""Azure compute entrypoint; target JSON contains resource IDs, never credentials."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_factory.config import Target
from agent_factory.data import ingest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--container", default="agent-factory")
    parser.add_argument("--prefix", default="kaggle-rag-v1")
    parser.add_argument("--index", default="aif-kaggle-rag-v1")
    args = parser.parse_args()
    target = Target(**json.loads(args.target.read_text(encoding="utf-8-sig")))
    result = ingest(target, container=args.container, prefix=args.prefix, index_name=args.index)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
