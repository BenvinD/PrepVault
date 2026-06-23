const state = { config: null, token: localStorage.getItem("pt_token") || null, problems: [], providers: [] };

function authHeaders() {
  const h = { "Content-Type": "application/json" };
  if (state.token) h["Authorization"] = `Bearer ${state.token}`;
  return h;
}

async function api(path, opts = {}) {
  const res = await fetch(`/api${path}`, { headers: authHeaders(), ...opts });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

// Run a background job and resolve with its result. In local mode the job comes
// back already finished; in cloud mode we poll /jobs/{id} until it's terminal.
async function runJob(path, opts = {}) {
  const job = await api(path, { method: "POST", ...opts });
  if (job.status === "success") return job.result || {};
  if (job.status === "error") throw new Error(job.error || "Job failed");
  for (let i = 0; i < 600; i++) {
    await new Promise(r => setTimeout(r, 500));
    const j = await api(`/jobs/${job.id}`);
    if (j.status === "success") return j.result || {};
    if (j.status === "error") throw new Error(j.error || "Job failed");
  }
  throw new Error("Job timed out");
}

function toast(msg, ok = true) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.style.borderColor = ok ? "#262b36" : "#7f1d1d";
  t.classList.remove("hidden");
  setTimeout(() => t.classList.add("hidden"), 3200);
}

function diffClass(d) { return (d || "").toLowerCase(); }
function esc(s) { return (s ?? "").toString().replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

/* ---------- unified renderers (judge-agnostic) ---------- */
function judgeBadge(j) {
  if (!j) return "";
  const label = typeof j === "string" ? j : (j.label || j.name || "");
  if (!label) return "";
  const color = (typeof j === "object" && j.color) ? j.color : "#6366f1";
  return `<span class="jbadge" style="--jc:${esc(color)}"><span class="jdot"></span>${esc(label)}</span>`;
}
function diffPill(d) {
  const label = d && typeof d === "object" ? d.label : d;
  if (!label) return "";
  const color = (d && typeof d === "object" && d.color) ? d.color : diffClass(label);
  return `<span class="pill ${esc(color)}">${esc(label)}</span>`;
}
function statusPill(s) {
  const label = s && typeof s === "object" ? s.label : s;
  if (!label) return "";
  const color = (s && typeof s === "object") ? (s.color || "") : ((label || "").toLowerCase().includes("accept") ? "easy" : "");
  return `<span class="pill ${esc(color)}">${esc(label)}</span>`;
}
function langText(l) { return Array.isArray(l) ? (l.join(", ") || "—") : (l || "—"); }
function topicsText(t) { return Array.isArray(t) ? t.join(", ") : (t || ""); }

/* ---------- tabs ---------- */
function showTab(name) {
  document.querySelectorAll(".tab").forEach(b => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".view").forEach(v => v.classList.toggle("hidden", v.dataset.view !== name));
  if (name === "dashboard") loadDashboard();
  if (name === "activity") loadActivity();
  if (name === "problems") loadProblems();
  if (name === "revision") loadRevision();
  if (name === "sync") renderSyncTab();
}
document.getElementById("tabs").addEventListener("click", e => {
  if (e.target.dataset.tab) showTab(e.target.dataset.tab);
});

/* ---------- dashboard ---------- */
async function loadDashboard() {
  const s = await api("/stats");
  const cards = [
    { v: s.total, l: "Total solved" },
    { v: s.solved_last_30_days, l: "Last 30 days" },
    { v: s.due_for_revision, l: "Due to revise" },
    { v: Object.keys(s.by_difficulty).length, l: "Difficulty buckets" },
  ];
  document.getElementById("statCards").innerHTML = cards.map(c =>
    `<div class="stat"><div class="v">${c.v}</div><div class="l">${c.l}</div></div>`).join("");

  const max = Math.max(1, ...Object.values(s.by_difficulty));
  const order = ["Easy", "Medium", "Hard"];
  const diffs = Object.entries(s.by_difficulty).sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0]));
  document.getElementById("byDifficulty").innerHTML = diffs.map(([k, v]) =>
    `<div><div class="flex justify-between text-sm mb-1"><span class="pill ${diffClass(k)}">${esc(k)}</span><span class="text-muted">${v}</span></div>
     <div class="bar"><span style="width:${(v / max * 100).toFixed(0)}%"></span></div></div>`).join("") || `<p class="text-muted text-sm">No data yet — run a sync.</p>`;

  document.getElementById("topTopics").innerHTML = s.top_topics.map(([t, c]) =>
    `<span class="pill">${esc(t)} · ${c}</span>`).join("") || `<p class="text-muted text-sm">No topics yet.</p>`;
}

/* ---------- activity ---------- */
state.activityYear = null;

