"""Service 4 - web-ui: dashboard for the opportunity platform.

Serves a single page dashboard and a small JSON API the page talks to:

    GET  /                      the dashboard
    GET  /api/opportunities     proxy to the opportunity service
    POST /api/register          proxy to the registration service (Service 1)
    GET  /api/registrations     recent registrations from Service 1
    GET  /api/leaderboard/<id>  proxy to the evaluation service
    POST /api/loadtest          run one workload level and return the measurements
    GET  /api/loadtest/results  the workloads run so far in this session
    GET  /api/overview          registration count + per-container CPU/memory
    GET  /health, GET /metrics

The load generator runs *here*, in a fourth container, on purpose: if it ran inside
one of the three measured services it would burn the very CPU that the measurement
is trying to attribute. It reuses loadtest/loadtest.py so there is one implementation
of the workload, and it brackets every level with the target services' /metrics
endpoints so CPU and memory are measured exactly rather than sampled.
"""
import os
import sys
import threading
import time
from typing import Any, Dict, List

import requests
from flask import Flask, jsonify, request, send_from_directory

sys.path.insert(0, "/app/loadtest")

from loadtest import build_payload, run_level  # noqa: E402

PORT = int(os.getenv("PORT", "8080"))
REGISTRATION_URL = os.getenv("REGISTRATION_URL", "http://registration-service:5001").rstrip("/")
OPPORTUNITY_URL = os.getenv("OPPORTUNITY_URL", "http://opportunity-service:5002").rstrip("/")
EVALUATION_URL = os.getenv("EVALUATION_URL", "http://evaluation-service:5003").rstrip("/")
PROXY_TIMEOUT = float(os.getenv("PROXY_TIMEOUT", "15"))
STATIC_DIR = os.getenv("STATIC_DIR", "/app/static")

MEASURED = [
    ("registration-service", REGISTRATION_URL),
    ("opportunity-service", OPPORTUNITY_URL),
    ("evaluation-service", EVALUATION_URL),
]

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")

history: List[Dict[str, Any]] = []
history_lock = threading.Lock()
running: Dict[str, Any] = {"level": None}   # concurrency of the workload in flight, if any


