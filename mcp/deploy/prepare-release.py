"""Prepare a local immutable build context; no Azure or registry writes."""
import argparse
import json
from pathlib import Path

from release import GitSource, load_graph_config, prepare_release, verify_release


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--purple-root", type=Path)
    parser.add_argument("--api-root", type=Path)
    parser.add_argument("--purple-ref")
    parser.add_argument("--api-ref")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--wheelhouse", type=Path)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--graph-config", type=Path,
                        help="Explicit agent JSON configuration whose enabled, pinned dual_graph snapshot is packaged.")
    args = parser.parse_args()
    if args.verify:
        manifest = verify_release(args.output.resolve())
    else:
        if not all((args.purple_root, args.api_root, args.purple_ref, args.api_ref, args.wheelhouse)):
            parser.error("Both repository roots, full source revisions and a Linux wheelhouse are required.")
        manifest = prepare_release(
            GitSource(args.purple_root.resolve(), args.purple_ref),
            GitSource(args.api_root.resolve(), args.api_ref),
            Path(__file__).resolve().parents[1], args.output.resolve(), args.wheelhouse.resolve(),
            graph_config=load_graph_config(args.graph_config) if args.graph_config else None,
        )
    print(json.dumps({"release_hash": manifest["release_hash"], "files": len(manifest["files"]),
                      "output": str(args.output.resolve())}))


if __name__ == "__main__":
    main()
