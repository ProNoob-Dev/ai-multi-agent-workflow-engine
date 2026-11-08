/* Dashboard logic: talks to /api, renders metrics, runs, approvals, evals. */
const $ = (id) => document.getElementById(id);

function badge(status) {
  return `<span class="badge ${status}">${status.replace(/_/g, " ")}</span>`;
}
function fmtTime(iso) {
  if (!iso) return "–";
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

async function loadHealth() {
  const r = await fetch("/api/health");
  const h = await r.json();
  $("status-pill").textContent = `● ${h.llm_provider} · ${h.store} store · ${h.runs_recorded} runs`;
}

async function loadMetrics() {
  const r = await fetch("/api/metrics");
  const m = await r.json();
  $("m-total").textContent = m.total_runs;
  $("m-auto").textContent = (m.autonomous_rate * 100).toFixed(0) + "%";
  $("m-lat").textContent = m.avg_latency_ms + " ms";
  $("m-pend").textContent = m.awaiting_approval;
  $("m-tok").textContent = m.total_tokens.toLocaleString();
  $("m-cost").textContent = "$" + m.total_cost_usd.toFixed(4);
  $("runs-count").textContent = m.total_runs;
  $("approvals-count").textContent = m.awaiting_approval;
}

async function loadRuns() {
  const r = await fetch("/api/runs?limit=50");
  const runs = await r.json();
  const body = $("runs-body");
  if (!runs.length) {
    body.innerHTML = `<tr><td colspan="7" class="empty">No runs yet — run a workflow from the Overview tab.</td></tr>`;
    return;
  }
  body.innerHTML = runs.map((run) => `
    <tr data-id="${run.id}">
      <td>${fmtTime(run.finished_at || run.started_at)}</td>
      <td>${esc(run.request)}</td>
      <td>${esc(run.intent || "–")}</td>
      <td>${esc(run.agent || "–")}</td>
      <td>${badge(run.status)}</td>
      <td>${run.latency_ms} ms</td>
      <td>${run.tokens}</td>
    </tr>`).join("");
  body.querySelectorAll("tr[data-id]").forEach((tr) => {
    tr.addEventListener("click", () => showRunDetail(tr.dataset.id));
  });
}

async function showRunDetail(id) {
  const r = await fetch(`/api/runs/${id}`);
  const run = await r.json();
  const el = $("run-detail");
  el.classList.remove("hidden");
  el.innerHTML = `
    <h3>Run ${esc(run.id)} — ${esc(run.agent || "")}</h3>
    <p><strong>Request:</strong> ${esc(run.request)}</p>
    <p><strong>Status:</strong> ${badge(run.status)} &nbsp; <strong>Latency:</strong> ${run.latency_ms} ms &nbsp; <strong>Tokens:</strong> ${run.tokens} &nbsp; <strong>Est. cost:</strong> $${run.cost_usd}</p>
    ${run.financial_action ? `<p><strong>Financial action:</strong> ${esc(run.financial_action.type)} ${esc(run.financial_action.currency)} ${(run.financial_action.amount || 0).toLocaleString()} for ${esc(run.financial_action.invoice_id)} — approval: ${run.approval === null ? "pending" : run.approval}</p>` : ""}
    <h3>Result</h3><pre>${esc(run.result || "")}</pre>
    ${run.citations && run.citations.length ? `<p><strong>Citations:</strong> ${run.citations.map(esc).join(", ")}</p>` : ""}
    <h3>Steps</h3><ol>${(run.steps || []).map((s) => `<li>${esc(s)}</li>`).join("")}</ol>
    <h3>Trace</h3><ul>${(run.trace || []).map((t) => `<li>${esc(t.name)} — ${t.duration_ms} ms${t.tokens ? ` · ${t.tokens} tokens` : ""}</li>`).join("")}</ul>
    ${run.saga_log && run.saga_log.length ? `<h3>Saga log</h3><ul>${run.saga_log.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>` : ""}
    ${run.error ? `<p style="color:#f87171"><strong>Error:</strong> ${esc(run.error)}</p>` : ""}`;
  el.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function loadApprovals() {
  const r = await fetch("/api/approvals");
  const items = await r.json();
  const el = $("approvals-list");
  if (!items.length) {
    el.innerHTML = `<p class="empty">Queue is empty — no financial action is waiting for approval.</p>`;
    return;
  }
  el.innerHTML = items.map((run) => {
    const a = run.financial_action || {};
    return `<div class="approval-card">
      <strong>${esc(a.type || "financial action")}</strong> — ${esc(a.currency || "")} ${(a.amount || 0).toLocaleString()} for ${esc(a.invoice_id || "")}
      <p class="hint">${esc(run.request || "")}</p>
      <p class="hint">Requested by ${esc(run.agent || "")} · ${fmtTime(run.finished_at || run.started_at)}</p>
      <div class="actions">
        <button class="btn-approve" onclick="decide('${run.id}', true)">Approve &amp; execute</button>
        <button class="btn-reject" onclick="decide('${run.id}', false)">Reject</button>
      </div>
    </div>`;
  }).join("");
}

async function decide(id, approved) {
  const action = approved ? "approve" : "reject";
  const r = await fetch(`/api/approvals/${id}/${action}`, { method: "POST" });
  if (!r.ok) { alert("Could not " + action + " this run."); return; }
  await refreshAll();
}

async function loadEval() {
  const r = await fetch("/api/eval");
  const e = await r.json();
  const el = $("eval-body");
  if (e.error) { el.innerHTML = `<p class="empty">${esc(e.error)}</p>`; return; }
  el.innerHTML = `
    <table class="runs-table"><thead><tr><th>Metric</th><th>Value</th></tr></thead><tbody>
      <tr><td>Golden cases</td><td>${e.cases}</td></tr>
      <tr><td>Routing accuracy</td><td>${(e.routing_accuracy * 100).toFixed(1)}%</td></tr>
      <tr><td>Agent accuracy</td><td>${(e.agent_accuracy * 100).toFixed(1)}%</td></tr>
      <tr><td>Outcome accuracy</td><td>${(e.outcome_accuracy * 100).toFixed(1)}%</td></tr>
      <tr><td>Autonomous resolution rate</td><td>${(e.autonomous_resolution_rate * 100).toFixed(1)}% (${e.autonomous_cases}/${e.cases})</td></tr>
      <tr><td>Cases needing human approval</td><td>${e.needs_approval_cases}</td></tr>
      <tr><td>Avg latency per case</td><td>${e.avg_latency_ms} ms</td></tr>
      <tr><td>Total tokens (mock provider)</td><td>${e.total_tokens.toLocaleString()}</td></tr>
    </tbody></table>
    <p class="hint" style="margin-top:12px">Per-case detail lives in <code>data/eval_results.json</code>. Re-run any time with <code>python -m app.eval</code>.</p>`;
}

async function refreshAll() {
  await Promise.all([loadHealth(), loadMetrics(), loadRuns(), loadApprovals(), loadEval()]);
}

document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tabpane").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $("tab-" + btn.dataset.tab).classList.add("active");
  });
});