function levelFor(count, max) {
  if (!count) return 0;
  const r = count / Math.max(max, 1);
  if (r <= 0.25) return 1;
  if (r <= 0.5) return 2;
  if (r <= 0.75) return 3;
  return 4;
}

function renderBars(mountId, items, opts = {}) {
  const mount = document.getElementById(mountId);
  const max = Math.max(1, ...items.map(i => i.count));
  if (!items.some(i => i.count)) { mount.innerHTML = `<p class="text-muted text-sm">No data.</p>`; return; }
  mount.innerHTML = items.map(i => `
    <div>
      <div class="flex justify-between text-xs mb-1"><span class="text-slate-300">${esc(i.label)}</span><span class="text-muted">${i.count}</span></div>
      <div class="bar"><span style="width:${(i.count / max * 100).toFixed(0)}%"></span></div>
    </div>`).join("");
}

async function loadActivity() {
  const data = await api(`/activity${state.activityYear ? `?year=${state.activityYear}` : ""}`);
  state.activityYear = data.year;
  state.activityData = data;

  // Year pills
  document.getElementById("yearPills").innerHTML = (data.years_available.length ? data.years_available : [data.year])
    .map(y => `<button class="pill ${y === data.year ? '' : ''}" data-year="${y}" style="${y === data.year ? 'border-color:#6366f1;color:#fff' : ''}">${y}</button>`).join("");
  document.querySelectorAll("#yearPills [data-year]").forEach(b => b.addEventListener("click", () => {
    state.activityYear = +b.dataset.year; loadActivity();
  }));

  // Summary cards
  const cards = [
    { v: data.total_events, l: `Contributions in ${data.year}` },
    { v: data.active_days, l: "Active days" },
    { v: data.current_streak, l: "Current streak" },
    { v: data.longest_streak, l: "Longest streak" },
    { v: data.busiest_day ? data.busiest_day.count : 0, l: data.busiest_day ? `Busiest (${data.busiest_day.date})` : "Busiest day" },
  ];
  document.getElementById("activityCards").innerHTML = cards.map(c =>
    `<div class="stat"><div class="v">${c.v}</div><div class="l">${esc(c.l)}</div></div>`).join("");

  // Legend
  document.getElementById("legend").innerHTML = [0,1,2,3,4].map(l => `<span class="legend-cell hm-l${l}"></span>`).join("");

  renderHeatmap(data);
  renderBars("byMonth", data.by_month.map(m => ({ label: monthName(m.month), count: m.count })));
  renderBars("byWeekday", data.by_weekday);
  renderBars("byProvider", data.by_provider.map(p => ({ label: p.judge, count: p.count })));
  renderBars("actByDifficulty", ["Easy","Medium","Hard"].filter(k => k in data.by_difficulty).map(k => ({ label: k, count: data.by_difficulty[k] })));
  document.getElementById("actTopics").innerHTML = data.top_topics.map(([t, c]) => `<span class="pill">${esc(t)} · ${c}</span>`).join("") || `<p class="text-muted text-sm">No topics.</p>`;
  document.getElementById("dayDetail").innerHTML = "";
}

function monthName(m) { return ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][m-1]; }

function renderHeatmap(data) {
  const cal = data.calendar;
  const max = Math.max(1, ...cal.map(d => d.count));
  const firstDow = (new Date(cal[0].date + "T00:00:00").getDay() + 6) % 7; // Mon=0
  const cells = [];
  for (let i = 0; i < firstDow; i++) cells.push(`<div class="hm-cell empty"></div>`);
  for (const d of cal) {
    const lvl = levelFor(d.count, max);
    cells.push(`<div class="hm-cell hm-l${lvl}" data-date="${d.date}" data-count="${d.count}"></div>`);
  }
  const hm = document.getElementById("heatmap");
  hm.innerHTML = cells.join("");

  // tooltip
  let tip = document.getElementById("hmTip");
  if (!tip) { tip = document.createElement("div"); tip.id = "hmTip"; tip.className = "hm-tip"; document.body.appendChild(tip); }
  hm.querySelectorAll(".hm-cell[data-date]").forEach(cell => {
    cell.addEventListener("mousemove", e => {
      const c = cell.dataset.count, dt = cell.dataset.date;
      tip.textContent = `${c} contribution${c === "1" ? "" : "s"} · ${dt}`;
      tip.style.display = "block";
      tip.style.left = (e.clientX + 12) + "px";
      tip.style.top = (e.clientY + 12) + "px";
    });
    cell.addEventListener("mouseleave", () => { tip.style.display = "none"; });
    cell.addEventListener("click", () => showDay(cell));
  });
}

