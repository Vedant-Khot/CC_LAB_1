"""Service 3 - Evaluation / Notification Service.

Scores each registration (CPU heavy on purpose, this is the bottleneck the lab
measures), maintains a per-hackathon leaderboard, and "sends" a confirmation
notification (simulated, no real e-mail).
"""
import hashlib
import os
import threading
import time

from flask import Flask, jsonify, request

PORT = int(os.getenv("PORT", "5003"))

# --- knobs used to tune how heavy this service is -----------------------------
HEAVY_ITERS = int(os.getenv("HEAVY_ITERS", "12000"))  # sha256 rounds per request
HEAVY_SLEEP = float(os.getenv("HEAVY_SLEEP", "0.03"))  # simulated model inference
NOTIFY_DELAY = float(os.getenv("NOTIFY_DELAY", "0.005"))

app = Flask(__name__)

SKILL_POINTS = {
    "python": 14,
    "java": 10,
    "c++": 10,
    "c#": 8,
    "javascript": 9,
    "typescript": 9,
    "react": 9,
    "nodejs": 9,
    "django": 8,
    "sql": 7,
    "docker": 7,
    "kubernetes": 8,
    "git": 5,
    "machine-learning": 12,
    "llm": 12,
    "statistics": 8,
    "solidity": 9,
    "unity": 7,
    "embedded": 8,
}

YEAR_BONUS = {1: 0, 2: 3, 3: 6, 4: 8, 5: 8}

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

leaderboards = {}  # opportunity_id -> list of {score, name, registration_id}
outbox = []
stats = {"evaluated": 0, "notified": 0, "total_compute_ms": 0.0}
_lock = threading.Lock()


def heavy_digest(seed):
    """Deterministic CPU burn: chained sha256 rounds."""
    digest = seed
    for i in range(HEAVY_ITERS):
        digest = hashlib.sha256(digest + i.to_bytes(4, "big")).digest()
    return digest


def compute_score(registration_id, opportunity_id, applicant):
    seed = hashlib.sha256(
        f"{registration_id}:{opportunity_id}:{applicant.get('name', '')}".encode()
    ).digest()

    digest = heavy_digest(seed)
    if HEAVY_SLEEP:
        time.sleep(HEAVY_SLEEP)

    skill_score = sum(
        SKILL_POINTS.get(skill.lower(), 2) for skill in applicant.get("skills", [])
    )
    year_bonus = YEAR_BONUS.get(applicant.get("year"), 0)
    jitter = int.from_bytes(digest[:4], "big") % 15  # 0..14, stable per registration

    return max(0, min(100, skill_score + year_bonus + jitter))


def record_score(opportunity_id, registration_id, applicant, score):
    with _lock:
        board = leaderboards.setdefault(opportunity_id, [])
        board.append(
            {
                "registration_id": registration_id,
                "name": applicant.get("name"),
                "score": score,
            }
        )
        board.sort(key=lambda row: (-row["score"], row["registration_id"]))
        rank = next(
            index + 1
            for index, row in enumerate(board)
            if row["registration_id"] == registration_id
        )
        return rank, len(board), board[:10]


@app.get("/health")
def health():
    return jsonify(
        service="evaluation-service",
        status="ok",
        evaluated=stats["evaluated"],
        notified=stats["notified"],
        leaderboards=len(leaderboards),
        heavy_iters=HEAVY_ITERS,
        heavy_sleep=HEAVY_SLEEP,
    )


@app.get("/metrics")
def metrics():
    return jsonify(
        service="evaluation-service",
        cpu_seconds=round(cpu_seconds(), 4),
        memory_peak_bytes=memory_bytes(peak=True),
        memory_current_bytes=memory_bytes(),
        rss_bytes=rss_bytes(),
    )


@app.get("/stats")
def get_stats():
    with _lock:
        average = (
            round(stats["total_compute_ms"] / stats["evaluated"], 2)
            if stats["evaluated"]
            else 0.0
        )
        return jsonify(
            evaluated=stats["evaluated"],
            notified=stats["notified"],
            avg_compute_ms=average,
            outbox_size=len(outbox),
        )


@app.post("/evaluate")
def evaluate():
    started = time.perf_counter()
    body = request.get_json(silent=True) or {}
    registration_id = body.get("registration_id")
    opportunity_id = body.get("opportunity_id")
    applicant = body.get("applicant") or {}

    if registration_id is None or opportunity_id is None:
        return (
            jsonify(
                error="validation_error",
                fields={
                    "registration_id": "required",
                    "opportunity_id": "required",
                },
            ),
            400,
        )

    score = compute_score(registration_id, opportunity_id, applicant)
    rank, participants, top = record_score(opportunity_id, registration_id, applicant, score)
    compute_ms = round((time.perf_counter() - started) * 1000, 2)

    with _lock:
        stats["evaluated"] += 1
        stats["total_compute_ms"] += compute_ms

    return jsonify(
        registration_id=registration_id,
        opportunity_id=opportunity_id,
        score=score,
        rank=rank,
        participants=participants,
        compute_ms=compute_ms,
        leaderboard_top=top,
    )


@app.get("/leaderboard/<opportunity_id>")
def leaderboard(opportunity_id):
    with _lock:
        board = leaderboards.get(opportunity_id, [])
        return jsonify(
            opportunity_id=opportunity_id,
            participants=len(board),
            top=board[:10],
        )


@app.post("/notify")
def notify():
    body = request.get_json(silent=True) or {}
    registration_id = body.get("registration_id")
    to = body.get("to")
    if not registration_id or not to:
        return (
            jsonify(
                error="validation_error",
                fields={"registration_id": "required", "to": "required"},
            ),
            400,
        )

    if NOTIFY_DELAY:
        time.sleep(NOTIFY_DELAY)

    message_id = f"msg-{registration_id}-{len(outbox) + 1}"
    message = {
        "message_id": message_id,
        "registration_id": registration_id,
        "to": to,
        "channel": "email(simulated)",
        "subject": "Hackathon registration confirmed",
        "body": f"Registration {registration_id} is confirmed. Good luck!",
    }
    with _lock:
        outbox.append(message)
        stats["notified"] += 1
        outbox_size = len(outbox)

    return jsonify(sent=True, message_id=message_id, outbox_size=outbox_size)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)