# --- proxy helpers -------------------------------------------------------------
def forward(url, method="GET", payload=None, timeout=PROXY_TIMEOUT):
    try:
        response = requests.request(method, url, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        return jsonify(error="upstream_unreachable", detail=f"{type(exc).__name__}: {exc}"), 502
    try:
        body = response.json()
    except ValueError:
        return jsonify(error="upstream_invalid_json", detail=response.text[:200]), 502
    return jsonify(body), response.status_code


def metrics_snapshot():
    """Exact CPU seconds and peak memory of the three measured containers."""
    snapshot = {}
    for name, base in MEASURED:
        try:
            data = requests.get(f"{base}/metrics", timeout=5).json()
            snapshot[name] = {
                "cpu_seconds": data.get("cpu_seconds", 0.0),
                "memory_peak_mb": round(data.get("memory_peak_bytes", 0) / 1048576, 2),
                "memory_current_mb": round(data.get("memory_current_bytes", 0) / 1048576, 2),
                "rss_mb": round(data.get("rss_bytes", 0) / 1048576, 2),
            }
        except Exception as exc:
            snapshot[name] = {"error": f"{type(exc).__name__}: {exc}"}
    return snapshot


def cpu_percent(before, after, wall_seconds):
    out = {}
    for name, _ in MEASURED:
        pre, post = before.get(name, {}), after.get(name, {})
        if "cpu_seconds" not in pre or "cpu_seconds" not in post:
            out[name] = None
            continue
        used = post["cpu_seconds"] - pre["cpu_seconds"]
        out[name] = {
            "cpu_seconds_used": round(used, 3),
            "cpu_percent": round(used / wall_seconds * 100, 2) if wall_seconds > 0 else 0.0,
        }
    return out


# --- dashboard -----------------------------------------------------------------
@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/api/opportunities")
def opportunities():
    return forward(f"{OPPORTUNITY_URL}/opportunities")


@app.post("/api/register")
def register():
    body = request.get_json(silent=True) or {}
    return forward(f"{REGISTRATION_URL}/register", method="POST", payload=body)


@app.get("/api/registrations")
def registrations():
    limit = request.args.get("limit", 25)
    return forward(f"{REGISTRATION_URL}/registrations?limit={limit}")


@app.get("/api/leaderboard/<opportunity_id>")
def leaderboard(opportunity_id):
    return forward(f"{EVALUATION_URL}/leaderboard/{opportunity_id}")


@app.get("/api/overview")
def overview():
    registration_count = None
    try:
        registration_count = requests.get(
            f"{REGISTRATION_URL}/health", timeout=5
        ).json().get("registrations")
    except Exception:
        pass
    return jsonify(
        registration_count=registration_count,
        containers=metrics_snapshot(),
        running_level=running["level"],
        workloads=len(history),
    )


# --- load testing --------------------------------------------------------------
@app.post("/api/loadtest")
def loadtest():
    body = request.get_json(silent=True) or {}
    try:
        concurrency = int(body.get("concurrency", 1))
        requests_count = int(body.get("requests", 100))
    except (TypeError, ValueError):
        return jsonify(error="validation_error", detail="concurrency and requests must be integers"), 400

    if not 1 <= concurrency <= 64:
        return jsonify(error="validation_error", detail="concurrency must be between 1 and 64"), 400
    if not 1 <= requests_count <= 2000:
        return jsonify(error="validation_error", detail="requests must be between 1 and 2000"), 400

    with history_lock:
        busy = running["level"]
        if busy is not None:
            return jsonify(
                error="loadtest_in_progress",
                detail=f"concurrency {busy} is still running",
            ), 409
        running["level"] = concurrency

    try:
        before = metrics_snapshot()
        wall_start = time.perf_counter()
        row = run_level(f"{REGISTRATION_URL}/register", requests_count, concurrency, 120.0)
        wall_seconds = time.perf_counter() - wall_start
        after = metrics_snapshot()

        record = {
            "concurrency": concurrency,
            "requests": requests_count,
            "wall_seconds": round(wall_seconds, 3),
            "cpu": cpu_percent(before, after, wall_seconds),
            "containers": {
                name: after.get(name, {}) for name, _ in MEASURED
            },
            **row,
        }
        with history_lock:
            history.append(record)
        return jsonify(record), 200
    finally:
        with history_lock:
            running["level"] = None


@app.get("/api/loadtest/results")
def loadtest_results():
    with history_lock:
        return jsonify(count=len(history), results=list(history))


@app.get("/api/loadtest/payload")
def loadtest_payload():
    """A sample request body, so the dashboard can show exactly what is sent."""
    return jsonify(build_payload(0))


@app.get("/health")
def health():
    return jsonify(
        service="web-ui",
        status="ok",
        workloads=len(history),
        running_level=running["level"],
    )


@app.get("/metrics")
def metrics():
    """The UI container's own cgroup numbers, same format as the other services."""
    return jsonify(
        service="web-ui",
        cpu_seconds=round(_cpu_seconds(), 4),
        memory_peak_bytes=_memory_bytes(peak=True),
        memory_current_bytes=_memory_bytes(),
    )


CGROUP_V2_CPU = "/sys/fs/cgroup/cpu.stat"
CGROUP_V1_CPU = "/sys/fs/cgroup/cpuacct/cpuacct.usage"
CGROUP_V2_MEM_PEAK = "/sys/fs/cgroup/memory.peak"
CGROUP_V1_MEM_PEAK = "/sys/fs/cgroup/memory/memory.max_usage_in_bytes"
CGROUP_V2_MEM_CURRENT = "/sys/fs/cgroup/memory.current"
CGROUP_V1_MEM_CURRENT = "/sys/fs/cgroup/memory/memory.usage_in_bytes"


def _read_number(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return float(handle.read().strip())
    except (OSError, ValueError):
        return None


def _cpu_seconds():
    try:
        with open(CGROUP_V2_CPU, "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("usage_usec"):
                    return float(line.split()[1]) / 1_000_000
    except OSError:
        pass
    nanos = _read_number(CGROUP_V1_CPU)
    return nanos / 1_000_000_000 if nanos is not None else 0.0


def _memory_bytes(peak=False):
    if peak:
        for path in (CGROUP_V2_MEM_PEAK, CGROUP_V1_MEM_PEAK):
            value = _read_number(path)
            if value:
                return value
        return 0.0
    for path in (CGROUP_V2_MEM_CURRENT, CGROUP_V1_MEM_CURRENT):
        value = _read_number(path)
        if value:
            return value
    return 0.0


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)