"""Load test for the Unstop-style registration chain.

Pure standard library, so it runs on Windows/macOS/Linux without installing
anything. Hits POST /register (Service 1 -> Service 2 -> Service 3) at several
concurrency levels with a fixed total number of requests per level.

Each worker thread keeps one keep-alive HTTP connection, so the numbers measure
the services and not TCP setup through the Docker Desktop proxy.

Usage:
    python loadtest.py --requests 200 --levels 1,2,4,8,16
"""

import argparse
import http.client
import json
import os
import statistics
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

DEFAULT_URL = "http://localhost:5001/register"

# Chosen so every generated request is eligible (201) and therefore walks the
# whole chain: hack-001/002/005/010 need skills this applicant already has,
# hack-009 has no skill requirement.
OPPORTUNITY_IDS = ["hack-001", "hack-002", "hack-005", "hack-009", "hack-010"]
SKILLS = [
    "python",
    "machine-learning",
    "docker",
    "kubernetes",
    "git",
    "sql",
    "llm",
]

STAGE_KEYS = ("opportunity_check_ms", "evaluation_ms", "notify_ms", "total_ms")


def build_payload(index):
    return {
        "student_name": f"Student {index}",
        "email": f"student{index}@unstop-lab.test",
        "college": "NIT Trichy",
        "year": 3,
        "skills": SKILLS,
        "opportunity_id": OPPORTUNITY_IDS[index % len(OPPORTUNITY_IDS)],
        "team_size": 2,
    }


class Client:
    """Keep-alive HTTP client, one instance per worker thread."""

    def __init__(self, url, timeout):
        parts = urllib.parse.urlsplit(url)
        self.host = parts.hostname or "localhost"
        self.port = parts.port or 80
        self.path = parts.path or "/"
        self.timeout = timeout
        self.conn = None

    def _connect(self):
        self.conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        return self.conn

    def post(self, payload):
        body = json.dumps(payload)
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
            "Connection": "keep-alive",
        }
        for attempt in (1, 2):
            conn = self._connect()
            try:
                conn.request("POST", self.path, body=body, headers=headers)
                response = conn.getresponse()
                data = response.read()
                return response.status, data
            except (http.client.HTTPException, OSError):
                self.close()
                if attempt == 2:
                    raise
        raise RuntimeError("unreachable")

    def close(self):
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None


def worker(url, timeout, batch, results, barrier):
    client = Client(url, timeout)
    try:
        barrier.wait()
        for index, payload in batch:
            started = time.perf_counter()
            try:
                status, data = client.post(payload)
                error = None
            except Exception as exc:
                status, data, error = 0, b"", f"{type(exc).__name__}: {exc}"
            latency_ms = (time.perf_counter() - started) * 1000

            stages = {}
            if status == 201:
                try:
                    stages = json.loads(data).get("timings_ms", {})
                except ValueError:
                    stages = {}

            results[index] = {
                "status": status,
                "latency_ms": latency_ms,
                "error": error,
                "stages": stages,
            }
    finally:
        client.close()


def percentile(sorted_values, fraction):
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, int(round(fraction * (len(sorted_values) - 1))))
    return sorted_values[index]


def run_level(url, total_requests, concurrency, timeout):
    results = [None] * total_requests
    barrier = threading.Barrier(concurrency)

    indexed = [(index, build_payload(index)) for index in range(total_requests)]
    batches = [indexed[offset::concurrency] for offset in range(concurrency)]

    wall_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [
            pool.submit(worker, url, timeout, batch, results, barrier)
            for batch in batches
        ]
        for future in futures:
            future.result()
    wall_seconds = time.perf_counter() - wall_start

    done = [row for row in results if row]
    latencies = sorted(row["latency_ms"] for row in done)
    ok = sum(1 for row in done if row["status"] == 201)
    not_eligible = sum(1 for row in done if row["status"] == 409)
    failed = len(done) - ok - not_eligible

    stages = {}
    for key in STAGE_KEYS:
        values = [
            row["stages"][key]
            for row in done
            if row["status"] == 201 and key in row["stages"]
        ]
        stages[key] = round(statistics.fmean(values), 2) if values else 0.0

    return {
        "concurrency": concurrency,
        "requests": total_requests,
        "ok": ok,
        "not_eligible": not_eligible,
        "failed": failed,
        "wall_seconds": round(wall_seconds, 3),
        "rps": round(total_requests / wall_seconds, 2),
        "avg_ms": round(statistics.fmean(latencies), 2),
        "p50_ms": round(percentile(latencies, 0.50), 2),
        "p95_ms": round(percentile(latencies, 0.95), 2),
        "p99_ms": round(percentile(latencies, 0.99), 2),
        "max_ms": round(max(latencies), 2),
        "avg_stage_ms": stages,
    }


