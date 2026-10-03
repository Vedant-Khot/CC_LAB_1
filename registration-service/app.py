"""Service 1 - Registration Service (entry point).

Client -> POST /register -> Opportunity Service (eligibility check)
                       -> Evaluation Service (score + rank)
                       -> Evaluation Service (simulated confirmation)
"""
import itertools
import os
import threading
import time

import requests
from flask import Flask, jsonify, request

OPPORTUNITY_URL = os.getenv(
    "OPPORTUNITY_URL", "http://opportunity-service:5002"
).rstrip("/")
EVALUATION_URL = os.getenv(
    "EVALUATION_URL", "http://evaluation-service:5003"
).rstrip("/")
INTERNAL_TIMEOUT = float(os.getenv("INTERNAL_TIMEOUT", "10"))

app = Flask(__name__)

registrations = {}
_lock = threading.Lock()
_id_sequence = itertools.count(1)

REQUIRED_FIELDS = ("student_name", "email", "college", "year", "opportunity_id")

# --- resource metrics ---------------------------------------------------------
# Read straight from the cgroup, so the load harness gets the exact CPU seconds
# and peak memory of the whole container instead of a sampled estimate.
CGROUP_V2_CPU = "/sys/fs/cgroup/cpu.stat"
CGROUP_V1_CPU = "/sys/fs/cgroup/cpuacct/cpuacct.usage"
CGROUP_V2_MEM_PEAK = "/sys/fs/cgroup/memory.peak"
CGROUP_V1_MEM_PEAK = "/sys/fs/cgroup/memory/memory.max_usage_in_bytes"
CGROUP_V2_MEM_CURRENT = "/sys/fs/cgroup/memory.current"
CGROUP_V1_MEM_CURRENT = "/sys/fs/cgroup/memory/memory.usage_in_bytes"


