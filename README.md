# Unstop-style Opportunity Platform — Microservices Performance Lab

Three independent microservices behind the required **Client -> Service 1 -> Service 2 / Service 3** pattern,
built so that one service is measurably the bottleneck.

```
Client ──POST /register──► Registration Service (5001)
                             │  1. eligibility check
                             ▼
                           Opportunity Service (5002)
                             │  2. score + rank   3. confirmation (simulated)
                             ▼
                           Evaluation Service (5003)  ◄── the bottleneck
```

| Service | Port | Responsibility |
|---|---|---|
| Registration Service | 5001 | Entry point. Validates the request, calls Service 2 then Service 3, stores the registration in memory. |
| Opportunity Service | 5002 | 12 hackathons in memory. Answers `is it open / are there seats / is the student eligible`. |
| Evaluation Service | 5003 | Scores the applicant (CPU heavy on purpose), maintains the per-hackathon leaderboard, "sends" the confirmation. |

## Endpoints

**Registration Service (5001)**
- `POST /register` — full chain, returns score, rank, notification id and per-stage timings
- `GET /registrations`, `GET /registrations/{id}`, `GET /health`, `GET /metrics`

**Opportunity Service (5002)**
- `GET /opportunities`, `GET /opportunities/{id}`
- `POST /opportunities/{id}/check` — `{team_size, year, skills}` → `200 eligible` / `409 reason`
- `GET /health`, `GET /metrics`

**Evaluation Service (5003)**
- `POST /evaluate`, `GET /leaderboard/{opportunity_id}`, `POST /notify`, `GET /stats`
- `GET /health`, `GET /metrics`

### Example

```bash
curl -s -X POST http://localhost:5001/register \
  -H "Content-Type: application/json" \
  -d '{"student_name":"Asha","email":"asha@unstop-lab.test","college":"NIT Trichy",
       "year":3,"skills":["python","machine-learning","sql"],
       "opportunity_id":"hack-001","team_size":2}'
```

```json
{"registration_id":"reg-000001","status":"confirmed","score":47,"rank":1,"participants":1,
 "notification_id":"msg-reg-000001-1",
 "timings_ms":{"opportunity_check_ms":17.58,"evaluation_ms":64.43,"notify_ms":9.62,"total_ms":92.55}}
```

An ineligible request short-circuits at Service 2 and never reaches Service 3:

```json
{"error":"not_eligible","reason":"deadline_passed","opportunity_id":"hack-004", ...}
```

Rejection reasons: `deadline_passed`, `insufficient_seats`, `year_not_eligible`, `skill_mismatch`.

## Run it

```bash
docker compose up -d --build
docker compose ps          # wait until all three are healthy
```

```bash
# Windows PowerShell
powershell -ExecutionPolicy Bypass -File loadtest\run-lab.ps1 -Requests 200

# Linux / macOS / WSL
./loadtest/run-lab.sh 200 "1,2,4,8,16"

# or drive the generator directly
python loadtest/loadtest.py --requests 200 --levels 1,2,4,8,16
```

`run-lab.*` samples `docker stats` in the background, runs the load test, then prints peak
CPU / memory per container. Output lands in `results/`.

Stop: `docker compose down`.

## Push to Docker Hub

Image names come from two variables, so the same compose file builds locally and publishes:

```yaml
image: ${IMAGE_PREFIX:-unstop-lab}/registration-service:${IMAGE_TAG:-latest}
```

