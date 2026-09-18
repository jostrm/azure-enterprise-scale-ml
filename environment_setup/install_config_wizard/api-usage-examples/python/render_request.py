"""Resolve JSON string placeholders without shell evaluation or textual JSON replacement."""

import argparse
import json
import os
from pathlib import Path
import re
import sys

PLACEHOLDER = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")


def render(value, environment):
    if isinstance(value, str):
        def replace(match):
            name = match[1]
            if not environment.get(name):
                raise ValueError(f"Set the nonempty environment variable {name}.")
            return environment[name]

        result = PLACEHOLDER.sub(replace, value)
        if "${" in result:
            raise ValueError("Unresolved or malformed placeholder; use ${UPPER_CASE_NAME}.")
        return result
    if isinstance(value, list):
        return [render(item, environment) for item in value]
    if isinstance(value, dict):
        if any("${" in key for key in value):
            raise ValueError("Placeholders are supported in values, not property names.")
        return {key: render(item, environment) for key, item in value.items()}
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("template", type=Path)
    parser.add_argument("--out", type=Path, help="New output file; existing files are not overwritten.")
    args = parser.parse_args()
    try:
        document = json.loads(args.template.read_text(encoding="utf-8-sig"))
        if not isinstance(document, dict):
            raise ValueError("A request must be a JSON object.")
        text = json.dumps(render(document, os.environ), indent=2, allow_nan=False) + "\n"
        if args.out:
            with args.out.open("x", encoding="utf-8") as output:
                output.write(text)
        else:
            sys.stdout.write(text)
    except (OSError, ValueError) as error:
        print(f"Request rendering failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