def _read_number(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read().strip()
    except OSError:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def rss_bytes():
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return float(line.split()[1]) * 1024
    except OSError:
        pass
    return 0.0


def cpu_seconds():
    try:
        with open(CGROUP_V2_CPU, "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("usage_usec"):
                    return float(line.split()[1]) / 1_000_000
    except OSError:
        pass
    nanos = _read_number(CGROUP_V1_CPU)
    return nanos / 1_000_000_000 if nanos is not None else 0.0


def memory_bytes(peak=False):
    if peak:
        for path in (CGROUP_V2_MEM_PEAK, CGROUP_V1_MEM_PEAK):
            value = _read_number(path)
            if value:
                return value
        return rss_bytes()
    for path in (CGROUP_V2_MEM_CURRENT, CGROUP_V1_MEM_CURRENT):
        value = _read_number(path)
        if value:
            return value
    return rss_bytes()


class DownstreamError(Exception):
    def __init__(self, stage, detail):
        super().__init__(detail)
        self.stage = stage
        self.detail = detail


def call_service(stage, method, url, payload):
    started = time.perf_counter()
    try:
        response = requests.request(method, url, json=payload, timeout=INTERNAL_TIMEOUT)
    except requests.RequestException as exc:
        raise DownstreamError(stage, f"{type(exc).__name__}: {exc}") from exc
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)

    if response.status_code >= 500:
        raise DownstreamError(
            stage, f"upstream returned {response.status_code}: {response.text[:200]}"
        )
    try:
        body = response.json()
    except ValueError:
        raise DownstreamError(stage, "upstream returned invalid JSON")
    return response.status_code, body, elapsed_ms


@app.get("/health")
def health():
    with _lock:
        count = len(registrations)
    return jsonify(
        service="registration-service",
        status="ok",
        registrations=count,
        opportunity_url=OPPORTUNITY_URL,
        evaluation_url=EVALUATION_URL,
    )


@app.get("/metrics")
def metrics():
    with _lock:
        count = len(registrations)
    return jsonify(
        service="registration-service",
        cpu_seconds=round(cpu_seconds(), 4),
        memory_peak_bytes=memory_bytes(peak=True),
        memory_current_bytes=memory_bytes(),
        rss_bytes=rss_bytes(),
        registrations=count,
    )


@app.post("/register")
def register():
    started = time.perf_counter()
    body = request.get_json(silent=True) or {}

    fields = {}
    for name in REQUIRED_FIELDS:
        if body.get(name) in (None, ""):
            fields[name] = "required"
    if "year" not in fields and not isinstance(body.get("year"), int):
        fields["year"] = "must be an integer"
    team_size = body.get("team_size", 1)
    if not isinstance(team_size, int) or team_size < 1:
        fields["team_size"] = "must be an integer >= 1"
    if fields:
        return jsonify(error="validation_error", fields=fields), 400

    opportunity_id = str(body["opportunity_id"])
    applicant = {
        "name": body["student_name"],
        "email": body["email"],
        "college": body["college"],
        "year": body["year"],
        "skills": [str(skill).strip() for skill in (body.get("skills") or [])],
    }

    timings = {}

    # 1) eligibility: deadline + seats + skills
    try:
        status, check, timings["opportunity_check_ms"] = call_service(
            "opportunity-service",
            "POST",
            f"{OPPORTUNITY_URL}/opportunities/{opportunity_id}/check",
            {"team_size": team_size, "year": applicant["year"], "skills": applicant["skills"]},
        )
    except DownstreamError as exc:
        return jsonify(error="upstream_failure", stage=exc.stage, detail=exc.detail), 502

    if status == 404:
        return jsonify(
            error="opportunity_not_found",
            opportunity_id=opportunity_id,
            timings_ms=timings,
        ), 404
    if status == 409 or not check.get("eligible"):
        return (
            jsonify(
                error="not_eligible",
                reason=check.get("reason", "unknown"),
                opportunity_id=opportunity_id,
                details=check.get("details", {}),
                timings_ms=timings,
            ),
            409,
        )

    with _lock:
        registration_id = f"reg-{next(_id_sequence):06d}"

    # 2) scoring / ranking (heavy service)
    try:
        _, evaluation, timings["evaluation_ms"] = call_service(
            "evaluation-service",
            "POST",
            f"{EVALUATION_URL}/evaluate",
            {
                "registration_id": registration_id,
                "opportunity_id": opportunity_id,
                "applicant": applicant,
            },
        )
    except DownstreamError as exc:
        return jsonify(error="upstream_failure", stage=exc.stage, detail=exc.detail), 502

    # 3) simulated confirmation
    try:
        _, notification, timings["notify_ms"] = call_service(
            "evaluation-service",
            "POST",
            f"{EVALUATION_URL}/notify",
            {"registration_id": registration_id, "to": applicant["email"]},
        )
    except DownstreamError as exc:
        return jsonify(error="upstream_failure", stage=exc.stage, detail=exc.detail), 502

    timings["total_ms"] = round((time.perf_counter() - started) * 1000, 2)

    record = {
        "registration_id": registration_id,
        "status": "confirmed",
        "opportunity_id": opportunity_id,
        "opportunity_title": check.get("title"),
        "applicant": applicant,
        "team_size": team_size,
        "score": evaluation.get("score"),
        "rank": evaluation.get("rank"),
        "participants": evaluation.get("participants"),
        "notification_id": notification.get("message_id"),
        "timings_ms": timings,
    }
    with _lock:
        registrations[registration_id] = record

    return jsonify(record), 201


@app.get("/registrations")
def list_registrations():
    with _lock:
        rows = list(registrations.values())
    limit = request.args.get("limit", type=int)
    if limit:
        rows = rows[-limit:]
    return jsonify(count=len(registrations), registrations=rows)


@app.get("/registrations/<registration_id>")
def get_registration(registration_id):
    with _lock:
        record = registrations.get(registration_id)
    if record is None:
        return jsonify(error="not_found", registration_id=registration_id), 404
    return jsonify(record)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)