function showDay(cell) {
  document.querySelectorAll(".hm-cell.sel").forEach(c => c.classList.remove("sel"));
  cell.classList.add("sel");
  const date = cell.dataset.date;
  const items = (state.activityData.day_items || {})[date] || [];
  const panel = document.getElementById("dayDetail");
  if (!items.length) {
    panel.innerHTML = `<div class="text-muted text-sm border-t border-line pt-3">No problems on ${date}.</div>`;
    return;
  }
  panel.innerHTML = `<div class="border-t border-line pt-3">
    <div class="text-sm mb-2"><span class="font-medium">${items.length}</span> problem(s) on <span class="text-slate-200">${date}</span></div>
    <div class="flex flex-col gap-1">${items.map(i => `
      <div class="flex items-center gap-2 text-sm">
        ${judgeBadge(i.judge)}
        <span class="text-slate-200">${esc(i.title)}</span>
        ${diffPill(i.difficulty)}
      </div>`).join("")}</div>
  </div>`;
}

document.getElementById("backfillBtn").addEventListener("click", async () => {
  const btn = document.getElementById("backfillBtn");
  btn.disabled = true; btn.textContent = "Backfilling…";
  try {
    const r = await runJob(`/sync/backfill`);
    toast(r.message || `Backfilled ${r.problems_processed} problem(s)`);
    await loadActivity();
  } catch (err) { toast(err.message, false); }
  finally { btn.disabled = false; btn.textContent = "Backfill history"; }
});

/* ---------- export / import ---------- */
document.getElementById("exportBtn").addEventListener("click", async () => {
  const btn = document.getElementById("exportBtn");
  btn.disabled = true; btn.textContent = "Exporting…";
  try {
    const res = await fetch("/api/export", { headers: authHeaders() });
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      if (res.status === 404) detail += " — restart the server and hard-refresh (the export endpoint is new)";
      try { detail = (await res.json()).detail || detail; } catch (_) {}
      throw new Error(`Export failed: ${detail}`);
    }
    const blob = await res.blob();
    const cd = res.headers.get("Content-Disposition") || "";
    const m = cd.match(/filename="?([^"]+)"?/);
    const name = m ? m[1] : "prepvault-export.json";
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = name; document.body.appendChild(a); a.click();
    a.remove(); URL.revokeObjectURL(url);
    toast("Exported your data");
  } catch (err) { toast(err.message, false); }
  finally { btn.disabled = false; btn.textContent = "Export data"; }
});

document.getElementById("importBtn").addEventListener("click", () => {
  document.getElementById("importFile").click();
});

document.getElementById("importFile").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const out = document.getElementById("transferResult");
  out.innerHTML = `<span class="text-muted">Importing…</span>`;
  try {
    const payload = JSON.parse(await file.text());
    const r = await api("/import", { method: "POST", body: JSON.stringify(payload) });
    out.innerHTML = `<span class="text-green-400">${esc(r.message)}</span>`;
    toast(r.message);
    loadDashboard();
  } catch (err) {
    out.innerHTML = `<span class="text-red-400">${esc(err.message)}</span>`;
  } finally {
    e.target.value = "";  // allow re-importing the same file
  }
});

/* ---------- problems ---------- */
async function loadProblems() {
  const q = document.getElementById("search").value.trim();
  const d = document.getElementById("diffFilter").value;
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (d) params.set("difficulty", d);
  state.problems = await api(`/problems?${params}`);
  renderProblems(state.problems, "problemsTable", true);
}

function fmtDateTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function renderProblems(rows, mountId, withControls) {
  const mount = document.getElementById(mountId);
  if (!rows.length) { mount.innerHTML = `<div class="p-6 text-muted text-sm">Nothing here yet.</div>`; return; }
  const cols = withControls ? 8 : 7;
  const body = rows.map(p => `
    <tr class="prow" data-id="${p.id}">
      <td class="text-muted">${esc(p.external_id || "")}</td>
      <td>${judgeBadge(p.judge)}</td>
      <td>
        <div class="font-medium cursor-pointer toggle" data-id="${p.id}">
          <span class="chev" data-id="${p.id}">▸</span> ${esc(p.title)}
        </div>
        <div class="text-muted text-xs">${esc(topicsText(p.topics))}</div>
        ${p.approach ? `<div class="text-xs mt-1 text-slate-400 italic">${esc(p.approach)}</div>` : ""}
      </td>
      <td>${diffPill(p.difficulty)}</td>
      <td class="text-xs">${esc(langText(p.languages))}</td>
      <td>
        <select data-id="${p.id}" class="conf input !py-1 !px-2 text-xs">
          ${[0, 1, 2, 3, 4, 5].map(n => `<option value="${n}" ${(p.confidence || 0) === n ? "selected" : ""}>${n || "–"}</option>`).join("")}
        </select>
      </td>
      <td class="text-muted text-xs">${p.next_revision || "—"}</td>
      ${withControls ? `<td class="whitespace-nowrap">
        <button class="btn-ghost insight" data-id="${p.id}" title="Generate AI insight">AI</button>
        <button class="btn-ghost revised" data-id="${p.id}">Revised</button>
        <button class="btn-ghost del" data-id="${p.id}">✕</button>
      </td>` : ""}
    </tr>
    <tr class="detail-row hidden" id="detail-${p.id}"><td colspan="${cols}" class="bg-ink/40"></td></tr>`).join("");
  mount.innerHTML = `<table><thead><tr>
      <th>#</th><th>Judge</th><th>Problem</th><th>Diff</th><th>Lang</th><th>Conf</th><th>Next</th>${withControls ? "<th></th>" : ""}
    </tr></thead><tbody>${body}</tbody></table>`;

  mount.querySelectorAll(".toggle").forEach(el => el.addEventListener("click", () => toggleDetail(el.dataset.id)));
  mount.querySelectorAll(".conf").forEach(sel => sel.addEventListener("change", async e => {
    await api(`/problems/${e.target.dataset.id}`, { method: "PATCH", body: JSON.stringify({ confidence: +e.target.value }) });
    toast("Confidence updated");
  }));
  mount.querySelectorAll(".revised").forEach(b => b.addEventListener("click", async e => {
    await api(`/problems/${e.target.dataset.id}/revised`, { method: "POST" });
    toast("Marked revised"); loadProblems();
  }));
  mount.querySelectorAll(".del").forEach(b => b.addEventListener("click", async e => {
    await api(`/problems/${e.target.dataset.id}`, { method: "DELETE" });
    toast("Deleted"); loadProblems();
  }));
  mount.querySelectorAll(".insight").forEach(b => b.addEventListener("click", async e => {
    const id = e.target.dataset.id;
    e.target.textContent = "…"; e.target.disabled = true;
    try { await runJob(`/problems/${id}/insight`); toast("Insight generated"); loadProblems(); }
    catch (err) { toast(err.message, false); e.target.textContent = "AI"; e.target.disabled = false; }
  }));
}

async function toggleDetail(id) {
  const row = document.getElementById(`detail-${id}`);
  const chev = document.querySelector(`.chev[data-id="${id}"]`);
  if (!row.classList.contains("hidden")) {
    row.classList.add("hidden"); if (chev) chev.textContent = "▸"; return;
  }
  row.classList.remove("hidden"); if (chev) chev.textContent = "▾";
  const cell = row.querySelector("td");
  cell.innerHTML = `<div class="p-3 text-muted text-sm">Loading submissions…</div>`;
  try {
    const data = await api(`/problems/${id}/submissions`);
    renderDetail(cell, data);
  } catch (err) {
    cell.innerHTML = `<div class="p-3 text-sm text-red-400">${esc(err.message)}</div>`;
  }
}

function renderDetail(cell, data) {
  const p = data.problem, subs = data.submissions;
  const meta = `
    <div class="flex flex-wrap gap-x-6 gap-y-1 text-xs mb-3 items-center">
      ${judgeBadge(p.judge)}
      <span class="text-muted">First solved: <span class="text-slate-200">${fmtDateTime(p.first_solved_at)}</span></span>
      <span class="text-muted">Last AC (revised): <span class="text-slate-200">${p.last_revised || "—"}</span></span>
      <span class="text-muted">Languages: <span class="text-slate-200">${esc(langText(p.languages))}</span></span>
      <button class="btn-ghost ml-auto addsub" data-id="${p.id}">+ Add submission</button>
    </div>`;
  if (!subs.length) {
    cell.innerHTML = `<div class="p-3">${meta}<div class="text-muted text-sm">No submissions yet. Use “+ Add submission” to paste your code.</div></div>`;
    cell.querySelector(".addsub").addEventListener("click", () => addSubmission(p.id));
    return;
  }
  const list = subs.map(s => `
    <div class="sub border border-line rounded-lg p-2 mb-2">
      <div class="flex items-center gap-3 text-xs flex-wrap">
        ${statusPill(s.status)}
        <span class="text-slate-200">${esc(s.lang || "")}</span>
        <span class="text-muted">${fmtDateTime(s.submitted_at)}</span>
        ${s.runtime ? `<span class="text-muted">⏱ ${esc(s.runtime)}</span>` : ""}
        ${s.memory ? `<span class="text-muted">▤ ${esc(s.memory)}</span>` : ""}
        <button class="btn-ghost ml-auto viewcode" data-id="${s.id}">View code</button>
        ${s.url ? `<a class="btn-ghost" href="${esc(s.url)}" target="_blank">↗</a>` : ""}
      </div>
      <pre class="code-block hidden mt-2" id="code-${s.id}"></pre>
    </div>`).join("");
  cell.innerHTML = `<div class="p-3">${meta}<div class="text-muted text-xs uppercase tracking-wide mb-2">Submissions</div>${list}</div>`;
  cell.querySelectorAll(".viewcode").forEach(b => b.addEventListener("click", () => viewCode(b)));
  cell.querySelector(".addsub").addEventListener("click", () => addSubmission(p.id));
}

