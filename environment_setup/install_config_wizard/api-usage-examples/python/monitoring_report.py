"""Call the canonical monitoring API using the existing guarded SDK; no collector."""

import argparse
import json
from pathlib import Path
import sys


def request_report(client, body, *, export=False, summary=False):
    if export and summary:
        raise ValueError("Summary returns JSON; CSV export selects one detailed report.")
    if summary:
        return client.monitoring_summary(body)
    return client.monitoring_export(body) if export else client.monitoring_report(body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, help="Canonical request, with explicit sample/live source.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--export", action="store_true", help="Return canonical filtered CSV attachment to stdout.")
    mode.add_argument("--summary", action="store_true", help="Return the combined six-report JSON summary.")
    args = parser.parse_args()
    try:
        from azurefactory import APIError, AzureFactoryClient
    except ImportError:
        print("Install the sibling azurefactory-cli package; see the examples readme.", file=sys.stderr)
        return 2
    try:
        path = Path(args.request)
        with path.open("rb") as stream:
            raw = stream.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError("Request exceeds 8 MiB.")
        body = json.loads(raw)
        result = request_report(AzureFactoryClient(), body, export=args.export, summary=args.summary)
        if args.export:
            print(result, end="")
        else:
            print(json.dumps(result, indent=2, allow_nan=False))
    except APIError as error:
        print(str(error), file=sys.stderr)
        return error.exit_code
    except (OSError, ValueError, TypeError):
        print("Cannot read or render the explicit monitoring request.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
