"""Plots the four performance graphs required by the lab manual.

Writes into results/graphs/:
    avg_response_time.png   average response time vs concurrent requests
    throughput.png          throughput vs concurrent requests
    cpu_utilization.png     CPU utilization per container vs concurrent requests
    memory_utilization.png  memory utilization per container vs concurrent requests

Usage:  python report/make-graphs.py [--results-dir results]
"""
import argparse
import pathlib
import sys

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from common import SERVICE_ORDER, load_results

COLORS = {
    "registration-service": "#c0392b",
    "opportunity-service": "#2980b9",
    "evaluation-service": "#27ae60",
}
STYLE = {
    "grid": {"color": "#dddddd", "linewidth": 0.8},
    "spines": {"top": False, "right": False},
}


def style_axis(axis):
    axis.grid(True, **STYLE["grid"])
    axis.set_axisbelow(True)
    for side in ("top", "right"):
        axis.spines[side].set_visible(False)
    axis.set_xticks([1, 2, 4, 8, 16])
    axis.set_xlabel("Concurrent requests")


def save(figure, path):
    figure.tight_layout()
    figure.savefig(path, dpi=300)
    plt.close(figure)
    print(f"written: {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", default="results")
    args = parser.parse_args()

    results = load_results(args.results_dir)
    if not results.workloads:
        raise SystemExit(
            f"no workload results found in {args.results_dir}/load_test_outputs - "
            "run loadtest/run-workloads.ps1 (or run-workloads.sh) first"
        )

    graph_dir = pathlib.Path(args.results_dir) / "graphs"
    graph_dir.mkdir(parents=True, exist_ok=True)

    concurrency = results.concurrencies

    # 1) average response time -------------------------------------------------
    figure, axis = plt.subplots(figsize=(7, 4.5))
    axis.plot(concurrency, [w["avg_ms"] for w in results.workloads],
              marker="o", color="#c0392b", linewidth=2, label="average")
    axis.plot(concurrency, [w["p95_ms"] for w in results.workloads],
              marker="s", color="#7f8c8d", linestyle="--", linewidth=1.5, label="p95")
    axis.set_ylabel("Response time (ms)")
    axis.set_title("Average response time vs concurrent requests")
    axis.legend()
    style_axis(axis)
    save(figure, graph_dir / "avg_response_time.png")

    # 2) throughput ------------------------------------------------------------
    figure, axis = plt.subplots(figsize=(7, 4.5))
    axis.plot(concurrency, [w["rps"] for w in results.workloads],
              marker="o", color="#2980b9", linewidth=2)
    axis.set_ylabel("Throughput (requests/second)")
    axis.set_title("Throughput vs concurrent requests")
    style_axis(axis)
    save(figure, graph_dir / "throughput.png")

    # 3) CPU utilization -------------------------------------------------------
    figure, axis = plt.subplots(figsize=(7, 4.5))
    for service in SERVICE_ORDER:
        values = [
            results.metrics.get(w["workload"], {}).get(service, {}).get("cpu_percent", 0.0)
            for w in results.workloads
        ]
        if any(values):
            axis.plot(concurrency, values, marker="o", linewidth=2,
                      color=COLORS[service], label=service)
    axis.set_ylabel("Average CPU (% of one core)")
    axis.set_title("CPU utilization per container vs concurrent requests")
    axis.legend()
    style_axis(axis)
    save(figure, graph_dir / "cpu_utilization.png")

    # 4) memory utilization ----------------------------------------------------
    figure, axis = plt.subplots(figsize=(7, 4.5))
    for service in SERVICE_ORDER:
        values = [
            results.metrics.get(w["workload"], {}).get(service, {}).get("memory_peak_mb", 0.0)
            for w in results.workloads
        ]
        if any(values):
            axis.plot(concurrency, values, marker="o", linewidth=2,
                      color=COLORS[service], label=service)
    axis.set_ylabel("Peak memory (MB)")
    axis.set_title("Memory utilization per container vs concurrent requests")
    axis.legend()
    style_axis(axis)
    save(figure, graph_dir / "memory_utilization.png")


if __name__ == "__main__":
    main()