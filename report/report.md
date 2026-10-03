# Unstop-style Opportunity Platform — Performance Report

Three microservices (`registration-service`, `opportunity-service`, `evaluation-service`) running in
Docker, exercised over HTTP through a single entry point and measured at five concurrency levels.

- **Workload:** `POST /register`, 300 requests per level, at concurrency 1, 2, 4, 8, 16
- **Levels:** W1–W5, each with all three containers restarted first so every level starts from
  identical, empty in-memory state
- **Measurements:** latency percentiles from the load generator; CPU and memory from each
  container's cgroup via its `/metrics` endpoint (`cpu.stat`, `memory.peak`), read immediately
  before and after each workload
- **Total:** 1500 requests, **0 failed**
- **Host:** Windows 11, Docker Desktop (WSL2), containers share the VM's cores, no CPU limits set

Reproduce with:

```bash
docker compose up -d --build
powershell -ExecutionPolicy Bypass -File loadtest/run-workloads.ps1 -Requests 300   # Windows
python report/make-table.py
python report/make-graphs.py
```

Generated artifacts: `results/observation_table.md`, `results/load_test_outputs/W1..W5.txt`,
`results/docker_stats/cpu_metrics.csv`, `results/graphs/*.png`.

---

## 1. Observation table

| Workload | Concurrency | Avg Response Time (ms) | Throughput (rps) | Failed | CPU % | Memory (MB) |
|---|---|---|---|---|---|---|
| W1 | 1 | 109.35 | 9.13 | 0 | 39.13 | 56.86 |
| W2 | 2 | 111.41 | 17.89 | 0 | 56.01 | 57.24 |
| W3 | 4 | 154.98 | 25.65 | 0 | 87.12 | 57.87 |
| W4 | 8 | 267.33 | 28.80 | 0 | 93.93 | 57.61 |
| W5 | 16 | 471.38 | 33.12 | 0 | 98.79 | 57.64 |

`CPU %` is the highest average CPU of the three containers in that workload; `Memory (MB)` the
highest peak RSS. Both are broken down per service in section 2.

### Per service CPU and memory

| Workload | Service | Avg CPU % | CPU seconds used | Wall (s) | Peak RSS (MB) | CPU ms / request |
|---|---|---|---|---|---|---|
| W1 | registration-service | 36.06 | 12.876 | 35.705 | 56.86 | 42.92 |
| W1 | opportunity-service | 20.27 | 7.236 | 35.705 | 52.92 | 24.12 |
| W1 | evaluation-service | 39.13 | 13.972 | 35.705 | 52.79 | 46.57 |
| W2 | registration-service | 51.75 | 10.007 | 19.339 | 57.24 | 33.36 |
| W2 | opportunity-service | 24.87 | 4.810 | 19.339 | 52.98 | 16.03 |
| W2 | evaluation-service | 56.01 | 10.831 | 19.339 | 53.46 | 36.10 |
| W3 | registration-service | 78.64 | 10.303 | 13.102 | 57.87 | 34.34 |
| W3 | opportunity-service | 35.92 | 4.706 | 13.102 | 53.10 | 15.69 |
| W3 | evaluation-service | 87.12 | 11.415 | 13.102 | 53.41 | 38.05 |
| W4 | registration-service | 84.16 | 11.585 | 13.765 | 57.61 | 38.62 |
| W4 | opportunity-service | 40.94 | 5.636 | 13.765 | 53.13 | 18.79 |
| W4 | evaluation-service | 93.93 | 12.929 | 13.765 | 53.48 | 43.10 |
| W5 | registration-service | 98.79 | 10.905 | 11.039 | 57.64 | 36.35 |
| W5 | opportunity-service | 45.12 | 4.981 | 11.039 | 53.05 | 16.60 |
| W5 | evaluation-service | 96.80 | 10.686 | 11.039 | 53.13 | 35.62 |

### Latency percentiles

