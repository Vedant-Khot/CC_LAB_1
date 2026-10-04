"use strict";

// name is the container name the API keys "cpu" and "containers" by, so it must
// match exactly; cls is only for the CSS bar class, colour is shared by charts
const SERVICES = [
  { name: "registration-service", cls: "reg", color: "#e05a4f" },
  { name: "opportunity-service", cls: "opp", color: "#4a9df8" },
  { name: "evaluation-service", cls: "eval", color: "#3fbf7f" }
];

const $ = (id) => document.getElementById(id);
const fmt = (n, d = 2) => (n === null || n === undefined ? "-" : Number(n).toFixed(d));

async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({ error: "invalid_json" }));
  return { status: response.status, body };
}

function show(el, text, kind) {
  el.textContent = typeof text === "string" ? text : JSON.stringify(text, null, 2);
  el.className = "result show" + (kind ? " " + kind : "");
}

function table(headers, rows) {
  const head = headers.map((h) => `<th>${h}</th>`).join("");
  const body = rows.map((r) => `<tr>${r.join("")}</tr>`).join("");
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

/* ---------- registration -------------------------------------------------- */
$("register-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const button = $("reg-btn");
  button.disabled = true;
  show($("reg-result"), "calling POST /register through all three services ...");

  const { status, body } = await api("/api/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      student_name: form.get("student_name"),
      email: form.get("email"),
      college: form.get("college"),
      year: Number(form.get("year")),
      skills: String(form.get("skills") || "").split(",").map((s) => s.trim()).filter(Boolean),
      opportunity_id: form.get("opportunity_id"),
      team_size: Number(form.get("team_size"))
    })
  });

  button.disabled = false;
  if (status === 201) {
    const t = body.timings_ms || {};
    show($("reg-result"),
      `HTTP 201  ${body.registration_id}  "${body.opportunity_title}"\n` +
      `score ${body.score}   rank ${body.rank} of ${body.participants}   ${body.notification_id}\n` +
      `service time: opportunity ${fmt(t.opportunity_check_ms)} ms | evaluate ${fmt(t.evaluation_ms)} ms | ` +
      `notify ${fmt(t.notify_ms)} ms | total ${fmt(t.total_ms)} ms`, "good");
  } else {
    show($("reg-result"), `HTTP ${status}  ${JSON.stringify(body, null, 2)}`, "bad");
  }
  refreshOverview();
  refreshRegistrations();
});

/* ---------- opportunities -------------------------------------------------- */
async function refreshOpportunities() {
  const { status, body } = await api("/api/opportunities");
  const target = $("opp-table");
  if (status !== 200) {
    target.innerHTML = `<p class="hint">could not reach the opportunity service (HTTP ${status})</p>`;
    return;
  }

  const select = $("opp-select");
  const previous = select.value;
  select.innerHTML = body.opportunities
    .map((o) => `<option value="${o.id}">${o.title}</option>`)
    .join("");
  if (previous) select.value = previous;

  const rows = body.opportunities.map((o) => {
    const statusPill = o.open
      ? (o.seats_left < 5 ? '<span class="pill tight">few seats</span>' : '<span class="pill open">open</span>')
      : '<span class="pill shut">closed</span>';
    const years = `${o.eligible_years.min}-${o.eligible_years.max}`;
    return [
      `<td>${o.id}</td>`,
      `<td>${o.title}</td>`,
      `<td>${statusPill}</td>`,
      `<td class="num">${o.seats_left}/${o.seats_total}</td>`,
      `<td class="num">${years}</td>`,
      `<td>${o.required_skills.join(", ") || "any"}</td>`,
      `<td>${o.deadline.slice(0, 10)}</td>`,
    ];
  });
  target.innerHTML = table(
    ["id", "title", "status", "seats left", "years", "required skills", "deadline"], rows);
}

/* ---------- load testing ---------------------------------------------------- */
async function runLevel(concurrency) {
  const requests = Number($("req-count").value) || 100;
  $("run-status").textContent = `running concurrency ${concurrency} with ${requests} requests ...`;
  document.querySelectorAll(".lvl").forEach((b) => { b.disabled = true; });
  $("run-all").disabled = true;

  const started = Date.now();
  const { status, body } = await api("/api/loadtest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ concurrency, requests })
  });

  document.querySelectorAll(".lvl").forEach((b) => { b.disabled = false; });
  $("run-all").disabled = false;

  if (status !== 200) {
    $("run-status").textContent = `concurrency ${concurrency}: HTTP ${status} ${JSON.stringify(body)}`;
    return;
  }
  $("run-status").textContent =
    `concurrency ${concurrency}: ${body.rps} rps, avg ${fmt(body.avg_ms)} ms, p95 ${fmt(body.p95_ms)} ms, ` +
    `${body.ok} ok / ${body.failed + body.not_eligible} not ok  (${((Date.now() - started) / 1000).toFixed(1)}s)`;
  await refreshResults();
}

