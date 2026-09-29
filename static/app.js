(() => {
  const $ = (s) => document.querySelector(s);
  const STATUS = { queued: "排队中", running: "进行中", done: "已完成", failed: "失败", cancelled: "已取消" };
  let serverConfig = {};
  let currentJob = null;
  let currentId = null;
  let es = null;
  let refreshTimer = null;

  // ---------- auth ----------
  const pw = {
    get: () => { try { return localStorage.getItem("craw_pw") || ""; } catch { return ""; } },
    set: (v) => { try { localStorage.setItem("craw_pw", v); } catch {} },
  };

  async function api(path, opts = {}) {
    const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
    if (pw.get()) headers["X-App-Password"] = pw.get();
    const res = await fetch(path, { ...opts, headers });
    if (res.status === 401) {
      await askPassword();
      return api(path, opts);
    }
    if (!res.ok) {
      let msg = `请求失败 (${res.status})`;
      try {
        const body = await res.json();
        if (typeof body.detail === "string") msg = body.detail;
        else if (Array.isArray(body.detail)) msg = body.detail.map((d) => d.msg).join("; ");
      } catch {}
      throw new Error(msg);
    }
    return res.json();
  }

  function askPassword() {
    return new Promise((resolve) => {
      const dlg = $("#pw-dialog");
      $("#pw-error").textContent = "";
      $("#pw-input").value = "";
      dlg.showModal();
      $("#pw-form").onsubmit = async (e) => {
        e.preventDefault();
        const val = $("#pw-input").value;
        const r = await fetch("/api/auth/check", { method: "POST", headers: { "X-App-Password": val } });
        if (r.ok) { pw.set(val); dlg.close(); resolve(); }
        else $("#pw-error").textContent = "密码错误";
      };
    });
  }

  function withPw(url) {
    const p = pw.get();
    return p ? `${url}${url.includes("?") ? "&" : "?"}pw=${encodeURIComponent(p)}` : url;
  }

  // ---------- helpers ----------
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmtTime = (t) => new Date(t * 1000).toLocaleTimeString();
  const fmtDate = (t) => new Date(t * 1000).toLocaleString();
  const isUrl = (v) => /^https?:\/\/\S+$/i.test(String(v || "").trim());
  function cell(v) {
    const s = String(v ?? "");
    if (isUrl(s)) {
      if (/\.(png|jpe?g|gif|webp|svg)(\?|$)/i.test(s)) return `<a href="${esc(s)}" target="_blank" rel="noopener"><img src="${esc(s)}" alt="" style="max-width:80px;max-height:60px"></a>`;
      return `<a href="${esc(s)}" target="_blank" rel="noopener noreferrer">${esc(s)}</a>`;
    }
    return `<div class="clip" title="${esc(s)}">${esc(s)}</div>`;
  }

  // ---------- init ----------
  async function init() {
    serverConfig = await fetch("/api/config").then((r) => r.json());
    $("#server-info").textContent = serverConfig.llm_enabled ? `AI 提取：${serverConfig.model}` : "基础模式（未配置大模型 API Key）";
    $("#max_pages").max = serverConfig.max_pages_limit;
    $("#max_depth").max = serverConfig.max_depth_limit;
    if (!serverConfig.browser_available) {
      $("#render_js").disabled = true;
      $("#browser-note").textContent = "（服务器未安装浏览器）";
    }
    if (serverConfig.password_required && !pw.get()) await askPassword();
    await loadJobs();
    const fromHash = location.hash.slice(1);
    if (fromHash) openJob(fromHash);
  }

  // ---------- job list ----------
  async function loadJobs() {
    const jobs = await api("/api/jobs");
    const ul = $("#job-list");
    ul.innerHTML = jobs.length ? "" : '<li class="muted">暂无任务</li>';
    for (const j of jobs) {
      const li = document.createElement("li");
      li.className = j.id === currentId ? "active" : "";
      li.innerHTML = `<div class="j-url">${esc(j.description || j.urls[0])}</div>
        <div class="j-meta"><span>${esc(j.urls[0])}</span></div>
        <div class="j-meta"><span class="st-${j.status}">${STATUS[j.status] || j.status} · ${j.record_count} 条</span><span>${fmtDate(j.created_at)}</span></div>`;
      li.onclick = () => openJob(j.id);
      ul.appendChild(li);
    }
  }
  $("#refresh-jobs").onclick = loadJobs;

  // ---------- create ----------
  $("#job-form").onsubmit = async (e) => {
    e.preventDefault();
    $("#form-error").textContent = "";
    const btn = $("#submit-btn");
    btn.disabled = true;
    try {
      const body = {
        urls: $("#urls").value.split(/\s+/).map((s) => s.trim()).filter(Boolean),
        description: $("#description").value.trim(),
        max_pages: +$("#max_pages").value || 1,
        max_depth: +$("#max_depth").value || 0,
        same_domain: $("#same_domain").checked,
        respect_robots: $("#respect_robots").checked,
        render_js: $("#render_js").checked,
      };
      const job = await api("/api/jobs", { method: "POST", body: JSON.stringify(body) });
      await loadJobs();
      openJob(job.id);
    } catch (err) {
      $("#form-error").textContent = err.message;
    } finally {
      btn.disabled = false;
    }
  };

  // ---------- job view ----------
  async function openJob(id) {
    if (es) { es.close(); es = null; }
    currentId = id;
    location.hash = id;
    let job;
    try { job = await api(`/api/jobs/${id}`); } catch (err) { $("#form-error").textContent = err.message; return; }
    currentJob = job;
    $("#empty").hidden = true;
    $("#job-view").hidden = false;
    if (window.innerWidth <= 900) $("#job-view").scrollIntoView({ behavior: "smooth" });
    $("#log").innerHTML = "";
    renderJob();
    loadJobs();
    // replay + follow progress
    es = new EventSource(withPw(`/api/jobs/${id}/events`));
    es.addEventListener("progress", (m) => {
      const ev = JSON.parse(m.data);
      appendLog(ev);
      Object.assign(currentJob, ev.job);
      renderHeader();
      if (["page", "plan", "done", "error"].includes(ev.level)) scheduleRefresh();
    });
    es.addEventListener("end", () => { es.close(); es = null; scheduleRefresh(); loadJobs(); });
    es.onerror = () => { if (es && es.readyState === EventSource.CLOSED) es = null; };
  }

  function scheduleRefresh() {
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(async () => {
      if (!currentId) return;
      currentJob = await api(`/api/jobs/${currentId}`);
      renderJob();
    }, 400);
  }

  function renderHeader() {
    const j = currentJob;
    $("#job-title").textContent = j.description || "（未填写描述）";
    $("#job-urls").textContent = j.urls.join("  ·  ");
    const st = $("#job-status");
    st.className = `badge st-${j.status}`;
    st.textContent = STATUS[j.status] || j.status;
    const active = j.status === "running" || j.status === "queued";
    $("#cancel-btn").hidden = !active;
    const total = Math.max(j.queued_pages || 0, j.pages_done || 0, 1);
    const pct = active ? Math.min(95, (100 * (j.pages_done || 0)) / total) : 100;
    $("#progress-bar").style.width = `${pct}%`;
    const usage = j.usage || {};
    const tokens = (usage.input_tokens || 0) + (usage.output_tokens || 0);
    $("#job-stats").innerHTML = `
      <span>已抓取 <b>${j.pages_done}</b> / ${j.queued_pages || j.max_pages} 页</span>
      <span>记录 <b>${j.record_count}</b> 条</span>
      ${tokens ? `<span>Tokens <b>${tokens.toLocaleString()}</b></span>` : ""}
      ${j.error ? `<span class="lv-error">${esc(j.error)}</span>` : ""}`;
  }

  function renderJob() {
    const j = currentJob;
    j.record_count = j.records.length;
    j.pages_done = j.pages.length;
    renderHeader();
    const plan = j.plan;
    $("#job-plan").innerHTML = plan
      ? `<div><b>AI 理解：</b>${esc(plan.summary)}</div>
         <div><b>每条记录：</b>${esc(plan.item_description)}</div>
         <div><b>字段：</b>${plan.fields.map((f) => `<span class="chip" title="${esc(f.description)}">${esc(f.label)}</span>`).join("")}</div>`
      : "";
    $("#count-results").textContent = `(${j.records.length})`;
    $("#count-pages").textContent = `(${j.pages.length})`;
    renderResults();
    renderPages();
  }

  function renderResults() {
    const j = currentJob;
    const fields = (j.plan?.fields || []).map((f) => [f.key, f.label]);
    const known = new Set(fields.map((f) => f[0]).concat("_source"));
    for (const r of j.records) for (const k of Object.keys(r)) if (!known.has(k)) { known.add(k); fields.push([k, k]); }
    fields.push(["_source", "来源页面"]);
    const q = $("#filter").value.trim().toLowerCase();
    const rows = q ? j.records.filter((r) => Object.values(r).some((v) => String(v).toLowerCase().includes(q))) : j.records;
    const t = $("#results-table");
    if (!rows.length) { t.innerHTML = `<tr><td class="muted">${j.records.length ? "无匹配结果" : "暂无结果"}</td></tr>`; return; }
    t.innerHTML = `<thead><tr><th>#</th>${fields.map(([, l]) => `<th>${esc(l)}</th>`).join("")}</tr></thead>
      <tbody>${rows.slice(0, 2000).map((r, i) => `<tr><td>${i + 1}</td>${fields.map(([k]) => `<td>${cell(r[k])}</td>`).join("")}</tr>`).join("")}</tbody>`;
  }
  $("#filter").oninput = () => currentJob && renderResults();

  function renderPages() {
    const pages = currentJob.pages;
    const t = $("#pages-table");
    if (!pages.length) { t.innerHTML = '<tr><td class="muted">暂无</td></tr>'; return; }
    const label = { ok: "成功", error: "失败", blocked: "robots 禁止" };
    t.innerHTML = `<thead><tr><th>#</th><th>页面</th><th>标题</th><th>深度</th><th>状态</th><th>记录数</th></tr></thead>
      <tbody>${pages.map((p, i) => `<tr><td>${i + 1}</td><td>${cell(p.url)}</td><td>${esc(p.title || "")}</td><td>${p.depth}</td>
      <td class="${p.status === "ok" ? "" : "lv-error"}" title="${esc(p.error || "")}">${label[p.status] || p.status}</td><td>${p.records}</td></tr>`).join("")}</tbody>`;
  }

  function appendLog(ev) {
    const li = document.createElement("li");
    li.className = `lv-${ev.level}`;
    li.innerHTML = `<time>${fmtTime(ev.ts)}</time>${esc(ev.message)}`;
    const log = $("#log");
    const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
    log.appendChild(li);
    if (atBottom) log.scrollTop = log.scrollHeight;
  }

  // ---------- actions ----------
  $("#cancel-btn").onclick = async () => { await api(`/api/jobs/${currentId}/cancel`, { method: "POST" }); };
  $("#delete-btn").onclick = async () => {
    if (!confirm("确定删除该任务及其结果？")) return;
    await api(`/api/jobs/${currentId}`, { method: "DELETE" });
    if (es) es.close();
    currentId = null; currentJob = null; location.hash = "";
    $("#job-view").hidden = true; $("#empty").hidden = false;
    loadJobs();
  };
  $("#export-csv").onclick = () => window.open(withPw(`/api/jobs/${currentId}/export?format=csv`));
  $("#export-json").onclick = () => window.open(withPw(`/api/jobs/${currentId}/export?format=json`));

  document.querySelectorAll(".tab").forEach((b) => {
    b.onclick = () => {
      document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === b));
      document.querySelectorAll(".tab-body").forEach((x) => (x.hidden = x.dataset.body !== b.dataset.tab));
    };
  });

  init().catch((err) => { $("#form-error").textContent = err.message; });
})();
