"""Use case 3 - external signals and timeline annotations.

A synthetic probe calls an endpoint and reports the result as an externally evaluated
signal on an entity. Reports expire (default 15 minutes), so a stopped probe turns the
signal Unknown instead of leaving a stale Healthy. Run it on a schedule (Container Apps
job, Function timer, pipeline) from inside the factory network for private endpoints.

    # probe the agent web app and report on the Applications layer
    python 03_external_signals.py --model-id <id> --entity layer-apps --signal agent-web-probe \
        --url https://<agent-app>/health --apply
    # annotate a release on the root timeline
    python 03_external_signals.py --model-id <id> --annotate-release 2026.10.1 --apply
"""
import argparse
import time
import urllib.error
import urllib.request

from _common import add_model_arguments, client_from

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
add_model_arguments(parser)
parser.add_argument("--entity", default="root")
parser.add_argument("--signal", default="synthetic-probe")
parser.add_argument("--url", help="HTTPS endpoint to probe (2xx = Healthy, slow = Degraded, error = Unhealthy).")
parser.add_argument("--slow-ms", type=int, default=3000)
parser.add_argument("--expires", type=int, default=15)
parser.add_argument("--annotate-release", metavar="VERSION")
parser.add_argument("--apply", action="store_true", help="Send the report/annotation (otherwise print it).")
args = parser.parse_args()
client = client_from(args)


def probe(url: str) -> tuple[str, float, str]:
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            elapsed = (time.perf_counter() - start) * 1000
            state = "Healthy" if elapsed < args.slow_ms else "Degraded"
            return state, elapsed, f"HTTP {response.status} in {elapsed:.0f} ms"
    except urllib.error.HTTPError as error:
        return "Unhealthy", (time.perf_counter() - start) * 1000, f"HTTP {error.code}"
    except (urllib.error.URLError, TimeoutError) as error:
        return "Unhealthy", (time.perf_counter() - start) * 1000, f"Unreachable: {error}"[:300]


if args.url:
    state, elapsed, context = probe(args.url)
    print(f"{args.signal} on {args.entity}: {state} ({context})")
    if args.apply:
        client.ingest_health_report(args.entity, args.signal, state, value=round(elapsed), context=context,
                                    expires_in_minutes=args.expires,
                                    evaluation_rules={"degradedRule": {"operator": "GreaterThan", "threshold": args.slow_ms},
                                                      "unhealthyRule": {"operator": "GreaterThan", "threshold": 30000}})
        print("Reported. The entity and its parents re-evaluate within about a minute.")

if args.annotate_release:
    details = {"event": "release", "version": args.annotate_release}
    if args.apply:
        print(client.add_annotation("root", details, f"AI Factory release {args.annotate_release}"))
    else:
        print(f"Would annotate root with {details} (add --apply).")
