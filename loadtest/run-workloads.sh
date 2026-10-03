#!/usr/bin/env bash
# Runs workloads W1..W5 (concurrency 1,2,4,8,16) one at a time.
#
# For every workload it writes:
#   results/load_test_outputs/W{n}.txt    raw load tool output (latency, ok/failed counts)
#   results/load_test_outputs/W{n}.json   machine readable version of the same
#   results/docker_stats/W{n}.csv         docker stats samples taken during the workload
#   results/docker_stats/cpu_metrics.csv  exact CPU seconds / peak RSS per container,
#                                         read from each service's /metrics endpoint
#                                         before and after the workload
#
# Usage: ./run-workloads.sh [requests_per_workload]
#   KEEP_CONTAINERS=1 ./run-workloads.sh 200    # do not restart between workloads
set -euo pipefail

REQUESTS="${1:-200}"
PYTHON="${PYTHON:-python3}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LOAD_DIR="$ROOT/results/load_test_outputs"
STATS_DIR="$ROOT/results/docker_stats"

TARGETS=(
  "registration-service:http://localhost:5001"
  "opportunity-service:http://localhost:5002"
  "evaluation-service:http://localhost:5003"
)

wait_healthy() {
  local deadline=$((SECONDS + 120))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if curl -sf http://localhost:5001/health | grep -q '"ok"' &&
       curl -sf http://localhost:5002/health | grep -q '"ok"' &&
       curl -sf http://localhost:5003/health | grep -q '"ok"'; then
      return 0
    fi
    sleep 2
  done
  return 1
}

# docker stats samples, one snapshot roughly every 2s (kept as the artefact the
# manual asks for; the exact numbers come from the /metrics endpoints)
sample_stats() {
  local file="$1"
  while true; do
    docker stats --no-stream \
      --format "$(date +%H:%M:%S),{{.Name}},{{.CPUPerc}},{{.MemPerc}},{{.MemUsage}}" \
      >>"$file" 2>/dev/null || true
    sleep 1
  done
}

# usage:$1 container name, $2 base url -> "<cpu_seconds> <peak_bytes> <current_bytes>"
read_metrics() {
  curl -sf "$2/metrics" |
    "$PYTHON" -c 'import json,sys; m=json.load(sys.stdin); print(m["cpu_seconds"], m["memory_peak_bytes"], m["memory_current_bytes"])'
}

echo "waiting for the stack to be up..."
wait_healthy || { echo "stack is not healthy, run 'docker compose up -d --build' first" >&2; exit 1; }

# only wipe previous results once the stack is confirmed up
rm -rf "$LOAD_DIR" "$STATS_DIR"
mkdir -p "$LOAD_DIR" "$STATS_DIR"
METRICS_FILE="$STATS_DIR/cpu_metrics.csv"
echo "workload,container,cpu_seconds_before,cpu_seconds_after,cpu_seconds_used,wall_seconds,cpu_percent,memory_peak_mb" \
  >"$METRICS_FILE"

index=1
for level in 1 2 4 8 16; do
  name="W$index"
  echo
  echo "===== $name : concurrency $level, $REQUESTS requests ====="

  if [ "${KEEP_CONTAINERS:-0}" != "1" ]; then
    # restart all three: cgroup memory.peak is a high-water mark that never
    # resets, so a service that keeps running would report its peak across
    # every earlier workload instead of this one.
    echo "restarting all services so this workload starts clean..."
    docker compose restart >/dev/null
    wait_healthy || { echo "$name: services did not become healthy" >&2; exit 1; }
    sleep 3
  fi

  stats_file="$STATS_DIR/$name.csv"
  echo "timestamp,container,cpu_percent,mem_percent,mem_usage" >"$stats_file"
  sample_stats "$stats_file" &
  sampler_pid=$!

  before_file=$(mktemp)
  for target in "${TARGETS[@]}"; do
    container="${target%%:*}"
    base="${target##*:}"
    echo "$container $(read_metrics "$container" "$base")" >>"$before_file"
  done

  wall_start=$(date +%s.%N)

  set +e
  "$PYTHON" loadtest/loadtest.py \
    --requests "$REQUESTS" --levels "$level" \
    --json-out "$LOAD_DIR/$name.json" 2>&1 | tee "$LOAD_DIR/$name.txt"
  load_exit=${PIPESTATUS[0]}
  set -e

  kill "$sampler_pid" 2>/dev/null || true
  wait "$sampler_pid" 2>/dev/null || true

  if [ "$load_exit" -ne 0 ]; then
    echo "$name: loadtest.py exited with $load_exit" >&2
    exit "$load_exit"
  fi

  wall_end=$(date +%s.%N)

  for target in "${TARGETS[@]}"; do
    container="${target%%:*}"
    base="${target##*:}"
    read -r cpu_before peak_before current_before \
      <<<"$(grep "^$container " "$before_file" | awk '{print $2, $3, $4}')"
    read -r cpu_after peak_after current_after \
      <<<"$(read_metrics "$container" "$base")"

    echo "$name,$container,$cpu_before,$cpu_after,$cpu_before,$cpu_after,$wall_start,$wall_end,$peak_after" \
      >>"$METRICS_FILE"
  done

  "$PYTHON" - "$name" "$METRICS_FILE" "$wall_start" "$wall_end" <<'PY'
import csv, sys
name, path, wall_start, wall_end = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4])
rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
wall = round(wall_end - wall_start, 3)
for row in rows:
    if row["workload"] != name:
        continue
    used = float(row["cpu_seconds_after"]) - float(row["cpu_seconds_before"])
    percent = round(used / wall * 100, 2)
    peak_mb = round(int(row["memory_peak_bytes"]) / 1024 / 1024, 2)
    row["cpu_seconds_used"] = round(used, 3)
    row["wall_seconds"] = wall
    row["cpu_percent"] = percent
    row["memory_peak_mb"] = peak_mb
    print(f"  {row['container']:<22} CPU {percent:>7}% "
          f"({used:>6} cpu-s / {wall:>5} s)   peak RSS {peak_mb:>7} MB")
with open(path, "w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=[
        "workload", "container", "cpu_seconds_before", "cpu_seconds_after",
        "cpu_seconds_used", "wall_seconds", "cpu_percent",
        "memory_peak_bytes", "memory_peak_mb"])
    writer.writeheader()
    writer.writerows(rows)
PY

  rm -f "$before_file"
  index=$((index + 1))
done

echo
echo "all workloads finished. now build the deliverables:"
echo "  python3 report/make-table.py     -> results/observation_table.md / .csv"
echo "  python3 report/make-graphs.py    -> results/graphs/*.png"