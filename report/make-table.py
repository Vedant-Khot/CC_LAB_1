"""Builds the observation table from the workload results.

Writes:
    results/observation_table.md            human readable, ready for the report
    results/observation_table.csv           the main table, opens in Excel
    results/observation_table_by_service.csv   per container CPU / memory detail

Usage:  python report/make-table.py [--results-dir results]
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from common import SERVICE_ORDER, STAGE_LABELS, format_markdown_table, load_results


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

    root = pathlib.Path(args.results_dir)
    root.mkdir(parents=True, exist_ok=True)

    # ---- main table: the columns the manual asks for -------------------------
    main_rows = []
    for workload in results.workloads:
        name = workload["workload"]
        service, cpu_percent = results.busiest_service(name)
        peak_mem = max(
            (row["memory_peak_mb"] for row in results.metrics.get(name, {}).values()),
            default=0.0,
        )
        successful = workload["ok"]
        failed = workload["requests"] - successful
        main_rows.append([
            name,
            workload["concurrency"],
            f"{workload['avg_ms']:.2f}",
            f"{workload['rps']:.2f}",
            failed,
            f"{cpu_percent:.2f}",
            f"{peak_mem:.2f}",
        ])
        del service

    # ---- per service detail --------------------------------------------------
    service_rows = []
    for workload in results.workloads:
        name = workload["workload"]
        for container in SERVICE_ORDER:
            row = results.metrics.get(name, {}).get(container)
            if row is None:
                continue
            sample = results.sampled.get(name, {}).get(container, {})
            service_rows.append([
                name,
                container,
                f"{row['cpu_percent']:.2f}",
                f"{row['cpu_seconds']:.3f}",
                f"{row['wall_seconds']:.3f}",
                f"{row['memory_peak_mb']:.2f}",
                f"{sample.get('cpu_peak', 0.0):.2f}",
                f"{sample.get('mem_peak', 0.0):.2f}",
                f"{row['cpu_seconds'] / workload['requests'] * 1000:.2f}",
            ])

    # ---- latency percentiles -------------------------------------------------
    latency_rows = [[
        workload["workload"],
        workload["concurrency"],
        f"{workload['avg_ms']:.2f}",
        f"{workload['p50_ms']:.2f}",
        f"{workload['p95_ms']:.2f}",
        f"{workload['p99_ms']:.2f}",
        f"{workload['max_ms']:.2f}",
    ] for workload in results.workloads]

    # ---- server side stage breakdown ----------------------------------------
    stage_rows = [[
        workload["workload"],
        workload["concurrency"],
        f"{workload['avg_stage_ms']['opportunity_check_ms']:.2f}",
        f"{workload['avg_stage_ms']['evaluation_ms']:.2f}",
        f"{workload['avg_stage_ms']['notify_ms']:.2f}",
        f"{workload['avg_stage_ms']['total_ms']:.2f}",
    ] for workload in results.workloads]

    busiest_name, busiest_cpu = results.max_cpu_overall()
    memory_name, memory_peak = results.max_memory_overall()
    best = max(results.workloads, key=lambda row: row["rps"])
    worst = max(results.workloads, key=lambda row: row["avg_ms"])
    first = results.workloads[0]

    main_table = format_markdown_table(
        ["Workload", "Concurrency", "Avg Response Time (ms)", "Throughput (rps)",
         "Failed", "CPU %", "Memory (MB)"],
        main_rows,
    )

    md = [
        "# Performance Observation Table",
        "",
        f"Measured with `loadtest/run-workloads` on {results.workloads[0]['requests']} requests "
        "per workload, POST /register through all three services.",
        "",
        "## 1. Observation table",
        "",
        main_table,
        "",
        "* `CPU %` is the highest average CPU consumption of the three containers during that "
        "workload, measured from each container's cgroup (`/metrics` endpoint), not sampled.",
        "* `Memory (MB)` is the highest peak RSS (`memory.peak`) of the three containers.",
        "* `Failed` counts every request that did not return HTTP 201.",
        "",
        "## 2. Per service CPU and memory",
        "",
        format_markdown_table(
            ["Workload", "Service", "Avg CPU %", "CPU seconds used", "Wall (s)",
             "Peak RSS (MB)", "Sampled peak CPU %", "Sampled peak MEM %",
             "CPU ms / request"],
            service_rows,
        ),
        "",
        "## 3. Latency percentiles",
        "",
        format_markdown_table(
            ["Workload", "Concurrency", "Avg (ms)", "p50 (ms)", "p95 (ms)", "p99 (ms)", "Max (ms)"],
            latency_rows,
        ),
        "",
        "## 4. Server side time per request (from timings_ms in the response)",
        "",
        format_markdown_table(
            ["Workload", "Concurrency", "Service 2 opp check (ms)", "Service 3 evaluate (ms)",
             "Service 3 notify (ms)", "Service 1 total (ms)"],
            stage_rows,
        ),
        "",
        "## 5. Summary",
        "",
        f"- Throughput rises from {first['rps']:.2f} rps at concurrency {first['concurrency']} "
        f"to a maximum of {best['rps']:.2f} rps at concurrency {best['concurrency']} "
        f"({best['rps'] / first['rps']:.2f}x for {best['concurrency'] / first['concurrency']:.0f}x "
        "the concurrency).",
        f"- Average response time grows from {first['avg_ms']:.2f} ms to "
        f"{worst['avg_ms']:.2f} ms ({worst['avg_ms'] / first['avg_ms']:.2f}x).",
        f"- Highest CPU consumption: {busiest_name} at {busiest_cpu:.2f}% of one core.",
        f"- Highest peak memory: {memory_name} at {memory_peak:.2f} MB.",
        f"- Failed requests across all workloads: "
        f"{sum(w['requests'] - w['ok'] for w in results.workloads)} of "
        f"{sum(w['requests'] for w in results.workloads)}.",
        "",
    ]

    (root / "observation_table.md").write_text("\n".join(md), encoding="utf-8")

    with open(root / "observation_table.csv", "w", encoding="utf-8") as handle:
        handle.write("Workload,Concurrency,Avg Response Time (ms),Throughput (rps),"
                     "Failed,CPU Percent,Memory MB\n")
        for row in main_rows:
            handle.write(",".join(str(cell) for cell in row) + "\n")

    with open(root / "observation_table_by_service.csv", "w", encoding="utf-8") as handle:
        handle.write("Workload,Service,Avg CPU Percent,CPU Seconds Used,Wall Seconds,"
                     "Peak RSS MB,Sampled Peak CPU Percent,Sampled Peak MEM Percent,"
                     "CPU ms per request\n")
        for row in service_rows:
            handle.write(",".join(str(cell) for cell in row) + "\n")

    print("\n".join(md))
    print(f"\nwritten: {root / 'observation_table.md'}")
    print(f"written: {root / 'observation_table.csv'}")
    print(f"written: {root / 'observation_table_by_service.csv'}")


if __name__ == "__main__":
    main()