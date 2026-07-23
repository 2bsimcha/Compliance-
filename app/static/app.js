"use strict";

const $ = (id) => document.getElementById(id);
const api = async (path, opts = {}) => {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (res.status === 401) {
    // Session expired or not signed in — bounce to the login page.
    window.location.href = "/login";
    throw new Error("Not authenticated");
  }
  if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
  return res.json();
};
const escapeHtml = (s) =>
  (s || "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

let productId = null;

const CERT_BADGE = {
  CPC: '<span class="badge cpc">CPC</span>',
  GCC: '<span class="badge gcc">GCC</span>',
  undetermined: '<span class="badge">—</span>',
};

// ===========================================================================
// View switching
// ===========================================================================
function showDashboard() {
  $("view-product").classList.add("hidden");
  $("view-dashboard").classList.remove("hidden");
  loadDashboard();
}
function showProduct() {
  $("view-dashboard").classList.add("hidden");
  $("view-product").classList.remove("hidden");
}
$("btn-back").onclick = showDashboard;
$("home-link").onclick = showDashboard;

// ===========================================================================
// Dashboard
// ===========================================================================
async function loadDashboard() {
  const [stats, products] = await Promise.all([api("/api/dashboard"), api("/api/products")]);
  renderStats(stats);
  renderProductList(products);
}

function renderStats(s) {
  const tiles = [
    ["Products", s.total],
    ["Need lab testing", s.needing_testing],
    ["Interviews open", s.interviews_incomplete],
    ["With drafts", s.with_drafts],
    ["CPC", s.by_certificate_type?.CPC || 0],
    ["GCC", s.by_certificate_type?.GCC || 0],
  ];
  $("stats").innerHTML = tiles
    .map(([label, val]) => `<div class="stat"><div class="stat-val">${val}</div><div class="stat-label">${label}</div></div>`)
    .join("");
}

function renderProductList(products) {
  $("prod-count").textContent = `(${products.length})`;
  if (!products.length) {
    $("product-list").innerHTML = `<p class="muted">No products yet. Click “＋ New product” to start a consultation.</p>`;
    return;
  }
  $("product-list").innerHTML = `
    <table class="grid">
      <thead><tr>
        <th>Product</th><th>Company</th><th>Status</th><th>Cert</th>
        <th>Rules</th><th>Interview</th><th>Drafts</th><th></th>
      </tr></thead>
      <tbody>
        ${products.map(rowFor).join("")}
      </tbody>
    </table>`;
  $("product-list").querySelectorAll("[data-open]").forEach((el) => {
    el.onclick = () => openProduct(parseInt(el.dataset.open, 10));
  });
}

function rowFor(p) {
  const interview = p.interview_complete
    ? '<span class="ok">complete</span>'
    : `${p.questions_answered}/${p.questions_relevant}`;
  const testing = p.testing_required ? ' <span class="badge test">lab</span>' : "";
  return `<tr class="clickable" data-open="${p.id}">
    <td><strong>${escapeHtml(p.name)}</strong></td>
    <td>${escapeHtml(p.company_name || "—")}</td>
    <td><span class="status s-${p.status}">${p.status}</span></td>
    <td>${CERT_BADGE[p.certificate_type] || "—"}</td>
    <td>${p.applicable_count}${testing}</td>
    <td>${interview}</td>
    <td>${p.certificate_count || 0}</td>
    <td class="chev">›</td>
  </tr>`;
}

// ---- Intake ----------------------------------------------------------------
$("btn-new").onclick = () => {
  $("intake").classList.remove("hidden");
  $("p-name").focus();
};
$("btn-cancel-new").onclick = () => {
  $("intake").classList.add("hidden");
  ["p-name", "p-company", "p-source"].forEach((id) => ($(id).value = ""));
};
$("btn-create").onclick = async () => {
  const name = $("p-name").value.trim();
  if (!name) return alert("Give the product a name.");
  const data = await api("/api/products", {
    method: "POST",
    body: JSON.stringify({
      name,
      company_name: $("p-company").value.trim() || null,
      source_input: $("p-source").value.trim() || null,
    }),
  });
  $("btn-cancel-new").onclick();
  openProduct(data.id, data.attrs);
};

// ===========================================================================
// Product detail
// ===========================================================================
async function openProduct(id, prefetchedAttrs) {
  productId = id;
  const p = await api(`/api/products/${id}`);
  $("pd-name").textContent = p.name;
  $("pd-meta").innerHTML =
    `${p.company_name ? escapeHtml(p.company_name) + " · " : ""}status: <span class="status s-${p.status}">${p.status}</span>` +
    (p.updated_at ? ` · updated ${new Date(p.updated_at).toLocaleString()}` : "");
  showProduct();
  ["pd-assessment", "pd-drafts"].forEach((s) => $(s).classList.add("hidden"));
  $("btn-draft").classList.add("hidden");
  showExtracted(prefetchedAttrs || p.attrs);
  $("report-file").value = "";
  $("report-status").textContent = "";
  loadDrafts();
  loadReports();
  loadQuestion();
}

$("btn-delete").onclick = async () => {
  if (!confirm("Delete this product and its drafts?")) return;
  await api(`/api/products/${productId}`, { method: "DELETE" });
  showDashboard();
};

function showExtracted(attrs) {
  attrs = attrs || {};
  const hints = Object.entries(attrs).filter(([k]) => !k.startsWith("_"));
  let html = "";
  if (attrs._fetch_error) {
    html += `<div class="gap">Couldn't fetch that URL (${escapeHtml(attrs._fetch_error)}). Try pasting the product description instead.</div>`;
  } else if (attrs._fetched_url) {
    html += `<div class="ok">Fetched page: ${escapeHtml(attrs._fetched_url)}</div>`;
  }
  if (hints.length) {
    html += `Known so far: ` + hints.map(([k, v]) => `${k}=${escapeHtml(JSON.stringify(v))}`).join(", ");
  }
  $("extracted").innerHTML = html;
}

// ---- Interview -------------------------------------------------------------
async function loadQuestion() {
  const data = await api(`/api/products/${productId}/next-question`);
  $("progress").textContent = `Answered ${data.progress.answered} of ${data.progress.relevant} relevant questions`;
  if (data.complete) {
    $("question").innerHTML = `<p class="ok">Consultation complete.</p>`;
    return loadAssessment();
  }
  renderQuestion(data.question);
}

function renderQuestion(q) {
  $("question").innerHTML = `
    <div class="q-prompt">${q.prompt}</div>
    <div class="q-reason">Why I'm asking: ${q.reason}</div>
    <div class="q-cite">${q.citation}</div>
    <div id="answer-area"></div>`;
  const area = $("answer-area");

  if (q.type === "bool") {
    area.innerHTML = `<div class="choices">
      <div class="choice" data-v="true">Yes</div>
      <div class="choice" data-v="false">No</div></div>`;
    area.querySelectorAll(".choice").forEach((el) => (el.onclick = () => submit(q.key, el.dataset.v === "true")));
  } else if (q.type === "int") {
    area.innerHTML = `<input id="int-in" type="number" placeholder="e.g. 3" /><button id="int-go">Next</button>`;
    $("int-go").onclick = () => {
      const v = parseInt($("int-in").value, 10);
      if (Number.isNaN(v)) return alert("Enter a number.");
      submit(q.key, v);
    };
  } else if (q.type === "single") {
    area.innerHTML = `<div class="choices">${q.choices.map((c) => `<div class="choice" data-v="${c}">${c}</div>`).join("")}</div>`;
    area.querySelectorAll(".choice").forEach((el) => (el.onclick = () => submit(q.key, el.dataset.v)));
  } else if (q.type === "multi") {
    const sel = new Set();
    area.innerHTML =
      `<div class="choices">${q.choices.map((c) => `<div class="choice" data-v="${c}">${c}</div>`).join("")}</div>` +
      `<button id="multi-go">Next</button>`;
    area.querySelectorAll(".choice").forEach((el) => {
      el.onclick = () => {
        el.classList.toggle("sel");
        el.classList.contains("sel") ? sel.add(el.dataset.v) : sel.delete(el.dataset.v);
      };
    });
    $("multi-go").onclick = () => submit(q.key, [...sel]);
  }
}

async function submit(key, value) {
  const r = await api(`/api/products/${productId}/answer`, {
    method: "POST",
    body: JSON.stringify({ key, value }),
  });
  showExtracted(r.attrs);
  loadQuestion();
}

// ---- Assessment ------------------------------------------------------------
async function loadAssessment() {
  const a = await api(`/api/products/${productId}/assessment`);
  $("pd-assessment").classList.remove("hidden");
  let html = `<p><strong>Certificate type:</strong> ${CERT_BADGE[a.certificate_type] || "—"}</p>`;
  if (a.third_party_testing_required)
    html += `<p class="gap">⚠ Third-party lab testing is required (see flagged rules below).</p>`;
  html += `<p class="muted">${a.applicable_rules.length} applicable rule(s):</p>`;

  for (const r of a.applicable_rules) {
    html += `<div class="rule">
      <h4>${r.title}
        ${r.third_party_testing && !r.exemptions_met.length ? '<span class="badge test">lab test</span>' : ""}
        ${r.exemptions_met.length ? '<span class="badge exempt">exemption</span>' : ""}
      </h4>
      <div class="cite">${r.citation}</div>
      <div class="muted">${r.summary}</div>
      ${r.exemptions_met.map((e) => `<div class="exemption">Exemption available: ${e.summary}<br/><span class="cite">${e.citation}</span></div>`).join("")}
      <button class="secondary btn-live" data-cite="${encodeURIComponent(r.citation)}">View live CFR text</button>
      <div class="live-text"></div>
    </div>`;
  }
  $("assessment-body").innerHTML = html;
  $("assessment-body").querySelectorAll(".btn-live").forEach((btn) => (btn.onclick = () => loadLiveText(btn)));
  $("btn-draft").classList.remove("hidden");
}

async function loadLiveText(btn) {
  const cite = decodeURIComponent(btn.dataset.cite);
  const box = btn.nextElementSibling;
  box.innerHTML = `<span class="muted">Fetching ${cite} from eCFR…</span>`;
  try {
    const d = await api(`/api/ecfr/section?citation=${encodeURIComponent(cite)}`);
    if (!d.ok) return (box.innerHTML = `<span class="gap">Live text unavailable: ${d.error}</span>`);
    box.innerHTML =
      `<div class="muted">Current as of ${d.current_as_of}${d._cached ? " (cached)" : ""} · <a href="${d.source_url}" target="_blank" rel="noopener">source</a></div>` +
      `<pre>${escapeHtml(d.heading ? d.heading + "\n\n" : "")}${escapeHtml(d.text)}${d.truncated ? "\n…(truncated)" : ""}</pre>`;
  } catch (e) {
    box.innerHTML = `<span class="gap">Lookup failed: ${e.message}</span>`;
  }
}

// ---- Drafts ----------------------------------------------------------------
$("btn-draft").onclick = async () => {
  await api(`/api/products/${productId}/draft`, { method: "POST", body: JSON.stringify({}) });
  loadDrafts();
};

async function loadDrafts() {
  const certs = await api(`/api/products/${productId}/certificates`);
  if (!certs.length) {
    $("pd-drafts").classList.add("hidden");
    return;
  }
  $("pd-drafts").classList.remove("hidden");
  $("drafts-body").innerHTML = certs
    .map((c) => {
      const gaps = c.gap_analysis.outstanding || [];
      return `<div class="rule">
        <h4>${c.cert_type} draft
          ${c.ready_to_issue ? '<span class="badge gcc">ready</span>' : '<span class="badge test">gaps</span>'}
        </h4>
        <div class="muted">${c.created_at ? new Date(c.created_at).toLocaleString() : ""}</div>
        <a class="secondary btn-pdf" href="/api/products/${productId}/certificates/${c.id}/pdf">Download PDF ↓</a>
        <details><summary class="muted">Show certificate JSON</summary><pre>${escapeHtml(JSON.stringify(c.draft, null, 2))}</pre></details>
        ${
          c.ready_to_issue
            ? '<p class="ok">✓ All required fields present — ready to finalize.</p>'
            : `<div class="muted" style="margin-top:6px">Gap analysis:</div>` + gaps.map((g) => `<div class="gap">• ${g}</div>`).join("")
        }
      </div>`;
    })
    .join("");
}

// ---- Test reports ----------------------------------------------------------
$("btn-upload-report").onclick = async () => {
  const input = $("report-file");
  if (!input.files.length) return alert("Choose a PDF test report first.");
  const fd = new FormData();
  fd.append("file", input.files[0]);
  $("report-status").textContent = "Uploading and analyzing…";
  try {
    const res = await fetch(`/api/products/${productId}/test-reports`, { method: "POST", body: fd });
    if (res.status === 401) return (window.location.href = "/login");
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    input.value = "";
    $("report-status").textContent = "";
    loadReports();
  } catch (e) {
    $("report-status").innerHTML = `<span class="gap">${e.message}</span>`;
  }
};

async function loadReports() {
  const reports = await api(`/api/products/${productId}/test-reports`);
  if (!reports.length) {
    $("reports-body").innerHTML = "";
    return;
  }
  $("reports-body").innerHTML = reports.map(reportCard).join("");
  $("reports-body").querySelectorAll("[data-del-report]").forEach((el) => {
    el.onclick = async () => {
      if (!confirm("Delete this test report?")) return;
      await api(`/api/products/${productId}/test-reports/${el.dataset.delReport}`, { method: "DELETE" });
      loadReports();
    };
  });
}

function reportCard(r) {
  const f = r.findings || {};
  const c = r.coverage || {};
  const meta = [f.lab_name, f.cpsc_lab_code, f.report_date].filter(Boolean).join(" · ");

  let cov;
  if (!c.required_count) {
    cov = `<p class="muted">This product's assessment requires no third-party lab testing.</p>`;
  } else if (c.fully_covered) {
    cov = `<p class="ok">✓ All ${c.required_count} required test(s) covered by this report.</p>`;
  } else {
    cov = `<p class="muted">${(c.covered || []).length} of ${c.required_count} required test(s) covered.</p>`;
  }

  const line = (item, cls, label) =>
    `<div class="${cls}">${label}: ${item.title} <span class="cite">${item.citation}</span>${
      item.tested_as ? ` — tested as ${item.tested_as}` : ""
    }</div>`;

  const failed = (c.failed || []).map((i) => line(i, "gap", "⚠ FAILED")).join("");
  const missing = (c.missing || []).map((i) => line(i, "gap", "Missing")).join("");
  const covered = (c.covered || []).map((i) => line(i, "ok", "✓ Covered")).join("");

  const tested = (f.tested || [])
    .map((t) => {
      const badge =
        t.result === "pass" ? '<span class="badge gcc">pass</span>'
        : t.result === "fail" ? '<span class="badge cpc">fail</span>'
        : '<span class="badge">—</span>';
      return `<div class="muted">${t.standard} ${badge}${t.notes ? " · " + t.notes : ""}</div>`;
    })
    .join("");

  const note = f._note ? `<div class="gap">${f._note}</div>` : "";
  const src = f._source === "heuristic"
    ? `<div class="muted" style="font-size:11px">Parsed without LLM (set ANTHROPIC_API_KEY for full extraction).</div>`
    : "";

  return `<div class="rule">
    <h4>${escapeHtml(r.filename)}
      <button class="secondary" data-del-report="${r.id}" style="float:right;padding:4px 10px;font-size:12px">Delete</button>
    </h4>
    ${meta ? `<div class="muted">${escapeHtml(meta)}</div>` : ""}
    ${cov}
    ${failed}${missing}${covered}
    ${tested ? `<details><summary class="muted">Tested standards (${(f.tested || []).length})</summary>${tested}</details>` : ""}
    ${note}${src}
  </div>`;
}

// ===========================================================================
// Global panels: eCFR + learning loop + currency
// ===========================================================================
// Show the logout link only when auth is actually enabled on the server.
(async function showLogout() {
  try {
    const h = await fetch("/healthz").then((r) => r.json());
    if (h.auth) $("logout-link").classList.remove("hidden");
  } catch (e) {
    /* ignore */
  }
})();

(async function showCurrency() {
  try {
    const d = await api("/api/ecfr/currency");
    $("ecfr-currency").textContent = d.ok
      ? `eCFR Title 16 (CPSC) current as of ${d.up_to_date_as_of}${d._cached ? " · cached" : ""}`
      : `eCFR live lookups unavailable here: ${d.error}`;
  } catch (e) {
    $("ecfr-currency").textContent = "eCFR live lookups unavailable in this environment.";
  }
})();

$("btn-ecfr-search").onclick = async () => {
  const q = $("e-query").value.trim();
  if (!q) return;
  $("ecfr-results").innerHTML = `<span class="muted">Searching eCFR…</span>`;
  try {
    const d = await api(`/api/ecfr/search?q=${encodeURIComponent(q)}`);
    if (!d.ok) return ($("ecfr-results").innerHTML = `<span class="gap">${d.error}</span>`);
    $("ecfr-results").innerHTML =
      `<p class="muted">${d.total ?? d.results.length} result(s)</p>` +
      d.results
        .map(
          (r) => `<div class="rule">
            <h4>${r.heading || r.citation || ""}</h4>
            <div class="muted">${r.excerpt || ""}</div>
            ${r.url ? `<a class="cite" href="${r.url}" target="_blank" rel="noopener">${r.url}</a>` : ""}
          </div>`
        )
        .join("");
  } catch (e) {
    $("ecfr-results").innerHTML = `<span class="gap">${e.message}</span>`;
  }
};

$("btn-report").onclick = async () => {
  const title = $("k-title").value.trim();
  if (!title) return alert("Give the rule a title.");
  const out = await api("/api/knowledge/report", {
    method: "POST",
    body: JSON.stringify({
      title,
      citation: $("k-citation").value.trim() || null,
      summary: $("k-summary").value.trim() || null,
      source_url: $("k-source").value.trim() || null,
      reported_by: "web-user",
    }),
  });
  let html = `<p class="ok">✓ Filed for review (id ${out.db_id}). ${out.note}</p>`;
  if (out.follow_up_questions.length) {
    html += `<p class="muted">To make this usable, a reviewer/you still need:</p>`;
    html += out.follow_up_questions.map((q) => `<div class="gap">• ${q.prompt}</div>`).join("");
  }
  $("report-result").innerHTML = html;
};

// Boot
showDashboard();
