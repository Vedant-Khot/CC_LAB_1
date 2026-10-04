# Evaluator Demo Script

Five checkpoints, in order. Every command is meant to be run from the project root
(`unstop-lab/`). Run `docker compose up -d --build` once before checkpoint 1.

Windows uses `powershell` blocks, Linux/macOS uses `bash`. Both are given where they differ.

---

## Checkpoint 1 — each service's API works independently

Each service answers on its own port, without going through the others.

**Service 2 — Opportunity Service (port 5002)**

```bash
curl -s http://localhost:5002/health
curl -s http://localhost:5002/opportunities | head -c 400
curl -s http://localhost:5002/opportunities/hack-001
curl -s -X POST http://localhost:5002/opportunities/hack-001/check \
  -H "Content-Type: application/json" \
  -d '{"team_size":2,"year":3,"skills":["python","machine-learning","sql"]}'
```

Last call returns `200` with `"eligible": true`. Repeat with
`{"team_size":2,"year":3,"skills":["javascript"]}` to show a `409` and
`"reason":"skill_mismatch"`, or use `hack-004` to show `"reason":"deadline_passed"`.

**Service 3 — Evaluation Service (port 5003)**

```bash
curl -s http://localhost:5003/health
curl -s -X POST http://localhost:5003/evaluate \
  -H "Content-Type: application/json" \
  -d '{"registration_id":"reg-demo-1","opportunity_id":"hack-001","applicant":{"name":"Demo","year":3,"skills":["python","sql"]}}'
curl -s -X POST http://localhost:5003/notify \
  -H "Content-Type: application/json" \
  -d '{"registration_id":"reg-demo-1","to":"demo@unstop-lab.test"}'
curl -s http://localhost:5003/leaderboard/hack-001
curl -s http://localhost:5003/metrics
```

`/evaluate` returns `score`, `rank`, `participants`, `compute_ms`. `/metrics` returns the
container's exact CPU seconds and peak memory.

**Service 1 — Registration Service (port 5001)**

```bash
curl -s http://localhost:5001/health
curl -s http://localhost:5001/registrations | head -c 400
curl -s http://localhost:5001/registrations/reg-000001
curl -s http://localhost:5001/metrics
```

---

## Checkpoint 2 — images built and containers running

```bash
docker images | grep -E "registration-service|opportunity-service|evaluation-service"
docker compose ps
```

Expected: three images and three containers with status `Up ... (healthy)` on ports
5001, 5002, 5003. With `.env` set to `IMAGE_PREFIX=vedantkhot112` the images are
`vedantkhot112/unstop-lab-registration-service` and so on; without it they build locally as
`unstop-lab/unstop-lab-<service>:latest`.

Bonus: the three images are published, so you can show the stack running straight from Docker Hub
with no local build at all:

```bash
docker compose pull      # .env already points at vedantkhot112
docker compose up -d
docker compose ps
```

---

## Checkpoint 3 — end-to-end request through all three services

```bash
curl -s -X POST http://localhost:5001/register \
  -H "Content-Type: application/json" \
  -d '{"student_name":"Asha","email":"asha@unstop-lab.test","college":"NIT Trichy",
       "year":3,"skills":["python","machine-learning","sql"],
       "opportunity_id":"hack-001","team_size":2}'
```

Response (HTTP 201) contains `registration_id`, `score`, `rank`, `notification_id` and
`timings_ms` with a separate timing for each hop:

```json
{"registration_id":"reg-000001","status":"confirmed","opportunity_title":"Smart India Hackathon",
 "score":47,"rank":1,"participants":1,"notification_id":"msg-reg-000001-1",
 "timings_ms":{"opportunity_check_ms":11.4,"evaluation_ms":48.1,"notify_ms":11.6,"total_ms":72.4}}
```

**Show the service-to-service calls in the logs** (each line is tagged with its service name):

```bash
docker compose logs --no-log-prefix | grep "service=" | tail -10
```

```text
service=registration-service  [..] "POST /register HTTP/1.1" 201 431B 137ms
service=opportunity-service   [..] "POST /opportunities/hack-009/check HTTP/1.1" 200 242B 65ms
service=evaluation-service    [..] "POST /evaluate HTTP/1.1" 200 199B 40ms
service=evaluation-service    [..] "POST /notify HTTP/1.1" 200 62B 6ms
```

Follow them live while sending the request:

```bash
docker compose logs -f
```

---

## Checkpoint 4 — load test with docker stats monitoring

Terminal 1 — live container stats:

```bash
docker stats
```

Terminal 2 — the five workloads (each restarts the stateful services first, then records
raw load output, `docker stats` samples and exact CPU/memory per container):

```bash
# Windows PowerShell
powershell -ExecutionPolicy Bypass -File loadtest\run-workloads.ps1 -Requests 200

# Linux / macOS
./loadtest/run-workloads.sh 200
```

Then build the table and the graphs:

```bash
python report/make-table.py
python report/make-graphs.py
```

Artifacts written:

```text
results/load_test_outputs/W1.txt ... W5.txt   raw load output (latency, 201 / 409 / error counts)
results/load_test_outputs/W1.json ... W5.json  same numbers, machine readable
results/docker_stats/W1.csv ... W5.csv         docker stats samples per workload
results/docker_stats/cpu_metrics.csv           exact CPU seconds and peak RSS per container
results/observation_table.md / .csv            the filled observation table
results/graphs/*.png                           the four graphs
```

To generate load only for one level while watching stats:

```bash
python loadtest/loadtest.py --requests 200 --levels 16
```

---

---

## Bonus - the dashboard (optional, shows well)

With the stack up, open **http://localhost:8080**.

Best first impression: click **Run 1 / 2 / 4 / 8 / 16** in the load testing panel. The page runs the
five levels itself, draws throughput / latency / CPU charts as the points arrive, and prints a table
with the CPU of each container measured from its cgroup. Then send one registration from the form and
watch the score, rank and per-hop timings come back from all three services.

To show the services are independent behind the UI, stop one and watch the panel degrade:

```bash
docker compose stop opportunity-service
```

the page keeps loading, and a registration comes back with `upstream_failure` naming the stage,
because Service 1 reports which hop broke rather than returning a generic 500.

The generator runs in this fourth container on purpose: putting it inside one of the three measured
services would spend the CPU that the measurement is meant to attribute.

## Checkpoint 5 — table, graphs, explanation

Show, in this order:

1. `results/observation_table.md` — main table plus per-service CPU/memory, latency
   percentiles and the per-hop server-side breakdown.
2. `results/graphs/avg_response_time.png`, `throughput.png`, `cpu_utilization.png`,
   `memory_utilization.png`.
3. The analysis in `report/report.md` (sections: response time / throughput trend, which
   service used the most CPU and memory, degradation and cause, conclusion).

Then be ready to explain: the architecture and the request path, what each Dockerfile and
the compose file do, how the services communicate over the `lab` bridge network, how the
workload was generated and measured, and why the numbers look the way they do.