document.querySelectorAll(".lvl").forEach((button) => {
  button.addEventListener("click", () => runLevel(Number(button.dataset.conc)));
});

$("run-all").addEventListener("click", async () => {
  for (const button of document.querySelectorAll(".lvl")) {
    await runLevel(Number(button.dataset.conc));
  }
});

$("clear-btn").addEventListener("click", () => {
  results.length = 0;
  renderResults();
  $("run-status").textContent = "cleared. ";
});

/* ---------- charts ---------------------------------------------------------- */
const results = [];

function lineChart(svgId, series, valueOf, yLabel) {
  const svg = $(svgId);
  const W = 320, H = 190, padL = 34, padR = 8, padT = 10, padB = 22;
  const xs = results.map((r) => r.concurrency);
  const points = series.map((s) => ({
    color: s.color,
    values: results.map((r) => valueOf(r, s.name))
  })).flatMap((s) => s.values.map((v, i) => ({ x: xs[i], y: v, color: s.color })))
   .filter((p) => p.y !== null && p.y !== undefined && !Number.isNaN(p.y));

  if (!points.length) {
    svg.innerHTML = `<text x="${W / 2}" y="${H / 2}" text-anchor="middle" class="axis-text">no data yet</text>`;
    return;
  }

  const maxX = Math.max(...points.map((p) => p.x));
  const maxY = Math.max(...points.map((p) => p.y)) * 1.15 || 1;
  const px = (x) => padL + (x / maxX) * (W - padL - padR);
  const py = (y) => H - padB - (y / maxY) * (H - padT - padB);

  let markup = "";
  for (let i = 0; i <= 4; i++) {
    const y = padT + (i / 4) * (H - padT - padB);
    markup += `<line class="grid-line" x1="${padL}" y1="${y}" x2="${W - padR}" y2="${y}"/>`;
    markup += `<text class="axis-text" x="4" y="${y + 3}">${(maxY * (1 - i / 4)).toFixed(maxY < 10 ? 1 : 0)}</text>`;
  }
  markup += `<line class="axis" x1="${padL}" y1="${H - padB}" x2="${W - padR}" y2="${H - padB}"/>`;
  for (const x of xs) {
    markup += `<text class="axis-text" x="${px(x)}" y="${H - padB + 13}" text-anchor="middle">${x}</text>`;
  }

  const byColor = {};
  points.forEach((p) => { (byColor[p.color] = byColor[p.color] || []).push(p); });
  for (const color of Object.keys(byColor)) {
    const group = byColor[color].sort((a, b) => a.x - b.x);
    const d = group.map((p, i) => `${i ? "L" : "M"}${px(p.x).toFixed(1)},${py(p.y).toFixed(1)}`).join(" ");
    markup += `<path class="series" stroke="${color}" d="${d}"/>`;
    group.forEach((p) => {
      markup += `<circle class="dot" cx="${px(p.x).toFixed(1)}" cy="${py(p.y).toFixed(1)}" r="3" fill="${color}"/>`;
    });
  }

  markup += `<text class="axis-text" x="${padL}" y="${H - 3}">concurrent requests</text>`;
  svg.innerHTML = markup;
}

