# Unstop-style Opportunity Platform — Microservices Performance Lab

An Unstop-style opportunity platform built as microservices behind the required
**Client → Service 1 → Service 2 / Service 3** pattern, plus a dashboard that can run the
performance workload against it.

Three services carry the graded workload; a fourth container (`web-ui`) serves the dashboard and
hosts the load generator, deliberately kept out of the measured services.

```
Client ──POST /register──► Registration Service (5001)   entry point, orchestrates the chain
                             │  1. eligibility check
                             ▼
                           Opportunity Service (5002)  deadline / seats / skills
                             │  2. score + rank   3. confirmation (simulated)
                             ▼
                           Evaluation Service (5003)  scoring + leaderboard

Dashboard (web-ui, 8080) ──► runs the workload against Registration Service,
                             polls /metrics on all three
```

| Container | Port | Role |
|---|---|---|
| `registration-service` | 5001 | Entry point. Validates the request, calls Service 2 then Service 3, stores registrations in memory. |
| `opportunity-service` | 5002 | 12 hackathons in memory. Answers *is it open / are there seats / is the student eligible*. |
| `evaluation-service` | 5003 | Scores the applicant (CPU heavy on purpose), keeps the per-hackathon leaderboard, "sends" the confirmation. |
| `web-ui` | 8080 | Dashboard and load-test driver. Not part of the measured system. |

## Endpoints

**Registration Service (5001)**
- `POST /register` — full chain; returns score, rank, notification id and per-stage timings
- `GET /registrations`, `GET /registrations/{id}`, `GET /health`, `GET /metrics`

**Opportunity Service (5002)**
- `GET /opportunities`, `GET /opportunities/{id}`
- `POST /opportunities/{id}/check` — `{team_size, year, skills}` → `200 eligible` / `409 reason`
- `GET /health`, `GET /metrics`

**Evaluation Service (5003)**
- `POST /evaluate`, `GET /leaderboard/{opportunity_id}`, `POST /notify`, `GET /stats`
- `GET /health`, `GET /metrics`

**Dashboard (8080)**
- `GET /` — the dashboard
- `GET /api/opportunities`, `POST /api/register`, `GET /api/registrations`, `GET /api/leaderboard/<id>`
- `POST /api/loadtest` — `{concurrency, requests}`; returns latency, throughput and per-container CPU
- `GET /api/loadtest/results`, `GET /api/overview`, `GET /health`, `GET /metrics`

### Example

```bash
curl -s -X POST http://localhost:5001/register \
  -H "Content-Type: application/json" \
  -d '{"student_name":"Asha","email":"asha@unstop-lab.test","college":"NIT Trichy",
       "year":3,"skills":["python","machine-learning","sql"],
       "opportunity_id":"hack-001","team_size":2}'
```

```json
{"registration_id":"reg-000001","status":"confirmed","score":53,"rank":1,"participants":1,
 "notification_id":"msg-reg-000001-1",
 "timings_ms":{"opportunity_check_ms":25.81,"evaluation_ms":43.34,"notify_ms":11.13,"total_ms":81.81}}
```

An ineligible request short-circuits at Service 2 and never reaches Service 3:

```json
{"error":"not_eligible","reason":"deadline_passed","opportunity_id":"hack-004", ...}
```

Rejection reasons: `deadline_passed`, `insufficient_seats`, `year_not_eligible`, `skill_mismatch`.

If a downstream service is down, the client gets a `502` naming the hop that broke, not a generic 500:

```json
{"error":"upstream_failure","stage":"opportunity-service","detail":"ConnectionError: ..."}
```

## Run it

```bash
docker compose up -d --build
docker compose ps          # wait until all four containers report healthy
```

Then open **http://localhost:8080**.

```bash
# Windows PowerShell
powershell -ExecutionPolicy Bypass -File loadtest\run-lab.ps1 -Requests 200

# Linux / macOS / WSL
./loadtest/run-lab.sh 200 "1,2,4,8,16"

# or drive the generator directly
python loadtest/loadtest.py --requests 200 --levels 1,2,4,8,16
```

`run-lab.*` samples `docker stats` in the background, runs the load test, then prints peak CPU
and memory per container. Output lands in `results/`.

Stop: `docker compose down`.

## Dashboard

| Panel | What it does |
|---|---|
| Register a student | one form, one `POST /register`; shows score, rank and the per-hop timings |
| Open hackathons | live from the opportunity service, with seats, deadline and required skills |
| Load testing | buttons for concurrency 1, 2, 4, 8, 16 (or all five in sequence) with live charts |
| Live container usage | CPU seconds and memory polled from each service's `/metrics` every 2 s |
| Registrations & leaderboard | latest registrations and the leaderboard for the selected hackathon |

Plain HTML/CSS/JS with inline SVG charts — no build step, no CDN, works offline.

The load generator runs **inside the `web-ui` container**, not inside one of the three measured
services: a generator sharing a container with the service under measurement would burn the very
CPU the measurement is trying to attribute. It imports the same `loadtest/loadtest.py` used for the
graded runs, so there is one implementation of the workload.