async function addSubmission(problemId) {
  const lang = prompt("Language (e.g. C++, Python):", "") || null;
  const code = prompt("Paste your code:");
  if (code === null) return;
  try {
    await api(`/problems/${problemId}/submissions/manual`, {
      method: "POST",
      body: JSON.stringify({ code, lang, status: "Accepted" }),
    });
    toast("Submission added");
    const row = document.getElementById(`detail-${problemId}`);
    const cell = row.querySelector("td");
    renderDetail(cell, await api(`/problems/${problemId}/submissions`));
    loadProblems();
  } catch (err) { toast(err.message, false); }
}

async function viewCode(btn) {
  const id = btn.dataset.id;
  const pre = document.getElementById(`code-${id}`);
  if (!pre.classList.contains("hidden")) { pre.classList.add("hidden"); btn.textContent = "View code"; return; }
  if (pre.dataset.loaded) { pre.classList.remove("hidden"); btn.textContent = "Hide code"; return; }
  btn.textContent = "…"; btn.disabled = true;
  try {
    const d = await api(`/submissions/${id}/code`);
    pre.textContent = d.code || "(no code returned)";
    pre.dataset.loaded = "1"; pre.classList.remove("hidden");
    btn.textContent = "Hide code";
  } catch (err) { toast(err.message, false); btn.textContent = "View code"; }
  finally { btn.disabled = false; }
}
document.getElementById("search").addEventListener("input", debounce(loadProblems, 300));
document.getElementById("diffFilter").addEventListener("change", loadProblems);
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

/* ---------- revision (smart priority queue, batched) ---------- */
const revSession = { queue: [], total: 0, done: 0, batchSize: 5, weakTopics: [] };

async function loadRevision() {
  const data = await api("/revision/queue");
  revSession.queue = data.items || [];
  revSession.total = data.total_due || 0;
  revSession.done = 0;
  revSession.batchSize = data.batch_size || 5;
  revSession.weakTopics = data.weak_topics || [];
  renderRevision();
}

function renderRevisionSummary() {
  const el = document.getElementById("revisionSummary");
  if (!revSession.weakTopics.length) { el.innerHTML = ""; return; }
  el.innerHTML = `<div class="card">
    <div class="text-xs uppercase tracking-wide text-muted mb-2">Focus areas — your weakest topics right now</div>
    <div class="flex flex-wrap gap-2">
      ${revSession.weakTopics.map(w => `
        <span class="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-panel2 border border-line"
              title="avg confidence ${w.avg_confidence ?? "—"} · ${w.due} due">
          ${esc(w.topic)}
          <span class="text-muted">${Math.round((w.weakness || 0) * 100)}%</span>
        </span>`).join("")}
    </div>
  </div>`;
}

function renderRevisionProgress() {
  const el = document.getElementById("revisionProgress");
  if (revSession.total === 0) { el.innerHTML = ""; return; }
  const pct = Math.round((revSession.done / revSession.total) * 100);
  el.innerHTML = `
    <div class="flex items-center gap-3 text-sm">
      <span class="font-medium">${revSession.done} of ${revSession.total} done</span>
      <span class="text-muted">· ${revSession.queue.length} left</span>
      <div class="flex-1 h-2 bg-panel2 rounded-full overflow-hidden ml-1">
        <div class="h-full bg-accent transition-all" style="width:${pct}%"></div>
      </div>
    </div>`;
}

function renderRevision() {
  renderRevisionSummary();
  renderRevisionProgress();
  const mount = document.getElementById("revisionList");

  if (revSession.total === 0) {
    mount.innerHTML = `<div class="card text-center py-10">
      <div class="text-lg font-medium mb-1">All caught up</div>
      <p class="text-muted text-sm">Nothing is due for revision right now.</p></div>`;
    return;
  }
  if (revSession.queue.length === 0) {
    mount.innerHTML = `<div class="card text-center py-10">
      <div class="text-lg font-medium mb-1">Session complete</div>
      <p class="text-muted text-sm">You cleared all ${revSession.total} due problem(s). Strong work.</p>
      <button id="revReload" class="btn-ghost mt-3">Reload queue</button></div>`;
    document.getElementById("revReload").addEventListener("click", loadRevision);
    return;
  }

  const batch = revSession.queue.slice(0, revSession.batchSize);
  mount.innerHTML = `
    <p class="text-muted text-xs mb-1">Next ${batch.length} highest-priority — clear them and the next batch loads automatically.</p>
    ${batch.map(revisionCard).join("")}`;
  bindRevisionButtons();
}