| Workload | Concurrency | Avg (ms) | p50 (ms) | p95 (ms) | p99 (ms) | Max (ms) |
|---|---|---|---|---|---|---|
| W1 | 1 | 109.35 | 100.27 | 160.32 | 192.43 | 205.27 |
| W2 | 2 | 111.41 | 104.24 | 171.14 | 195.27 | 219.70 |
| W3 | 4 | 154.98 | 147.53 | 239.30 | 280.66 | 293.98 |
| W4 | 8 | 267.33 | 251.29 | 466.27 | 539.52 | 642.69 |
| W5 | 16 | 471.38 | 431.68 | 731.13 | 777.25 | 818.35 |

### Server-side time per request (from `timings_ms` in the response)

| Workload | Concurrency | Service 2 opp check (ms) | Service 3 evaluate (ms) | Service 3 notify (ms) | Service 1 total (ms) |
|---|---|---|---|---|---|
| W1 | 1 | 15.24 | 55.97 | 14.70 | 87.98 |
| W2 | 2 | 15.13 | 56.35 | 15.65 | 89.57 |
| W3 | 4 | 19.96 | 75.31 | 22.10 | 121.09 |
| W4 | 8 | 30.65 | 118.43 | 60.03 | 214.62 |
| W5 | 16 | 39.26 | 111.19 | 54.96 | 215.58 |

---

## 2. Graphs

![Average response time](results/graphs/avg_response_time.png)

![Throughput](results/graphs/throughput.png)

![CPU utilization](results/graphs/cpu_utilization.png)

![Memory utilization](results/graphs/memory_utilization.png)

---

## 3. Analysis

### 3.1 How response time and throughput changed as load increased

Throughput rose from **9.13 rps** at concurrency 1 to **33.12 rps** at concurrency 16 — a 3.6x
gain for 16x the clients. The gain is strongly sub-linear, and the curve flattens visibly at the
top end:

| Concurrency | Throughput | Marginal gain |
|---|---|---|
| 1 → 2 | 9.13 → 17.89 rps | +96 % |
| 2 → 4 | 17.89 → 25.65 rps | +43 % |
| 4 → 8 | 25.65 → 28.80 rps | +12 % |
| 8 → 16 | 28.80 → 33.12 rps | +15 % |

Each doubling of concurrency buys less than the previous one, and past concurrency 8 the system is
effectively saturated: doubling the clients from 8 to 16 added 15 % throughput but **doubled the
average response time** (267 ms → 471 ms) and increased p95 from 466 ms to 731 ms.

Average response time grew from 109 ms to 471 ms (**4.3x**) while throughput grew 3.6x. That is the
textbook saturation signature: the extra clients are not creating new work capacity, they are
queueing. By Little's law, at concurrency 16 the system holds 16 requests in flight against a
capacity of ~33/s, which predicts ~480 ms per request — almost exactly the 471 ms measured.

Concurrency 1 → 2 is the only step where latency is flat (109 → 111 ms), because one client cannot
keep a single-threaded service busy; that headroom is what the second client absorbs for free.

### 3.2 Which microservice used the most CPU and memory

**CPU — `registration-service` (98.79 % of one core at W5), with `evaluation-service` effectively
tied (96.80 %). `opportunity-service` used far less (45.12 %).**

Both leaders are close to one full core at concurrency 16, so both are effectively saturated. The
per-request CPU cost explains why:

- `registration-service` spends ~36 ms of CPU per request. It is the only container on a published
  port and it makes **two outbound HTTP calls per request** with the `requests` library (socket
  setup, JSON encode/decode twice, TLS-free but still full HTTP parsing), plus Flask request
  handling and storing the registration.
- `evaluation-service` spends ~36 ms of CPU per request, almost all of it the 4000 chained sha256
  rounds in the scoring function. Note the deliberate trap in its config: `HEAVY_SLEEP=0.03`
  inflates *latency* by 30 ms but consumes **no CPU**, so the service that looks like the heaviest
  step in the latency table is only tied for heaviest in CPU.
- `opportunity-service` spends ~16 ms per request — a dictionary lookup, four rules and a 5 ms
  simulated DB read. It is the cheapest service by a factor of two, because the `409` short-circuit
  means it is only ever asked one question.