The dashboard is a demo and reporting aid, not part of the measured system. The graded table and
graphs still come from `loadtest/run-workloads.*` plus `report/make-table.py` and
`report/make-graphs.py`, because the numbers must not depend on a browser session.

## Results

Measured with `loadtest/run-workloads.ps1 -Requests 300`: 300 requests at each concurrency level,
all three containers restarted before each one, **1500 requests, 0 failed**.

| Workload | Concurrency | Avg response (ms) | Throughput (rps) | Failed | Peak CPU (%) | Peak memory (MB) |
|---|---|---|---|---|---|---|
| W1 | 1 | 109.35 | 9.13 | 0 | 39.13 | 56.86 |
| W2 | 2 | 111.41 | 17.89 | 0 | 56.01 | 57.24 |
| W3 | 4 | 154.98 | 25.65 | 0 | 87.12 | 57.87 |
| W4 | 8 | 267.33 | 28.80 | 0 | 93.93 | 57.61 |
| W5 | 16 | 471.38 | 33.12 | 0 | 98.79 | 57.64 |

Per container, at concurrency 16:

| Container | Avg CPU (%) | CPU ms / request | Peak RSS (MB) |
|---|---|---|---|
| registration-service | 98.79 | 36.35 | 57.64 |
| evaluation-service | 96.80 | 35.62 | 53.13 |
| opportunity-service | 45.12 | 16.60 | 53.05 |

Reading of it, in one paragraph: throughput rises 3.6x for 16x the clients and then flattens after
concurrency 8, while average latency grows 4.3x — clients are queueing, not being served. The
binding constraint is CPU on the two services every request touches; memory is flat at 53–58 MB
and never a factor. `evaluation-service` has the largest single-step *latency*, but
`registration-service` edges it on *total* CPU because it makes two outbound HTTP calls per request.
Full analysis, including a measurement of how much of the headline latency is the Docker Desktop
port-forwarding proxy rather than the application, is in [`report/report.md`](report/report.md).

## Push to Docker Hub

Image names come from two variables, so the same compose file builds locally and publishes:

```yaml
image: ${IMAGE_PREFIX:-unstop-lab}/unstop-lab-registration-service:${IMAGE_TAG:-latest}
```

```bash
# 1. log in (Docker Hub asks for your username and an access token).
#    Credentials go to the Docker CLI credential store, never into this repository.
docker login

# 2. set your namespace once
cp .env.example .env        # then edit: IMAGE_PREFIX=<yourhubusername>

# 3. build and push all four images
./publish.sh                                            # Linux / macOS
powershell -ExecutionPolicy Bypass -File publish.ps1     # Windows
```

Equivalent by hand:

```bash
IMAGE_PREFIX=<yourhubusername> docker compose build
IMAGE_PREFIX=<yourhubusername> docker compose push
# or in one step, without publishing locally:
IMAGE_PREFIX=<yourhubusername> docker compose build --push
```

One repository per container. This project is already published as:

```text
docker.io/vedantkhot112/unstop-lab-registration-service:latest   47 MB
docker.io/vedantkhot112/unstop-lab-opportunity-service:latest    46 MB
docker.io/vedantkhot112/unstop-lab-evaluation-service:latest     46 MB
docker.io/vedantkhot112/unstop-lab-web-ui:latest                 47 MB
```

`.env` in this repo already sets `IMAGE_PREFIX=vedantkhot112`, so the whole stack can be run from
the published images without building anything locally:

```bash
docker compose pull
docker compose up -d
docker compose ps
```

Notes:
- Repository names must be lowercase; Docker Hub creates them on first push under your namespace.
- Anonymous pulls are rate limited, so keep the images public if an evaluator has to pull them.
- `web-ui` builds with the repo root as its context so the image can copy `loadtest/loadtest.py`.

## Where the cost is

`POST /evaluate` does `HEAVY_ITERS` chained sha256 rounds plus a `HEAVY_SLEEP` pause (simulating
model inference), so it is the most expensive *single step* of the chain. It runs in one gunicorn
worker with threads, and because the work is pure Python it is GIL-bound, so extra threads buy no
throughput.

On CPU the ranking is closer than that suggests: Service 1 does two outbound HTTP calls per request
(`requests`, JSON encode/decode, Flask), which makes it the largest consumer once throughput is
high. Both effects are in `results/observation_table.md`; tune the knobs below and re-run to move
the balance.

| Variable | Service | Default | Meaning |
|---|---|---|---|
| `HEAVY_ITERS` | evaluation | `4000` | sha256 rounds per request (~18 ms) |
| `HEAVY_SLEEP` | evaluation | `0.03` | simulated inference (s) — costs latency, no CPU |
| `NOTIFY_DELAY` | evaluation | `0.005` | simulated e-mail send |
| `IO_DELAY` | opportunity | `0.005` | pretend DB read |
| `RESERVE_SEATS` | opportunity | `false` | if `true`, eligible checks consume seats, which breaks repeatable runs |

## Results pipeline

Nothing below is hand written: the harness records the run, then two scripts turn it into the
table and the graphs.