const GRADES = [[1, "Forgot"], [2, "Hard"], [3, "OK"], [4, "Good"], [5, "Easy"]];

function revisionCard(p) {
  const conf = p.confidence;
  const reasons = (p.reasons || []).map(r =>
    `<span class="text-[11px] px-2 py-0.5 rounded-full bg-panel2 border border-line text-muted">${esc(r)}</span>`
  ).join("");
  const grades = GRADES.map(([n, lbl]) =>
    `<button class="grade-btn text-xs px-2 py-1 rounded-md bg-panel2 border border-line hover:border-accent ${conf == n ? "border-accent text-white" : ""}"
             data-id="${p.id}" data-grade="${n}" title="${lbl}">${n}<span class="text-muted ml-1 hidden sm:inline">${lbl}</span></button>`
  ).join("");
  return `<div class="card py-3" data-rid="${p.id}">
    <div class="flex items-center gap-3 flex-wrap">
      <div class="flex-1 min-w-[200px]">
        <div class="font-medium flex items-center gap-2">${judgeBadge(p.judge)}${p.url ? `<a href="${esc(p.url)}" target="_blank" class="hover:text-white">${esc(p.title)}</a>` : esc(p.title)}</div>
        <div class="text-muted text-xs mt-0.5">${esc(topicsText(p.topics))}${p.next_revision ? ` · due ${p.next_revision}` : ""}</div>
        <div class="flex flex-wrap gap-1 mt-2">${reasons}</div>
      </div>
      ${diffPill(p.difficulty)}
      <div class="rev-actions flex items-center gap-2">
        <button class="btn-ghost text-xs skip-rev" data-id="${p.id}">Skip</button>
        <button class="btn-primary text-xs revised-rev" data-id="${p.id}">Mark revised</button>
      </div>
      <div class="rev-grader hidden items-center gap-1 flex-wrap">
        <span class="text-xs text-muted mr-1">How well did you recall it?</span>
        ${grades}
        <button class="grade-skip text-xs text-muted ml-1 hover:text-white" data-id="${p.id}" title="Mark revised without rating">no rating</button>
      </div>
    </div>
  </div>`;
}

async function gradeAndRevise(id, grade) {
  try {
    if (grade != null) {
      await api(`/problems/${id}`, { method: "PATCH", body: JSON.stringify({ confidence: grade }) });
    }
    await api(`/problems/${id}/revised`, { method: "POST" });
    revSession.queue = revSession.queue.filter(x => x.id !== id);
    revSession.done += 1;
    toast(grade != null ? `Rated ${grade}/5 · rescheduled` : "Rescheduled");
    renderRevision();
    if (revSession.queue.length === 0) loadDashboard();
  } catch (err) { toast(err.message, false); }
}

function bindRevisionButtons() {
  document.querySelectorAll(".revised-rev").forEach(b => b.addEventListener("click", e => {
    const card = e.target.closest("[data-rid]");
    card.querySelector(".rev-actions").classList.add("hidden");
    const grader = card.querySelector(".rev-grader");
    grader.classList.remove("hidden");
    grader.classList.add("flex");
  }));
  document.querySelectorAll(".grade-btn").forEach(b => b.addEventListener("click", e => {
    const btn = e.target.closest(".grade-btn");
    gradeAndRevise(+btn.dataset.id, +btn.dataset.grade);
  }));
  document.querySelectorAll(".grade-skip").forEach(b => b.addEventListener("click", e => {
    gradeAndRevise(+e.target.dataset.id, null);
  }));
  document.querySelectorAll(".skip-rev").forEach(b => b.addEventListener("click", e => {
    const id = +e.target.dataset.id;
    const idx = revSession.queue.findIndex(x => x.id === id);
    if (idx >= 0) { const [it] = revSession.queue.splice(idx, 1); revSession.queue.push(it); }
    renderRevision();
  }));
}

/* ---------- sync ---------- */
function renderSyncTab() {
  const sel = document.getElementById("syncJudge");
  if (!sel) return;
  const providers = state.providers.length ? state.providers
    : [{ name: "leetcode", label: "LeetCode", syncable: true }];
  sel.innerHTML = providers.map(p => `<option value="${p.name}">${esc(p.label)}</option>`).join("");
  sel.onchange = updateSyncFields;
  updateSyncFields();
  loadAccounts();
}

