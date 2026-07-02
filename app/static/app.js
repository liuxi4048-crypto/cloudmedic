/* CloudMedic dashboard */

const $ = (id) => document.getElementById(id);

let currentIncidentId = null;
const chartData = []; // {error, p95, mem}
const MAX_POINTS = 60;

// ---------- 初期化 ----------

async function init() {
  const state = await fetchJSON("/api/state");
  renderState(state);
  renderInjectButtons(state.fault_types);
  const incidents = state.incidents || [];
  renderHistory(incidents);
  const active = incidents.find((i) => i.status === "investigating" || i.status === "awaiting_approval") || incidents[0];
  if (active) loadIncident(active.id);
  connectSSE();
}

async function fetchJSON(url, opts) {
  const res = await fetch(url, opts);
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  return res.json();
}

function post(url, body) {
  return fetchJSON(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
}

// ---------- SSE ----------

function connectSSE() {
  const es = new EventSource("/api/events");
  es.onmessage = (msg) => {
    const { type, data } = JSON.parse(msg.data);
    if (type === "vitals") updateVitals(data);
    else if (type === "agent_event") onAgentEvent(data);
    else if (type === "incident_update") onIncidentUpdate(data);
    else if (type === "state") refreshState();
  };
  es.onerror = () => {
    setTimeout(() => { es.close(); connectSSE(); }, 3000);
  };
}

async function refreshState() {
  try {
    const state = await fetchJSON("/api/state");
    renderState(state);
    renderHistory(state.incidents || []);
  } catch (e) { /* noop */ }
}

// ---------- 描画: 患者・バイタル ----------

function renderState(state) {
  const p = state.patient;
  $("patient-name").textContent = p.name;
  $("patient-version").textContent = p.version;
  $("patient-instances").textContent = `${p.instances} 台`;
  $("patient-failsafe").textContent = p.failsafe_active ? "🟡 有効（キャッシュ応答）" : "無効";

  const faults = $("active-faults");
  faults.innerHTML = "";
  for (const f of p.active_faults) {
    const chip = document.createElement("div");
    chip.className = "fault-chip";
    chip.textContent = `⚠ ${p.fault_labels[f] || f}`;
    faults.appendChild(chip);
  }

  updateVitals(state.vitals);

  document.querySelectorAll("#mode-segmented button").forEach((b) => {
    b.classList.toggle("active", b.dataset.mode === state.settings.mode);
  });
}

function updateVitals(v) {
  if (!v) return;
  const err = $("v-error"), p95 = $("v-p95"), rpm = $("v-rpm"), mem = $("v-mem");
  err.textContent = `${v.error_rate_pct}%`;
  err.className = "vital-value " + (v.error_rate_pct >= 20 ? "bad" : "ok");
  p95.textContent = `${Math.round(v.p95_latency_ms)}ms`;
  p95.className = "vital-value " + (v.p95_latency_ms >= 1200 ? "bad" : "ok");
  rpm.textContent = v.requests_per_min;
  rpm.className = "vital-value";
  mem.textContent = `${Math.round(v.memory_mb)}MB`;
  mem.className = "vital-value " + (v.memory_mb >= v.memory_alert_mb ? "bad" : "ok");

  const badge = $("patient-status");
  badge.textContent = v.status === "healthy" ? "正常" : "異常あり";
  badge.className = "badge " + (v.status === "healthy" ? "healthy" : "degraded");

  chartData.push({ error: v.error_rate_pct, p95: v.p95_latency_ms, mem: v.memory_mb });
  if (chartData.length > MAX_POINTS) chartData.shift();
  drawChart();
}

function drawChart() {
  const canvas = $("vitals-chart");
  const ctx2d = canvas.getContext("2d");
  const w = canvas.width, h = canvas.height;
  ctx2d.clearRect(0, 0, w, h);
  const series = [
    { key: "error", color: "#f85149", scale: (x) => x },          // 0-100
    { key: "p95", color: "#d29922", scale: (x) => x / 20 },        // 2000ms -> 100
    { key: "mem", color: "#bc8cff", scale: (x) => x / 10 },        // 1000MB -> 100
  ];
  for (const s of series) {
    ctx2d.beginPath();
    ctx2d.strokeStyle = s.color;
    ctx2d.lineWidth = 1.6;
    chartData.forEach((d, i) => {
      const x = (i / (MAX_POINTS - 1)) * w;
      const y = h - Math.min(100, s.scale(d[s.key])) / 100 * (h - 8) - 4;
      i === 0 ? ctx2d.moveTo(x, y) : ctx2d.lineTo(x, y);
    });
    ctx2d.stroke();
  }
}

// ---------- 障害注入・操作 ----------

function renderInjectButtons(faultTypes) {
  const grid = $("inject-buttons");
  grid.innerHTML = "";
  for (const f of faultTypes) {
    const btn = document.createElement("button");
    btn.textContent = f.label;
    btn.onclick = async () => {
      btn.disabled = true;
      try { await post("/api/demo/inject", { fault: f.id }); }
      finally { setTimeout(() => (btn.disabled = false), 2000); }
    };
    grid.appendChild(btn);
  }
}

$("btn-reset").onclick = () => post("/api/demo/reset").then(refreshState);
$("btn-manual-trigger").onclick = () =>
  post("/api/incidents/trigger").catch((e) => alert("エージェントは対応中です"));

document.querySelectorAll("#mode-segmented button").forEach((b) => {
  b.onclick = () => post("/api/settings/mode", { mode: b.dataset.mode }).then(refreshState);
});

// ---------- インシデント表示 ----------

async function loadIncident(id) {
  currentIncidentId = id;
  const inc = await fetchJSON(`/api/incidents/${id}`);
  $("agent-feed").innerHTML = "";
  $("feed-empty")?.remove();
  for (const ev of inc.events) appendEvent(inc.id, ev);
  setIncidentBadge(inc.status);
  if (inc.postmortem) showPostmortem(inc.postmortem);
  else $("postmortem-card").style.display = "none";
}

function onIncidentUpdate(summary) {
  if (!currentIncidentId || summary.id === currentIncidentId ||
      summary.status === "investigating") {
    if (summary.id !== currentIncidentId && summary.status === "investigating") {
      loadIncident(summary.id);
      return;
    }
    setIncidentBadge(summary.status);
  }
  refreshHistoryOnly();
}

async function refreshHistoryOnly() {
  try { renderHistory(await fetchJSON("/api/incidents")); } catch (e) { /* noop */ }
}

function setIncidentBadge(status) {
  const badge = $("incident-status");
  const map = {
    investigating: ["🔍 診察中…", "working"],
    awaiting_approval: ["🙋 承認待ち", "waiting"],
    recovered: ["✅ 回復済み", "healthy"],
    failed: ["⚠ 要手動対応", "degraded"],
  };
  const [label, cls] = map[status] || ["待機中", ""];
  badge.textContent = label;
  badge.className = "badge " + cls;
}

function onAgentEvent({ incident_id, event }) {
  if (currentIncidentId !== incident_id) {
    currentIncidentId = incident_id;
    $("agent-feed").innerHTML = "";
  }
  $("feed-empty")?.remove();
  appendEvent(incident_id, event);
}

function appendEvent(incidentId, ev) {
  const feed = $("agent-feed");
  const div = document.createElement("div");
  div.className = `event event-${ev.type}`;
  const time = new Date(ev.ts * 1000).toLocaleTimeString("ja-JP");

  let html = `<span class="ev-time">${time}</span><span class="ev-title">${escapeHtml(ev.title)}</span>`;

  if (ev.type === "postmortem") {
    showPostmortem(ev.detail);
  } else if (ev.type === "approval_request" && ev.detail) {
    html += `<div class="ev-detail">${escapeHtml(ev.detail.reason || "")}</div>`;
    if (ev.detail.decision === null || ev.detail.decision === undefined) {
      html += `
        <div class="approval-actions" data-approval="${ev.detail.id}">
          <button class="btn-approve" onclick="decide('${incidentId}','${ev.detail.id}',true)">✅ 承認する</button>
          <button class="btn-reject" onclick="decide('${incidentId}','${ev.detail.id}',false)">却下</button>
        </div>`;
    }
  } else if (ev.detail && ev.type !== "thought" && ev.type !== "info") {
    const text = typeof ev.detail === "string" ? ev.detail : JSON.stringify(ev.detail, null, 1);
    html += `<details class="ev-detail-wrap"><summary>詳細</summary><div class="ev-detail">${escapeHtml(truncate(text, 1200))}</div></details>`;
  }

  div.innerHTML = html;
  feed.appendChild(div);
  feed.scrollTop = feed.scrollHeight;
}

window.decide = async (incidentId, approvalId, approve) => {
  try {
    await post(`/api/incidents/${incidentId}/approval`, { approval_id: approvalId, approve });
    document.querySelectorAll(`[data-approval="${approvalId}"]`).forEach((el) => el.remove());
  } catch (e) { alert("承認処理に失敗しました: " + e.message); }
};

// ---------- ポストモーテム ----------

function showPostmortem(md) {
  $("postmortem-card").style.display = "";
  $("postmortem-body").innerHTML = renderMarkdown(md);
  $("btn-copy-pm").onclick = () => navigator.clipboard.writeText(md);
}

function renderMarkdown(md) {
  // 最小限のMarkdownレンダラ（見出し・表・強調・区切り線）
  const lines = md.split("\n");
  let html = "", inTable = false;
  for (const line of lines) {
    if (/^\|/.test(line)) {
      if (/^\|[\s\-|]+\|$/.test(line)) continue;
      const cells = line.split("|").slice(1, -1).map((c) => c.trim());
      if (!inTable) { html += "<table>"; inTable = true; }
      html += "<tr>" + cells.map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>";
      continue;
    }
    if (inTable) { html += "</table>"; inTable = false; }
    if (/^# /.test(line)) html += `<h1>${inline(line.slice(2))}</h1>`;
    else if (/^## /.test(line)) html += `<h2>${inline(line.slice(3))}</h2>`;
    else if (/^---/.test(line)) html += "<hr>";
    else if (line.trim() === "") html += "";
    else html += `<p>${inline(line)}</p>`;
  }
  if (inTable) html += "</table>";
  return html;

  function inline(s) {
    return escapeHtml(s)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\*(.+?)\*/g, "<em>$1</em>");
  }
}

// ---------- 履歴 ----------

function renderHistory(incidents) {
  const box = $("incident-history");
  if (!incidents.length) {
    box.innerHTML = '<p class="hint">まだ履歴はありません。</p>';
    return;
  }
  box.innerHTML = "";
  const statusLabel = {
    investigating: "🔍 診察中", awaiting_approval: "🙋 承認待ち",
    recovered: "✅ 回復", failed: "⚠ 要対応",
  };
  for (const inc of incidents) {
    const div = document.createElement("div");
    div.className = "history-item";
    const t = new Date(inc.started_at * 1000).toLocaleTimeString("ja-JP");
    div.innerHTML = `<span>${t} — ${escapeHtml(inc.trigger.reason || "インシデント")}</span>
      <span class="hint">${statusLabel[inc.status] || inc.status}</span>`;
    div.onclick = () => loadIncident(inc.id);
    box.appendChild(div);
  }
}

// ---------- utils ----------

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function truncate(s, n) { return s.length > n ? s.slice(0, n) + "…" : s; }

init();