def print_table(rows):
    header = (
        f"{'conc':>5} {'reqs':>5} {'201':>5} {'409':>4} {'err':>4} "
        f"{'wall_s':>7} {'rps':>7} {'avg_ms':>8} {'p50_ms':>8} "
        f"{'p95_ms':>8} {'p99_ms':>8} {'max_ms':>8}"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row['concurrency']:>5} {row['requests']:>5} {row['ok']:>5} "
            f"{row['not_eligible']:>4} {row['failed']:>4} {row['wall_seconds']:>7.2f} "
            f"{row['rps']:>7.2f} {row['avg_ms']:>8.2f} {row['p50_ms']:>8.2f} "
            f"{row['p95_ms']:>8.2f} {row['p99_ms']:>8.2f} {row['max_ms']:>8.2f}"
        )

    print("\nserver-side time per request (avg ms, measured inside the services)")
    header = (
        f"{'conc':>5} {'opp_check':>11} {'evaluate':>10} "
        f"{'notify':>8} {'service_total':>14}"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        stages = row["avg_stage_ms"]
        print(
            f"{row['concurrency']:>5} {stages['opportunity_check_ms']:>11.2f} "
            f"{stages['evaluation_ms']:>10.2f} {stages['notify_ms']:>8.2f} "
            f"{stages['total_ms']:>14.2f}"
        )


def main():
    parser = argparse.ArgumentParser(description="Load test for the registration chain")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--requests", type=int, default=200,
                        help="total requests per concurrency level")
    parser.add_argument("--levels", default="1,2,4,8,16",
                        help="comma separated concurrency levels")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--json-out", default="results/results.json")
    parser.add_argument("--warmup", type=int, default=5,
                        help="warmup requests before measuring")
    args = parser.parse_args()

    levels = [int(level) for level in args.levels.split(",") if level.strip()]

    print(f"target: {args.url}", flush=True)
    print(f"requests per level: {args.requests}", flush=True)
    print(f"levels: {levels}", flush=True)
    print(f"warmup: {args.warmup}\n", flush=True)

    warm_client = Client(args.url, args.timeout)
    for i in range(args.warmup):
        try:
            warm_client.post(build_payload(900_000 + i))
        except Exception as exc:
            print(f"warmup request failed: {exc}", flush=True)
    warm_client.close()

    rows = [run_level(args.url, args.requests, level, args.timeout) for level in levels]
    print_table(rows)

    output_dir = os.path.dirname(args.json_out)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(args.json_out, "w", encoding="utf-8") as handle:
        json.dump({"url": args.url, "requests_per_level": args.requests, "rows": rows},
                  handle, indent=2)
    print(f"\nJSON written to {args.json_out}", flush=True)

    first, last = rows[0], rows[-1]
    if len(rows) == 1:
        row = rows[0]
        print(f"throughput: {row['rps']} rps at concurrency {row['concurrency']} "
              f"({row['ok']} ok, {row['not_eligible']} rejected, {row['failed']} failed)")
        print(f"p95 latency: {row['p95_ms']} ms")
        return 0

    print(f"throughput: {first['rps']} rps at concurrency 1 -> {last['rps']} rps at "
          f"concurrency {last['concurrency']} (x{last['rps'] / first['rps']:.2f})")
    print(f"p95 latency: {first['p95_ms']} ms -> {last['p95_ms']} ms "
          f"(x{last['p95_ms'] / first['p95_ms']:.2f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())