async function loadAccounts() {
  const box = document.getElementById("accountsList");
  if (!box) return;
  let accounts = [];
  try { accounts = await api("/sync/accounts"); } catch { /* ignore */ }
  if (!accounts.length) {
    box.innerHTML = `<p class="text-sm text-muted">No accounts synced yet.</p>`;
    return;
  }
  box.innerHTML = accounts.map((a, i) => {
    const j = a.judge;
    const dot = `<span class="jdot" style="background:${esc(j.color)}"></span>`;
    const name = a.account ? esc(a.account) : `<span class="text-muted italic">unattributed</span>`;
    const cookie = a.has_cookie ? `<span class="text-xs text-muted">· cookie</span>` : "";
    const resync = a.syncable
      ? `<button class="btn-ghost text-xs" data-resync="${i}">Resync</button>` : "";
    return `<div class="flex items-center gap-2 p-2 rounded-lg border border-line bg-panel2/40">
      <span class="jbadge">${dot}${esc(j.label)}</span>
      <span class="text-sm">${name}</span>
      <span class="text-xs text-muted">${a.problems} problem${a.problems === 1 ? "" : "s"}</span>
      ${cookie}
      <span class="ml-auto flex gap-1">
        ${resync}
        <button class="btn-ghost text-xs text-red-400" data-unsync="${i}">Unsync</button>
      </span>
    </div>`;
  }).join("");

  box.querySelectorAll("[data-resync]").forEach(btn => {
    btn.onclick = () => resyncAccount(accounts[+btn.dataset.resync]);
  });
  box.querySelectorAll("[data-unsync]").forEach(btn => {
    btn.onclick = () => unsyncAccount(accounts[+btn.dataset.unsync]);
  });
}

function refreshAfterSyncChange() {
  loadAccounts();
  if (typeof loadDashboard === "function") loadDashboard();
  if (typeof loadProblems === "function") loadProblems();
  if (typeof loadActivity === "function") loadActivity();
}

async function resyncAccount(a) {
  const payload = { judge: a.judge.name };
  if (a.account) payload.username = a.account;
  toast(`Resyncing ${a.judge.label}…`);
  try {
    const r = await runJob("/sync", { body: JSON.stringify(payload) });
    toast(r.message || "Resynced");
    refreshAfterSyncChange();
  } catch (err) { toast(err.message, false); }
}

async function unsyncAccount(a) {
  const who = a.account ? `${a.judge.label} (${a.account})` : a.judge.label;
  if (!confirm(`Unsync ${who}? This permanently removes ${a.problems} problem(s), their submissions and activity. This cannot be undone.`)) return;
  try {
    const r = await api("/sync/unsync", {
      method: "POST",
      body: JSON.stringify({ judge: a.judge.name, account: a.account }),
    });
    toast(r.message || "Unsynced");
    refreshAfterSyncChange();
  } catch (err) { toast(err.message, false); }
}

function updateSyncFields() {
  const sel = document.getElementById("syncJudge");
  const judge = sel.value;
  const prov = state.providers.find(p => p.name === judge) || { syncable: true };
  const lc = document.getElementById("lcFields");
  const hr = document.getElementById("hrFields");
  const cc = document.getElementById("ccFields");
  const note = document.getElementById("syncNote");
  const btn = document.getElementById("syncBtn");
  lc.classList.toggle("hidden", judge !== "leetcode");
  hr.classList.toggle("hidden", judge !== "hackerrank");
  cc.classList.toggle("hidden", judge !== "codechef");
  if (!prov.syncable) {
    note.textContent = `${sel.options[sel.selectedIndex].text} has no public API — add these problems manually from the Problems tab.`;
    note.classList.remove("hidden");
    btn.disabled = true; btn.classList.add("opacity-50");
  } else {
    note.classList.add("hidden");
    btn.disabled = false; btn.classList.remove("opacity-50");
  }
}

document.getElementById("syncBtn").addEventListener("click", async () => {
  const btn = document.getElementById("syncBtn");
  const out = document.getElementById("syncResult");
  const judge = document.getElementById("syncJudge").value;
  let payload = { judge };
  if (judge === "hackerrank") {
    const u = document.getElementById("hrUser").value.trim();
    if (!u) { out.innerHTML = `<span class="text-red-400">Enter a HackerRank username.</span>`; return; }
    payload.username = u;
    payload.session_cookie = document.getElementById("hrSession").value.trim() || null;
  } else if (judge === "codechef") {
    const u = document.getElementById("ccUser").value.trim();
    if (!u) { out.innerHTML = `<span class="text-red-400">Enter a CodeChef username.</span>`; return; }
    payload.username = u;
  } else if (judge === "leetcode") {
    const u = document.getElementById("lcUser").value.trim();
    if (!u) { out.innerHTML = `<span class="text-red-400">Enter your LeetCode username.</span>`; return; }
    payload.username = u;
    payload.leetcode_session = document.getElementById("lcSession").value.trim() || null;
    payload.csrftoken = document.getElementById("lcCsrf").value.trim() || null;
  } else {
    payload.username = document.getElementById("lcUser")?.value.trim() || null;
  }
  btn.disabled = true; btn.textContent = "Syncing…"; out.textContent = "";
  try {
    const r = await runJob("/sync", { body: JSON.stringify(payload) });
    out.innerHTML = `<span class="text-green-400">${esc(r.message)}</span>`;
    toast(`Added ${r.added} problem(s)`);
    loadAccounts();
  } catch (err) { out.innerHTML = `<span class="text-red-400">${esc(err.message)}</span>`; }
  finally { btn.disabled = false; btn.textContent = "Start sync"; }
});

