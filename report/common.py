"""Shared loading of the workload results.

Reads what loadtest/run-workloads.* produced:
    results/load_test_outputs/W<n>.json    one file per workload
    results/docker_stats/cpu_metrics.csv   exact CPU seconds / peak RSS per container
    results/docker_stats/W<n>.csv          sampled 'docker stats' output (kept as evidence)
"""
import csv
import json
import pathlib

SERVICE_ORDER = [
    "registration-service",
    "opportunity-service",
    "evaluation-service",
]

STAGE_LABELS = {
    "opportunity_check_ms": "Service 2 opp check",
    "evaluation_ms": "Service 3 evaluate",
    "notify_ms": "Service 3 notify",
    "total_ms": "Service 1 total",
}


class Results:
    def __init__(self, workloads, metrics, sampled):
        self.workloads = workloads        # list of dicts, ordered W1..W5
        self.metrics = metrics            # {workload: {container: {...}}}
        self.sampled = sampled            # {workload: {container: {"cpu_peak","mem_peak","mem_usage_last"}}}

    @property
    def concurrencies(self):
        return [w["concurrency"] for w in self.workloads]

    def busiest_service(self, workload):
        """Container with the highest average CPU% in that workload."""
        rows = self.metrics.get(workload, {})
        if not rows:
            return None, 0.0
        name = max(rows, key=lambda key: rows[key]["cpu_percent"])
        return name, rows[name]["cpu_percent"]

    def max_cpu_overall(self):
        best = ("", 0.0)
        for workload, rows in self.metrics.items():
            for name, row in rows.items():
                if row["cpu_percent"] > best[1]:
                    best = (f"{name} ({workload})", row["cpu_percent"])
        return best

    def max_memory_overall(self):
        best = ("", 0.0)
        for workload, rows in self.metrics.items():
            for name, row in rows.items():
                if row["memory_peak_mb"] > best[1]:
                    best = (f"{name} ({workload})", row["memory_peak_mb"])
        return best


def _read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_results(results_dir="results"):
    root = pathlib.Path(results_dir)
    load_dir = root / "load_test_outputs"
    stats_dir = root / "docker_stats"

    workloads = []
    for path in sorted(load_dir.glob("W*.json")):
        name = path.stem
        payload = json.loads(path.read_text(encoding="utf-8"))
        row = dict(payload["rows"][0])
        row["workload"] = name
        workloads.append(row)
    workloads.sort(key=lambda row: row["workload"])

    metrics = {}
    metrics_path = stats_dir / "cpu_metrics.csv"
    if metrics_path.exists():
        for row in _read_csv(metrics_path):
            metrics.setdefault(row["workload"], {})[row["container"]] = {
                "cpu_seconds": float(row["cpu_seconds_used"]),
                "wall_seconds": float(row["wall_seconds"]),
                "cpu_percent": float(row["cpu_percent"]),
                "memory_peak_mb": float(row["memory_peak_mb"]),
            }

    sampled = {}
    for path in sorted(stats_dir.glob("W*.csv")):
        name = path.stem
        rows = _read_csv(path)
        table = {}
        for row in rows:
            container = (row.get("container") or "").strip()
            if not container:
                continue
            cpu = _percent(row.get("cpu_percent"))
            mem_pct = _percent(row.get("mem_percent"))
            entry = table.setdefault(
                container,
                {"cpu_peak": 0.0, "mem_peak": 0.0, "mem_usage_last": "", "samples": 0},
            )
            entry["samples"] += 1
            entry["cpu_peak"] = max(entry["cpu_peak"], cpu)
            entry["mem_peak"] = max(entry["mem_peak"], mem_pct)
            if row.get("mem_usage"):
                entry["mem_usage_last"] = row["mem_usage"].strip()
        sampled[name] = table

    return Results(workloads, metrics, sampled)


def _percent(text):
    if text is None:
        return 0.0
    digits = "".join(ch for ch in str(text) if ch.isdigit() or ch == ".")
    try:
        return float(digits)
    except ValueError:
        return 0.0


def format_markdown_table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)