```bash
docker compose up -d --build

# 1. run the five workloads (300 requests each at concurrency 1, 2, 4, 8, 16)
powershell -ExecutionPolicy Bypass -File loadtest/run-workloads.ps1 -Requests 300   # Windows
./loadtest/run-workloads.sh 300                                                    # Linux / macOS

# 2. build the observation table and the four graphs
python report/make-table.py
python report/make-graphs.py
```

| Path | Contents |
|---|---|
| `results/load_test_outputs/W1..W5.txt` | raw load tool output: latency percentiles and the 201 / 409 / error counts |
| `results/load_test_outputs/W1..W5.json` | the same numbers, machine readable |
| `results/docker_stats/W1..W5.csv` | `docker stats` samples captured during each workload |
| `results/docker_stats/cpu_metrics.csv` | exact CPU seconds and peak RSS per container per workload |
| `results/observation_table.md` / `.csv` | the filled observation table, plus per-service detail |
| `results/graphs/*.png` | response time, throughput, CPU utilization, memory utilization |
| `report/report.md` | the written analysis and conclusion |
| `DEMO.md` | the five checkpoints, command by command |

### How CPU and memory are measured

`docker stats` samples roughly every 2 s, which is too coarse for a workload that lasts under 10 s:
the peak it reports is whichever sample happened to land on the busiest moment. So every service
also exposes `GET /metrics`, which reads the container's own cgroup:

```bash
curl -s http://localhost:5003/metrics
```

```json
{"service":"evaluation-service","cpu_seconds":13.367,"memory_peak_bytes":55984128.0,
 "memory_current_bytes":41168896.0,"rss_bytes":35729408.0}
```

The harness reads `/metrics` on all three containers immediately before and after each workload, so
`cpu_percent = (cpu_seconds_after - cpu_seconds_before) / wall_seconds` is the exact average CPU of
that container for that workload — the same definition `docker stats` uses, but measured instead of
sampled. Memory comes from cgroup `memory.peak`, the true high-water mark rather than the highest
sample. The sampled `docker stats` output is still recorded per workload as supporting evidence.

Because `memory.peak` never resets, the harness restarts **all three** services before each
workload; otherwise a service that keeps running reports its peak across every earlier run.

### Reading the load tool output

```
 conc  reqs   201  409  err  wall_s     rps   avg_ms   p50_ms   p95_ms   p99_ms   max_ms
    8   300   300    0    0  13.77   28.80   267.33   251.29   466.27   539.52   642.69
```

`201` is a confirmed registration (the whole chain ran), `409` is a request the opportunity service
rejected on eligibility, `err` is a timeout or connection failure. `Failed` in the observation table
is `reqs - 201`, so a `409` counts as failed.

## Repository layout

```text
registration-service/   app.py, Dockerfile, requirements.txt   (Service 1)
opportunity-service/    app.py, Dockerfile, requirements.txt   (Service 2)
evaluation-service/     app.py, Dockerfile, requirements.txt   (Service 3)
web-ui/                 app.py, Dockerfile, requirements.txt, static/
loadtest/               loadtest.py, run-workloads.*, run-lab.*
report/                 common.py, make-table.py, make-graphs.py, report.md
results/                load_test_outputs/, docker_stats/, graphs/, observation_table.*
docker-compose.yml      four services on a `lab` bridge network
DEMO.md                 the five checkpoints, command by command
```

## Notes / caveats

- Every service keeps state **in memory**, so each container runs **1 gunicorn worker with
  threads**. More workers would split `registrations` and the leaderboards across processes.
- `HEAVY_SLEEP` is a sleep, not real work: it inflates latency without burning CPU. The sha256 loop
  is the part that actually consumes CPU.
- Scores are deterministic per `registration_id`, but ranks shift between runs because requests
  complete out of order under concurrency.
- `loadtest.py` uses one keep-alive connection per worker thread, so it measures the services and
  not TCP setup through the Docker Desktop proxy.
- Compose caps memory at 256M per container but sets **no CPU limit**, so the cgroup numbers
  reflect real demand instead of a cap. Add a `cpus:` limit and the containers will sit at that
  limit, making the per-service CPU comparison meaningless.
- All four containers share the Docker Desktop VM's cores, so a busy host adds noise. Let the
  machine settle before a run and do not rebuild images immediately before measuring. Run-to-run
  variance is about 15 %.
- Absolute throughput is environment-bound: at concurrency 4 the same generator measured 25.65 rps
  from the Windows host, 43.40 rps from inside a container via the published port, and 51.89 rps
  over the internal network. Read `report/report.md` §3.3 before quoting a capacity number.
- `.gitattributes` fixes line endings per file type (CRLF default, LF for `.sh` and `Dockerfile`).
  If an editor rewrites a file with the wrong endings, git reports mixed line endings on the next
  commit; re-save it as CRLF and it goes away.
- `loadtest/run-lab.*` is the quick version (all levels in one pass, sampled stats only);
  `loadtest/run-workloads.*` is the graded version (one workload at a time, exact metrics).