function renderResults() {
  lineChart("chart-rps", [{ key: "rps", color: "#4a9df8" }], (r) => r.rps);
  lineChart("chart-lat", [{ key: "avg_ms", color: "#e05a4f" }], (r) => r.avg_ms);
  lineChart("chart-cpu", SERVICES.map((s) => ({ key: s.name, color: s.color })),
    (r, key) => (r.cpu && r.cpu[key] ? r.cpu[key].cpu_percent : null));

  $("stat-workloads").textContent = results.length;
  const last = results[results.length - 1];
  $("stat-rps").textContent = last ? `${last.rps} rps` : "-";

  if (!results.length) {
    $("load-table").innerHTML = "No workloads run yet in this session.";
    return;
  }

  const rows = results.map((r) => {
    const cpu = SERVICES.map((s) => {
      const entry = r.cpu && r.cpu[s.name];
      const pct = entry ? entry.cpu_percent : 0;
      return `<td class="num">${fmt(pct, 1)}%<div class="bar ${s.cls}"><span style="width:${Math.min(100, pct)}%"></span></div></td>`;
    }).join("");
    return [
      `<td>${r.concurrency}</td>`,
      `<td class="num">${r.requests}</td>`,
      `<td class="num">${fmt(r.avg_ms)}</td>`,
      `<td class="num">${fmt(r.p95_ms)}</td>`,
      `<td class="num">${r.rps}</td>`,
      `<td class="num">${r.ok}</td>`,
      `<td class="num">${r.failed + r.not_eligible}</td>`,
      cpu,
      `<td class="num">${fmt((r.containers || {})["evaluation-service"]?.memory_peak_mb, 1)}</td>`,
    ];
  });

  $("load-table").innerHTML = table(
    ["conc", "reqs", "avg ms", "p95 ms", "rps", "201 ok", "failed",
     "cpu reg", "cpu opp", "cpu eval", "peak mem MB"], rows) +
    `<div class="legend">` +
    SERVICES.map((s) => `<span><i style="background:${s.color}"></i>${s.name}</span>`).join("") +
    `</div>`;
}

async function refreshResults() {
  const { status, body } = await api("/api/loadtest/results");
  if (status !== 200) return;
  results.length = 0;
  body.results.forEach((r) => results.push(r));
  renderResults();
}

/* ---------- live metrics ---------------------------------------------------- */
async function refreshOverview() {
  const { status, body } = await api("/api/overview");
  if (status !== 200) return;
  $("stat-regs").textContent = body.registration_count === null ? "-" : body.registration_count;

  const rows = SERVICES.map((s) => {
    const c = body.containers[s.name] || {};
    const cpu = c.cpu_seconds !== undefined ? fmt(c.cpu_seconds, 2) + " cpu-s" : "n/a";
    const mem = c.memory_current_mb !== undefined ? fmt(c.memory_current_mb, 1) : "n/a";
    const peak = c.memory_peak_mb !== undefined ? fmt(c.memory_peak_mb, 1) : "n/a";
    return [
      `<td><span class="pill" style="background:${s.color}22;color:${s.color}">${s.name}</span></td>`,
      `<td class="num">${cpu}</td>`,
      `<td class="num">${mem}</td>`,
      `<td class="num">${peak}</td>`,
    ];
  });
  $("metrics-table").innerHTML =
    table(["container", "cpu used so far", "memory now (MB)", "peak memory (MB)"], rows);
}

async function refreshRegistrations() {
  const { status, body } = await api("/api/registrations?limit=8");
  if (status !== 200) return;
  const rows = (body.registrations || []).slice(-8).reverse().map((r) => [
    `<td>${r.registration_id}</td>`,
    `<td>${r.applicant.name}</td>`,
    `<td>${r.opportunity_id}</td>`,
    `<td class="num">${r.score}</td>`,
    `<td class="num">${r.rank}</td>`,
    `<td class="num">${fmt((r.timings_ms || {}).total_ms, 1)}</td>`,
  ]);
  $("regs-table").innerHTML = rows.length
    ? table(["id", "name", "opportunity", "score", "rank", "total ms"], rows)
    : `<p class="hint">no registrations yet - send one above</p>`;

  const opportunityId = $("opp-select").value;
  if (opportunityId) {
    const board = await api(`/api/leaderboard/${opportunityId}`);
    if (board.status === 200) {
      const boardRows = (board.body.top || []).map((row, i) => [
        `<td>${i + 1}</td>`,
        `<td>${row.name || "-"}</td>`,
        `<td class="num">${row.score}</td>`,
      ]);
      $("board-table").innerHTML = boardRows.length
        ? table(["rank", "name", "score"], boardRows)
        : `<p class="hint">leaderboard for ${opportunityId} is empty</p>`;
    }
  }
}

$("opp-select").addEventListener("change", refreshRegistrations);

/* ---------- boot ------------------------------------------------------------ */
refreshOpportunities();
refreshResults();
refreshOverview();
refreshRegistrations();
setInterval(refreshOverview, 2000);
setInterval(refreshRegistrations, 4000);