**Memory — `registration-service`, 57.87 MB peak RSS.** It is also the only service whose memory
tracks its workload: it retains every `registrations` entry (300 per run, ~431 bytes of JSON each),
whereas `opportunity-service` (53.1 MB) and `evaluation-service` (53.1–53.5 MB) hold only a fixed
12-hackathon catalogue and one leaderboard per hackathon. All three are flat within ~1 MB across
the whole concurrency range, and all sit far below the 256 MB compose limit, so **memory is not a
constraint in this workload** — the growth is a Python interpreter floor, not application state.

### 3.3 Degradation, failures, and their likely cause

**No request failed.** All 1500 requests returned HTTP 201: zero `409`, zero connection errors, zero
timeouts, and p99 never exceeded 0.83x the maximum. There was no breakdown, only graceful
degradation.

The degradation that did occur had three contributing causes:

1. **Both busy services reached ~1 full core** (registration 98.79 %, evaluation 96.80 %) at
   concurrency 16. Once a core is saturated, extra requests queue instead of being served, which is
   exactly the latency curve observed.
2. **Threads cannot help, because the work is GIL-bound.** Each container runs one gunicorn worker
   with 8 threads (required, since state is in memory). The sha256 loop and JSON parsing are pure
   Python, so the interpreter lock serialises them: raising `--threads` would add context switching,
   not throughput. This is why concurrency 16 bought only +15 % throughput over concurrency 8.
3. **Part of the measured latency is not in the services at all.** The services' own `total_ms` at
   W5 is 215.58 ms while the client measured 471.38 ms — **54 % of the observed response time sits
   in the client↔container hop**, which on Windows means Docker Desktop's port-forwarding proxy in
   the WSL2 VM. That proxy is itself a contention point and grew super-linearly (21 ms of overhead
   at W1, 255 ms at W5). A good part of the 33 rps ceiling is therefore an artefact of the
   measurement environment rather than of the application.

No degradation was seen in the tail distribution: the p99/avg ratio stayed between 1.65 and 1.83 for
every level, so requests slowed down together rather than a few stragglers dominating.

**Run-to-run variance** was about 15 % (a repeat of W1 measured 10.88 rps versus 9.13 rps here),
which is expected when three containers share a VM whose cores are also serving the host. Numbers
should be read as trends across levels, not as absolute capacity.

### 3.4 Conclusion

The chain behaves like a well-behaved system approaching its capacity limit: it scales nearly
linearly to concurrency 2–4, then flattens, converting additional clients into queueing delay rather
than throughput, with zero errors throughout. The binding constraint is **CPU on the two services
that touch every request** — the registration front door and the scoring service — not memory, not
the eligibility check, and not the network between containers.

Adding clients or threads is therefore not a fix. The fixes that would actually raise capacity:

- **Scale the front door horizontally.** It is the single highest consumer per request, does the
  least amount of domain work, and is trivially stateless apart from the registration store — moving
  that store to a shared database would allow replicas behind a load balancer.
- **Take the scoring off the request path** (queue + async consumer) or cache it: scores are a pure
  function of the applicant, so they can be pre-computed, and `HEAVY_SLEEP` shows the shape of that
  cost without the CPU.
- **Release the GIL** by moving scoring into a native library, a compiled extension, or a separate
  process pool with a shared store, so `--threads` becomes useful.
- **Eliminate the proxy hop** by running the stack on a Linux host or behind a single published
  entry point, which would remove the 54 % latency overhead seen at W5.

Note that the ranking of services is workload-dependent: `evaluation-service` has the largest
single-step latency at every level, and at lower throughput (earlier runs on this machine) it also
led on total CPU. The honest statement is that it is tied with the registration service on CPU,
while being the most expensive step in latency terms.

---

## 4. Limitations

- Single gunicorn worker per container, mandated by the in-memory state (registrations,
  leaderboards). More workers would split that state across processes.
- No CPU limits in compose, so the CPU percentages are real demand; adding a `cpus:` cap would pin
  containers at the cap and invalidate the per-service comparison.
- 300 requests per level, single run per level. With ~15 % variance, medians of repeated runs would
  tighten the numbers for a formal submission.
- Measured on Windows Docker Desktop; section 3.3 quantifies how much of the latency that adds.
- `HEAVY_SLEEP` is a sleep, so it contributes latency but no CPU — deliberately, to separate the
  two effects.