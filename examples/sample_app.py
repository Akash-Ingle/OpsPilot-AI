#!/usr/bin/env python3
"""OpsPilot-AI sample log shipper.

A tiny stand-in for "your app" that emits realistic service logs and ships them
to an OpsPilot project's /ingest endpoint. Use it to see the full loop end to
end: ingest -> anomaly detection -> auto-analysis -> incident -> Slack alert.

No third-party dependencies (uses only the Python standard library).

Examples
--------
# Fire a single database-failure burst (default) and watch an incident appear:
python sample_app.py --api-key opsp_xxx

# Trigger a different built-in scenario:
python sample_app.py --api-key opsp_xxx --scenario memory_leak
python sample_app.py --api-key opsp_xxx --scenario latency_spike

# Run continuously: steady healthy traffic with an incident burst every ~6 cycles
# (great for a live demo - the dashboard stays quiet, then an incident pops):
python sample_app.py --api-key opsp_xxx --loop

# Point at a local backend instead of the hosted demo:
python sample_app.py --api-key opsp_xxx --base-url http://localhost:8000/api/v1

The API key can also be supplied via the OPSPILOT_API_KEY environment variable.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from typing import Callable, Dict, List

DEFAULT_BASE_URL = "https://opspilot-ai-backend-ka0z.onrender.com/api/v1"

Log = Dict[str, str]


# --------------------------------------------------------------------------- #
# Log generators - the incident bursts mirror the shapes OpsPilot recognizes.
# --------------------------------------------------------------------------- #
def normal_logs(n: int) -> List[Log]:
    services = ["web", "checkout-svc", "orders-svc", "inventory-svc"]
    paths = ["/", "/cart", "/checkout", "/api/products", "/api/orders", "/health"]
    out: List[Log] = []
    for _ in range(n):
        svc = random.choice(services)
        path = random.choice(paths)
        ms = random.randint(8, 180)
        out.append(
            {
                "service_name": svc,
                "severity": "info",
                "message": f"GET {path} 200 latency_ms={ms} request_id={random.randint(10000, 99999)}",
            }
        )
    return out


def database_failure_logs(n: int) -> List[Log]:
    out: List[Log] = []
    for i in range(n):
        out.append(
            {
                "service_name": "orders-svc",
                "severity": "error",
                "message": (
                    f"connection timeout to db-primary after 5000ms "
                    f"pool=orders-pool waiting={i} upstream_timeout=true"
                ),
            }
        )
    out.append(
        {
            "service_name": "orders-svc",
            "severity": "error",
            "message": "circuit breaker opened for db-primary (consecutive_failures=15)",
        }
    )
    out.append(
        {
            "service_name": "orders-svc",
            "severity": "critical",
            "message": "FATAL: connection pool exhausted (size=20 in_use=20) queue_depth=80",
        }
    )
    return out


def memory_leak_logs(n: int) -> List[Log]:
    out: List[Log] = []
    heap = 700
    for i in range(n):
        heap += random.randint(40, 90)
        out.append(
            {
                "service_name": "inventory-svc",
                "severity": "warning" if i < n - 3 else "error",
                "message": (
                    f"gc thrash detected heap_mb={heap} full_gc_count={5 + i} "
                    f"gc_pause_ms={200 + i * 30}"
                ),
            }
        )
    out.append(
        {
            "service_name": "inventory-svc",
            "severity": "error",
            "message": "java.lang.OutOfMemoryError: Java heap space",
        }
    )
    out.append(
        {
            "service_name": "inventory-svc",
            "severity": "critical",
            "message": "Process killed by oom_killer (exit_code=137)",
        }
    )
    return out


def latency_spike_logs(n: int) -> List[Log]:
    out: List[Log] = []
    for i in range(n):
        latency = 3500 + i * 120
        out.append(
            {
                "service_name": "checkout-svc",
                "severity": "error",
                "message": (
                    f"slow_request latency_ms={latency} upstream=payments-svc "
                    f"p99_window_ms={latency + 800} status=504"
                ),
            }
        )
    return out


SCENARIOS: Dict[str, Callable[[int], List[Log]]] = {
    "normal": normal_logs,
    "database_failure": database_failure_logs,
    "memory_leak": memory_leak_logs,
    "latency_spike": latency_spike_logs,
}


# --------------------------------------------------------------------------- #
# Ingestion
# --------------------------------------------------------------------------- #
def ship(base_url: str, api_key: str, logs: List[Log]) -> dict:
    """POST a batch of logs to /ingest. Raises on non-2xx."""
    url = base_url.rstrip("/") + "/ingest"
    body = json.dumps({"logs": logs}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _emit(base_url: str, api_key: str, logs: List[Log], label: str) -> None:
    try:
        result = ship(base_url, api_key, logs)
        print(
            f"  -> shipped {result.get('ingested', len(logs))} {label} log(s); "
            f"watcher_scheduled={result.get('watcher_scheduled')}"
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        print(f"  !! HTTP {exc.code} shipping {label}: {detail}", file=sys.stderr)
        if exc.code == 401:
            print("     (check your --api-key / OPSPILOT_API_KEY)", file=sys.stderr)
            sys.exit(1)
    except urllib.error.URLError as exc:
        print(
            f"  !! network error shipping {label}: {exc}. "
            f"The free-tier backend may be cold-starting - retrying is safe.",
            file=sys.stderr,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ship sample logs to an OpsPilot-AI project.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("OPSPILOT_API_KEY"),
        help="Project API key (or set OPSPILOT_API_KEY).",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="OpsPilot API base URL.")
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIOS),
        default="database_failure",
        help="Which log pattern to emit for the burst (default: database_failure).",
    )
    parser.add_argument(
        "--count", type=int, default=15, help="Lines per incident burst (default: 15)."
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Stream healthy traffic continuously, with periodic incident bursts.",
    )
    parser.add_argument(
        "--interval", type=float, default=5.0, help="Seconds between batches in --loop mode."
    )
    parser.add_argument(
        "--burst-every",
        type=int,
        default=6,
        help="In --loop mode, emit an incident burst every N cycles (default: 6).",
    )
    args = parser.parse_args()

    if not args.api_key:
        parser.error("an API key is required (pass --api-key or set OPSPILOT_API_KEY)")

    print(f"OpsPilot sample app -> {args.base_url}")
    print(f"  project key: {args.api_key[:12]}...")

    if not args.loop:
        gen = SCENARIOS[args.scenario]
        print(f"Sending a '{args.scenario}' burst ({args.count} lines)...")
        _emit(args.base_url, args.api_key, gen(args.count), args.scenario)
        if args.scenario != "normal":
            print(
                "\nDone. Within a few seconds OpsPilot should detect the anomaly, run\n"
                "the agent, and open an incident (and Slack-alert if you configured a\n"
                "webhook). Check the dashboard or GET /projects/me for live stats."
            )
        return

    print("Looping. Healthy traffic with an incident burst every "
          f"{args.burst_every} cycles. Ctrl-C to stop.\n")
    cycle = 0
    try:
        while True:
            cycle += 1
            if cycle % args.burst_every == 0:
                print(f"[cycle {cycle}] INCIDENT burst: {args.scenario}")
                _emit(args.base_url, args.api_key, SCENARIOS[args.scenario](args.count), args.scenario)
            else:
                print(f"[cycle {cycle}] healthy traffic")
                _emit(args.base_url, args.api_key, normal_logs(random.randint(3, 8)), "normal")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
