#!/usr/bin/env bash
# Runs the load test at each concurrency level while sampling docker stats.
# Usage: ./run-lab.sh [total_requests_per_level] [levels]
#   ./run-lab.sh 200 "1,2,4,8,16"
set -euo pipefail

REQUESTS="${1:-200}"
LEVELS="${2:-1,2,4,8,16}"
INTERVAL="${STATS_INTERVAL_SECONDS:-2}"
PYTHON="${PYTHON:-python3}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

RESULTS_DIR="$ROOT/results"
mkdir -p "$RESULTS_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
STATS_FILE="$RESULTS_DIR/docker-stats-$STAMP.csv"
JSON_FILE="$RESULTS_DIR/results-$STAMP.json"

echo "timestamp,container,cpu_percent,mem_percent,mem_usage" >"$STATS_FILE"
echo "Sampling docker stats -> $STATS_FILE"

sample_stats() {
  while true; do
    docker stats --no-stream \
      --format "$(date +%H:%M:%S),{{.Name}},{{.CPUPerc}},{{.MemPerc}},{{.MemUsage}}" \
      >>"$STATS_FILE" 2>/dev/null || true
    sleep "$INTERVAL"
  done
}

sample_stats &
SAMPLER_PID=$!
trap 'kill "$SAMPLER_PID" 2>/dev/null || true' EXIT

sleep 3
"$PYTHON" loadtest/loadtest.py \
  --requests "$REQUESTS" --levels "$LEVELS" --json-out "$JSON_FILE"

kill "$SAMPLER_PID" 2>/dev/null || true
wait "$SAMPLER_PID" 2>/dev/null || true

echo
echo "Peak resource usage per container:"
tail -n +2 "$STATS_FILE" | awk -F, '
  NF >= 4 {
    name = $2;
    gsub(/[^0-9.]/, "", $3); gsub(/[^0-9.]/, "", $4);
    if ($3 + 0 > cpu[name]) cpu[name] = $3 + 0;
    if ($4 + 0 > mem[name])  mem[name]  = $4 + 0;
    last[name] = $5;
  }
  END {
    for (name in cpu)
      printf "%-22s peak CPU %6s%%   peak MEM %6s%%   last %s\n",
             name, cpu[name], mem[name], last[name];
  }' | sort

echo
echo "Load results: $JSON_FILE"
echo "Raw stats:    $STATS_FILE"
echo "Evaluation service internal timings:"
curl -s http://localhost:5003/stats || true
echo