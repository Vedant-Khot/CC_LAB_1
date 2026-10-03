"""Service 2 - Opportunity Service.

Stores hackathons in memory and answers eligibility questions:
is the event open, are there seats left, is the student eligible?
"""
import os
import time
from datetime import datetime, timezone

from flask import Flask, jsonify, request

PORT = int(os.getenv("PORT", "5002"))
IO_DELAY = float(os.getenv("IO_DELAY", "0.005"))
RESERVE_SEATS = os.getenv("RESERVE_SEATS", "false").lower() == "true"

app = Flask(__name__)

OPPORTUNITIES = [
    {
        "id": "hack-001",
        "title": "Smart India Hackathon",
        "seats_total": 500,
        "seats_taken": 120,
        "deadline": "2026-12-20T18:00:00Z",
        "eligible_years": {"min": 1, "max": 4},
        "required_skills": ["python", "machine-learning"],
        "min_skill_match": 0.5,
        "mode": "offline",
        "prize_pool_inr": 500000,
    },
    {
        "id": "hack-002",
        "title": "Open Source Contribution Sprint",
        "seats_total": 300,
        "seats_taken": 40,
        "deadline": "2026-11-30T18:00:00Z",
        "eligible_years": {"min": 2, "max": 4},
        "required_skills": ["git", "python"],
        "min_skill_match": 0.5,
        "mode": "online",
        "prize_pool_inr": 150000,
    },
    {
        "id": "hack-003",
        "title": "FinTech Buildathon",
        "seats_total": 200,
        "seats_taken": 195,
        "deadline": "2026-11-15T18:00:00Z",
        "eligible_years": {"min": 2, "max": 3},
        "required_skills": ["nodejs", "sql"],
        "min_skill_match": 1.0,
        "mode": "online",
        "prize_pool_inr": 300000,
    },
    {
        "id": "hack-004",
        "title": "HealthTech Hack",
        "seats_total": 150,
        "seats_taken": 10,
        "deadline": "2025-01-15T18:00:00Z",
        "eligible_years": {"min": 2, "max": 4},
        "required_skills": ["python", "django"],
        "min_skill_match": 0.5,
        "mode": "offline",
        "prize_pool_inr": 200000,
    },
    {
        "id": "hack-005",
        "title": "AI Agent Builders Cup",
        "seats_total": 400,
        "seats_taken": 90,
        "deadline": "2026-12-01T18:00:00Z",
        "eligible_years": {"min": 3, "max": 5},
        "required_skills": ["python", "llm"],
        "min_skill_match": 0.5,
        "mode": "online",
        "prize_pool_inr": 400000,
    },
    {
        "id": "hack-006",
        "title": "Campus Blockchain Jam",
        "seats_total": 120,
        "seats_taken": 30,
        "deadline": "2026-10-28T18:00:00Z",
        "eligible_years": {"min": 2, "max": 4},
        "required_skills": ["solidity"],
        "min_skill_match": 1.0,
        "mode": "offline",
        "prize_pool_inr": 100000,
    },
    {
        "id": "hack-007",
        "title": "Data Science Weekend",
        "seats_total": 250,
        "seats_taken": 70,
        "deadline": "2026-11-25T18:00:00Z",
        "eligible_years": {"min": 2, "max": 4},
        "required_skills": ["python", "sql", "statistics"],
        "min_skill_match": 0.34,
        "mode": "online",
        "prize_pool_inr": 180000,
    },
    {
        "id": "hack-008",
        "title": "AR/VR Prototype Fest",
        "seats_total": 90,
        "seats_taken": 88,
        "deadline": "2026-12-10T18:00:00Z",
        "eligible_years": {"min": 2, "max": 4},
        "required_skills": ["unity", "c#"],
        "min_skill_match": 0.5,
        "mode": "offline",
        "prize_pool_inr": 120000,
    },
    {
        "id": "hack-009",
        "title": "Green Energy Challenge",
        "seats_total": 350,
        "seats_taken": 110,
        "deadline": "2026-12-31T18:00:00Z",
        "eligible_years": {"min": 1, "max": 5},
        "required_skills": [],
        "min_skill_match": 0.0,
        "mode": "online",
        "prize_pool_inr": 250000,
    },
    {
        "id": "hack-010",
        "title": "Cloud Native Hack",
        "seats_total": 220,
        "seats_taken": 55,
        "deadline": "2026-11-10T18:00:00Z",
        "eligible_years": {"min": 3, "max": 4},
        "required_skills": ["docker", "kubernetes"],
        "min_skill_match": 0.5,
        "mode": "online",
        "prize_pool_inr": 220000,
    },
    {
        "id": "hack-011",
        "title": "Women In Tech Hackathon",
        "seats_total": 180,
        "seats_taken": 65,
        "deadline": "2026-12-05T18:00:00Z",
        "eligible_years": {"min": 1, "max": 5},
        "required_skills": ["python"],
        "min_skill_match": 0.0,
        "mode": "online",
        "prize_pool_inr": 350000,
    },
    {
        "id": "hack-012",
        "title": "Robotics Arena",
        "seats_total": 60,
        "seats_taken": 59,
        "deadline": "2026-10-20T18:00:00Z",
        "eligible_years": {"min": 3, "max": 4},
        "required_skills": ["c++", "embedded"],
        "min_skill_match": 1.0,
        "mode": "offline",
        "prize_pool_inr": 90000,
    },
]