```bash
# 1. log in (Docker Hub asks for your username and an access token).
#    Credentials go to the Docker CLI credential store, never into this repository.
docker login

# 2. set your namespace once
cp .env.example .env        # then edit: IMAGE_PREFIX=<yourhubusername>

# 3. build and push all three images
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

That publishes `docker.io/<yourhubusername>/registration-service`,
`.../opportunity-service` and `.../evaluation-service`. To run the stack from the published
images instead of building:

```bash
IMAGE_PREFIX=<yourhubusername> docker compose pull
IMAGE_PREFIX=<yourhubusername> docker compose up -d
```

Notes:
- The three repos must exist under your namespace (or be created automatically on first push).
- Docker Hub enforces lowercase repository names.
- Anonymous pulls are rate limited; keep the images public for an evaluator to pull them.

## Where the cost is

`POST /evaluate` does `HEAVY_ITERS` chained sha256 rounds plus a `HEAVY_SLEEP` pause
(simulating model inference), so it is the most expensive *single* step of the chain and it
runs in one gunicorn worker with threads. Because the work is pure Python it is bound by the
GIL, so extra threads buy no throughput.

The measured results are more nuanced than "Service 3 is the bottleneck", and the report says
so: Service 3 has the largest per-request service-side time, but Service 1 does two outbound
HTTP calls per request (with `requests`, JSON encode/decode and Flask overhead) and therefore
ends up consuming the most *total* CPU once throughput is high. Both effects are visible in
`results/observation_table.md`; tune `HEAVY_ITERS` / `HEAVY_SLEEP` and re-run to move the
balance.

Tune it without touching code (in `docker-compose.yml`):

| Variable | Service | Default | Meaning |
|---|---|---|---|
| `HEAVY_ITERS` | evaluation | `4000` | sha256 rounds per request (~18 ms) |
| `HEAVY_SLEEP` | evaluation | `0.03` | simulated inference (s) |
| `NOTIFY_DELAY` | evaluation | `0.005` | simulated e-mail send |
| `IO_DELAY` | opportunity | `0.005` | pretend DB read |
| `RESERVE_SEATS` | opportunity | `false` | if `true`, eligible checks consume seats (breaks repeatable runs) |

## Results pipeline

Nothing below is hand written: the harness records the run, then two scripts turn it into
the table and the graphs the manual asks for.

```bash
docker compose up -d --build

# 1. run the five workloads (200 requests each at concurrency 1, 2, 4, 8, 16)
powershell -ExecutionPolicy Bypass -File loadtest
un-workloads.ps1 -Requests 200   # Windows
./loadtest/run-workloads.sh 200                                                    # Linux / macOS

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
| `results/observation_table.md` / `.csv` | the filled observation table (plus per-service detail) |
| `results/graphs/*.png` | response time, throughput, CPU utilization, memory utilization |
| `report/report.md` | the written analysis and conclusion |
| `DEMO.md` | the five checkpoints, command by command |

### How CPU and memory are measured

`docker stats` samples roughly every 2 s, which is too coarse for a workload that lasts
under 10 s: the peak it reports is whichever sample happened to land on the busiest moment.
So every service also exposes `GET /metrics`, which reads the container's own cgroup:

```bash
curl -s http://localhost:5003/metrics
```

```json
{"service":"evaluation-service","cpu_seconds":13.367,"memory_peak_bytes":55984128.0,
 "memory_current_bytes":41168896.0,"rss_bytes":35729408.0}
```

The harness reads `/metrics` on all three containers immediately before and after each
workload, so `cpu_percent = (cpu_seconds_after - cpu_seconds_before) / wall_seconds` is the
exact average CPU of that container for that workload - the same definition `docker stats`
uses, but measured instead of sampled. Memory comes from cgroup `memory.peak`, which is the
true high-water mark rather than the highest sample. The sampled `docker stats` output is
still recorded per workload as supporting evidence.

### Reading the load tool output

```
 conc  reqs   201  409  err  wall_s     rps   avg_ms   p50_ms   p95_ms   p99_ms   max_ms
    8   200   200    0    0   6.47   30.93   252.51   245.65   350.16   371.49   391.94
```

`201` is a confirmed registration (the whole chain ran), `409` is a request the opportunity
service rejected on eligibility, `err` is a timeout or connection failure. `Failed` in the
observation table is `reqs - 201`, so a `409` counts as failed.

## Notes / caveats

- Every service keeps state **in memory**, so each container runs **1 gunicorn worker with
  threads**. More workers would split `registrations` and the leaderboards across processes.
- `HEAVY_SLEEP` is a sleep, not real work: it inflates latency without burning CPU. The sha256
  loop is the part that actually consumes CPU.
- Scores are deterministic per `registration_id`, but ranks shift between runs because requests
  complete out of order under concurrency.
- `loadtest.py` uses one keep-alive connection per worker thread, so it measures the services and
  not TCP setup through the Docker Desktop proxy.
- Compose caps memory at 256M per container but sets **no CPU limit**, so `docker stats` and the
  cgroup numbers reflect real demand instead of a cap. If you add a `cpus:` limit, the
  containers will sit at that limit and the per-service CPU comparison becomes meaningless.
- All three containers share the Docker Desktop VM's cores, so a busy host adds noise. Let the
  machine settle before a run and do not rebuild images immediately before measuring.
- `loadtest/run-lab.*` is the quick version (all levels in one pass, sampled stats only);
  `loadtest/run-workloads.*` is the graded version (one workload at a time, exact metrics).#   C C _ L A B _ 1  
 