/* ---------- auth (cloud mode) ---------- */
function renderAuth() {
  const area = document.getElementById("authArea");
  if (!state.config.auth_required) { area.innerHTML = `<span class="text-xs text-muted">local mode</span>`; return; }
  if (state.token) {
    area.innerHTML = `<button class="btn-ghost" id="logout">Log out</button>`;
    document.getElementById("logout").onclick = () => { state.token = null; localStorage.removeItem("pt_token"); location.reload(); };
  } else {
    area.innerHTML = `<button class="btn-primary text-xs" id="loginBtn">Sign in / up</button>`;
    document.getElementById("loginBtn").onclick = authPrompt;
  }
}
async function authPrompt() {
  const email = prompt("Email:"); if (!email) return;
  const password = prompt("Password:"); if (!password) return;
  const mode = confirm("OK = Sign in, Cancel = Register") ? "login" : "register";
  try {
    const r = await api(`/auth/${mode}`, { method: "POST", body: JSON.stringify({ email, password }) });
    state.token = r.access_token; localStorage.setItem("pt_token", r.access_token);
    toast("Signed in"); location.reload();
  } catch (err) { toast(err.message, false); }
}

/* ---------- add problem modal ---------- */
const modal = document.getElementById("modal");
function openModal() {
  const sel = document.getElementById("mJudge");
  sel.innerHTML = state.providers.map(p => `<option value="${p.name}">${esc(p.label)}</option>`).join("")
    || `<option value="leetcode">LeetCode</option>`;
  // Default to HelloInterview if present (common manual case), else first.
  const hi = state.providers.find(p => p.name === "hellointerview");
  if (hi) sel.value = "hellointerview";
  ["mTitle", "mUrl", "mTopics", "mLang", "mCode"].forEach(id => document.getElementById(id).value = "");
  document.getElementById("mDiff").value = "";
  document.getElementById("mErr").textContent = "";
  modal.classList.remove("hidden"); modal.classList.add("flex");
}
function closeModal() { modal.classList.add("hidden"); modal.classList.remove("flex"); }
document.getElementById("addProblemBtn").addEventListener("click", openModal);
document.getElementById("modalClose").addEventListener("click", closeModal);
document.getElementById("mCancel").addEventListener("click", closeModal);
modal.addEventListener("click", e => { if (e.target === modal) closeModal(); });

document.getElementById("mSave").addEventListener("click", async () => {
  const judgeSel = document.getElementById("mJudge");
  const judge = state.providers.find(p => p.name === judgeSel.value)?.label || judgeSel.value || "LeetCode";
  const title = document.getElementById("mTitle").value.trim();
  const err = document.getElementById("mErr");
  if (!title) { err.textContent = "Title is required."; return; }
  const code = document.getElementById("mCode").value;
  const lang = document.getElementById("mLang").value.trim() || null;
  try {
    const p = await api("/problems", { method: "POST", body: JSON.stringify({
      judge, title,
      url: document.getElementById("mUrl").value.trim() || null,
      difficulty: document.getElementById("mDiff").value || null,
      topics: document.getElementById("mTopics").value.trim() || null,
      languages: lang,
    }) });
    if (code.trim()) {
      await api(`/problems/${p.id}/submissions/manual`, { method: "POST",
        body: JSON.stringify({ code, lang, status: "Accepted" }) });
    }
    toast("Problem added");
    closeModal(); loadProblems();
  } catch (e) { err.textContent = e.message; }
});

/* ---------- boot ---------- */
(async function init() {
  state.config = await api("/config");
  document.getElementById("modeBadge").textContent = state.config.mode + (state.config.llm_enabled ? " · AI" : "");
  renderAuth();
  if (state.config.auth_required && !state.token) { showTabShell(); return; }
  try { state.providers = await api("/providers"); } catch (_) { state.providers = []; }
  showTab("dashboard");
})();

function showTabShell() {
  document.querySelectorAll(".view").forEach(v => v.classList.add("hidden"));
  document.querySelector('[data-view="dashboard"]').classList.remove("hidden");
  document.getElementById("statCards").innerHTML = `<p class="text-muted text-sm col-span-4">Sign in to view your dashboard.</p>`;
}