BY_ID = {item["id"]: item for item in OPPORTUNITIES}


def now():
    return datetime.now(timezone.utc)


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


def is_open(opportunity):
    return now() < datetime.fromisoformat(opportunity["deadline"].replace("Z", "+00:00"))


def public_view(opportunity):
    seats_left = opportunity["seats_total"] - opportunity["seats_taken"]
    return {
        "id": opportunity["id"],
        "title": opportunity["title"],
        "mode": opportunity["mode"],
        "seats_total": opportunity["seats_total"],
        "seats_taken": opportunity["seats_taken"],
        "seats_left": seats_left,
        "deadline": opportunity["deadline"],
        "open": is_open(opportunity),
        "eligible_years": opportunity["eligible_years"],
        "required_skills": opportunity["required_skills"],
        "min_skill_match": opportunity["min_skill_match"],
        "prize_pool_inr": opportunity["prize_pool_inr"],
    }


def evaluate_eligibility(opportunity, team_size, year, skills):
    """Returns (eligible: bool, reason: str, details: dict)."""
    seats_left = opportunity["seats_total"] - opportunity["seats_taken"]
    details = {
        "seats_left": seats_left,
        "team_size": team_size,
        "deadline": opportunity["deadline"],
        "open": is_open(opportunity),
    }

    if not is_open(opportunity):
        return False, "deadline_passed", details

    if team_size > seats_left:
        details["seats_required"] = team_size
        return False, "insufficient_seats", details

    years = opportunity["eligible_years"]
    if not years["min"] <= year <= years["max"]:
        details["allowed_years"] = years
        return False, "year_not_eligible", details

    required = [s.lower() for s in opportunity["required_skills"]]
    matched = sorted({s.lower() for s in skills} & set(required))
    ratio = opportunity["min_skill_match"]
    needed = -(-len(required) * int(ratio * 100) // 100)  # ceil
    details["matched_skills"] = matched
    details["skills_needed"] = needed
    if len(matched) < needed:
        return False, "skill_mismatch", details

    return True, "eligible", details


@app.get("/health")
def health():
    return jsonify(
        service="opportunity-service",
        status="ok",
        opportunities=len(OPPORTUNITIES),
        open_now=sum(1 for item in OPPORTUNITIES if is_open(item)),
    )


@app.get("/metrics")
def metrics():
    return jsonify(
        service="opportunity-service",
        cpu_seconds=round(cpu_seconds(), 4),
        memory_peak_bytes=memory_bytes(peak=True),
        memory_current_bytes=memory_bytes(),
        rss_bytes=rss_bytes(),
    )


@app.get("/opportunities")
def list_opportunities():
    time.sleep(IO_DELAY)
    return jsonify(
        count=len(OPPORTUNITIES),
        opportunities=[public_view(item) for item in OPPORTUNITIES],
    )


@app.get("/opportunities/<opportunity_id>")
def get_opportunity(opportunity_id):
    time.sleep(IO_DELAY)
    opportunity = BY_ID.get(opportunity_id)
    if opportunity is None:
        return jsonify(error="not_found", opportunity_id=opportunity_id), 404
    return jsonify(public_view(opportunity))


@app.post("/opportunities/<opportunity_id>/check")
def check(opportunity_id):
    started = time.perf_counter()
    time.sleep(IO_DELAY)
    opportunity = BY_ID.get(opportunity_id)
    if opportunity is None:
        return jsonify(error="not_found", opportunity_id=opportunity_id), 404

    body = request.get_json(silent=True) or {}
    team_size = int(body.get("team_size", 1))
    year = int(body.get("year", 1))
    skills = body.get("skills") or []

    eligible, reason, details = evaluate_eligibility(opportunity, team_size, year, skills)

    if eligible and RESERVE_SEATS:
        opportunity["seats_taken"] += team_size

    payload = {
        "opportunity_id": opportunity_id,
        "title": opportunity["title"],
        "eligible": eligible,
        "reason": reason,
        "check_ms": round((time.perf_counter() - started) * 1000, 2),
        "details": details,
    }
    return jsonify(payload), (200 if eligible else 409)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)