document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => { $("req-input").value = chip.dataset.req; });
});

$("run-btn").addEventListener("click", async () => {
  const req = $("req-input").value.trim();
  if (!req) return;
  const btn = $("run-btn");
  btn.disabled = true;
  btn.textContent = "Running…";
  const box = $("run-result");
  box.classList.remove("hidden");
  box.innerHTML = "<p class='hint'>Running the workflow…</p>";
  try {
    const r = await fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request: req }),
    });
    const run = await r.json();
    box.innerHTML = `
      <p>${badge(run.status)} &nbsp; <strong>${esc(run.agent || "")}</strong> · ${esc(run.intent || "")} · ${run.latency_ms} ms · ${run.tokens} tokens</p>
      <pre>${esc(run.result || "")}</pre>
      ${run.financial_action ? `<p class="hint">Financial action ${esc(run.financial_action.type)} ${esc(run.financial_action.currency)} ${(run.financial_action.amount || 0).toLocaleString()} — waiting in the Review Queue.</p>` : ""}
      ${run.citations && run.citations.length ? `<p class="hint">Citations: ${run.citations.map(esc).join(", ")}</p>` : ""}`;
  } catch (err) {
    box.innerHTML = `<p style="color:#f87171">Run failed: ${esc(err.message)}</p>`;
  }
  btn.disabled = false;
  btn.textContent = "▶ Run workflow";
  await refreshAll();
});

refreshAll();
setInterval(() => { loadHealth(); loadMetrics(); loadApprovals(); }, 5000);
