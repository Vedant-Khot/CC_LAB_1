# Performance Observation Table

Measured with `loadtest/run-workloads` on 300 requests per workload, POST /register through all three services.

## 1. Observation table

| Workload | Concurrency | Avg Response Time (ms) | Throughput (rps) | Failed | CPU % | Memory (MB) |
|---|---|---|---|---|---|---|
| W1 | 1 | 109.35 | 9.13 | 0 | 39.13 | 56.86 |
| W2 | 2 | 111.41 | 17.89 | 0 | 56.01 | 57.24 |
| W3 | 4 | 154.98 | 25.65 | 0 | 87.12 | 57.87 |
| W4 | 8 | 267.33 | 28.80 | 0 | 93.93 | 57.61 |
| W5 | 16 | 471.38 | 33.12 | 0 | 98.79 | 57.64 |

* `CPU %` is the highest average CPU consumption of the three containers during that workload, measured from each container's cgroup (`/metrics` endpoint), not sampled.
* `Memory (MB)` is the highest peak RSS (`memory.peak`) of the three containers.
* `Failed` counts every request that did not return HTTP 201.

## 2. Per service CPU and memory

| Workload | Service | Avg CPU % | CPU seconds used | Wall (s) | Peak RSS (MB) | Sampled peak CPU % | Sampled peak MEM % | CPU ms / request |
|---|---|---|---|---|---|---|---|---|
| W1 | registration-service | 36.06 | 12.876 | 35.705 | 56.86 | 53.31 | 16.92 | 42.92 |
| W1 | opportunity-service | 20.27 | 7.236 | 35.705 | 52.92 | 38.76 | 15.75 | 24.12 |
| W1 | evaluation-service | 39.13 | 13.972 | 35.705 | 52.79 | 58.10 | 16.03 | 46.57 |
| W2 | registration-service | 51.75 | 10.007 | 19.339 | 57.24 | 77.22 | 16.77 | 33.36 |
| W2 | opportunity-service | 24.87 | 4.810 | 19.339 | 52.98 | 45.21 | 15.05 | 16.03 |
| W2 | evaluation-service | 56.01 | 10.831 | 19.339 | 53.46 | 68.56 | 15.12 | 36.10 |
| W3 | registration-service | 78.64 | 10.303 | 13.102 | 57.87 | 170.40 | 21.12 | 34.34 |
| W3 | opportunity-service | 35.92 | 4.706 | 13.102 | 53.10 | 124.26 | 19.47 | 15.69 |
| W3 | evaluation-service | 87.12 | 11.415 | 13.102 | 53.41 | 183.64 | 20.17 | 38.05 |
| W4 | registration-service | 84.16 | 11.585 | 13.765 | 57.61 | 137.99 | 16.87 | 38.62 |
| W4 | opportunity-service | 40.94 | 5.636 | 13.765 | 53.13 | 142.25 | 19.80 | 18.79 |
| W4 | evaluation-service | 93.93 | 12.929 | 13.765 | 53.48 | 141.50 | 15.23 | 43.10 |
| W5 | registration-service | 98.79 | 10.905 | 11.039 | 57.64 | 196.11 | 22.52 | 36.35 |
| W5 | opportunity-service | 45.12 | 4.981 | 11.039 | 53.05 | 100.31 | 15.04 | 16.60 |
| W5 | evaluation-service | 96.80 | 10.686 | 11.039 | 53.13 | 237.55 | 19.69 | 35.62 |

## 3. Latency percentiles

| Workload | Concurrency | Avg (ms) | p50 (ms) | p95 (ms) | p99 (ms) | Max (ms) |
|---|---|---|---|---|---|---|
| W1 | 1 | 109.35 | 100.27 | 160.32 | 192.43 | 205.27 |
| W2 | 2 | 111.41 | 104.24 | 171.14 | 195.27 | 219.70 |
| W3 | 4 | 154.98 | 147.53 | 239.30 | 280.66 | 293.98 |
| W4 | 8 | 267.33 | 251.29 | 466.27 | 539.52 | 642.69 |
| W5 | 16 | 471.38 | 431.68 | 731.13 | 777.25 | 818.35 |

## 4. Server side time per request (from timings_ms in the response)

| Workload | Concurrency | Service 2 opp check (ms) | Service 3 evaluate (ms) | Service 3 notify (ms) | Service 1 total (ms) |
|---|---|---|---|---|---|
| W1 | 1 | 15.24 | 55.97 | 14.70 | 87.98 |
| W2 | 2 | 15.13 | 56.35 | 15.65 | 89.57 |
| W3 | 4 | 19.96 | 75.31 | 22.10 | 121.09 |
| W4 | 8 | 30.65 | 118.43 | 60.03 | 214.62 |
| W5 | 16 | 39.26 | 111.19 | 54.96 | 215.58 |

## 5. Summary

- Throughput rises from 9.13 rps at concurrency 1 to a maximum of 33.12 rps at concurrency 16 (3.63x for 16x the concurrency).
- Average response time grows from 109.35 ms to 471.38 ms (4.31x).
- Highest CPU consumption: registration-service (W5) at 98.79% of one core.
- Highest peak memory: registration-service (W3) at 57.87 MB.
- Failed requests across all workloads: 0 of 1500.
