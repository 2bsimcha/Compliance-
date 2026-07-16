"use strict";

const $ = (id) => document.getElementById(id);
const api = async (path, opts = {}) => {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
  return res.json();
};

let productId = null;

// ---- Intake ----------------------------------------------------------------
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
  productId = data.id;
  $("prod-label").textContent = "· " + data.name;
  $("interview").classList.remove("hidden");
  showExtracted(data.attrs);
  loadQuestion();
};

function showExtracted(attrs) {
  const hints = Object.entries(attrs).filter(([k]) => !k.startsWith("_"));
  $("extracted").textContent = hints.length
    ? "Pre-filled from your input: " + hints.map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ")
    : "";
}

// ---- Interview -------------------------------------------------------------
async function loadQuestion() {
  const data = await api(`/api/products/${productId}/next-question`);
  $("progress").textContent = `Answered ${data.progress.answered} of ${data.progress.relevant} relevant questions`;
  if (data.complete) {
    $("question").innerHTML = `<p class="ok">Consultation complete — running assessment…</p>`;
    return loadAssessment();
  }
  renderQuestion(data.question);
}

function renderQuestion(q) {
  const box = $("question");
  box.innerHTML = `
    <div class="q-prompt">${q.prompt}</div>
    <div class="q-reason">Why I'm asking: ${q.reason}</div>
    <div class="q-cite">${q.citation}</div>
    <div id="answer-area"></div>`;
  const area = $("answer-area");

  if (q.type === "bool") {
    area.innerHTML = `<div class="choices">
      <div class="choice" data-v="true">Yes</div>
      <div class="choice" data-v="false">No</div></div>`;
    area.querySelectorAll(".choice").forEach((el) => {
      el.onclick = () => submit(q.key, el.dataset.v === "true");
    });
  } else if (q.type === "int") {
    area.innerHTML = `<input id="int-in" type="number" placeholder="e.g. 3" />
      <button id="int-go">Next</button>`;
    $("int-go").onclick = () => {
      const v = parseInt($("int-in").value, 10);
      if (Number.isNaN(v)) return alert("Enter a number.");
      submit(q.key, v);
    };
  } else if (q.type === "single") {
    area.innerHTML = `<div class="choices">${q.choices
      .map((c) => `<div class="choice" data-v="${c}">${c}</div>`)
      .join("")}</div>`;
    area.querySelectorAll(".choice").forEach((el) => {
      el.onclick = () => submit(q.key, el.dataset.v);
    });
  } else if (q.type === "multi") {
    const sel = new Set();
    area.innerHTML = `<div class="choices">${q.choices
      .map((c) => `<div class="choice" data-v="${c}">${c}</div>`)
      .join("")}</div><button id="multi-go">Next</button>`;
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
  await api(`/api/products/${productId}/answer`, {
    method: "POST",
    body: JSON.stringify({ key, value }),
  });
  loadQuestion();
}

// ---- Assessment ------------------------------------------------------------
async function loadAssessment() {
  const a = await api(`/api/products/${productId}/assessment`);
  $("assessment").classList.remove("hidden");
  const certBadge =
    a.certificate_type === "CPC"
      ? `<span class="badge cpc">CPC required</span>`
      : a.certificate_type === "GCC"
      ? `<span class="badge gcc">GCC required</span>`
      : `<span class="badge">undetermined</span>`;

  let html = `<p><strong>Certificate type:</strong> ${certBadge}</p>`;
  if (a.third_party_testing_required) {
    html += `<p class="gap">⚠ Third-party lab testing is required (see flagged rules below).</p>`;
  }
  html += `<p class="muted">${a.applicable_rules.length} applicable rule(s):</p>`;

  for (const r of a.applicable_rules) {
    html += `<div class="rule">
      <h4>${r.title}
        ${r.third_party_testing && !r.exemptions_met.length ? '<span class="badge test">lab test</span>' : ""}
        ${r.exemptions_met.length ? '<span class="badge exempt">exemption</span>' : ""}
      </h4>
      <div class="cite">${r.citation}</div>
      <div class="muted">${r.summary}</div>
      ${r.exemptions_met
        .map((e) => `<div class="exemption">Exemption available: ${e.summary} <br/><span class="cite">${e.citation}</span></div>`)
        .join("")}
    </div>`;
  }
  $("assessment-body").innerHTML = html;
  $("btn-draft").classList.remove("hidden");
}

$("btn-draft").onclick = async () => {
  const out = await api(`/api/products/${productId}/draft`, {
    method: "POST",
    body: JSON.stringify({}),
  });
  $("draft").classList.remove("hidden");
  const gaps = out.gap_analysis.outstanding;
  let html = `<p><strong>${out.draft.certificate_type}</strong> draft generated ${out.draft.issued_on}</p>`;
  html += `<pre>${JSON.stringify(out.draft, null, 2)}</pre>`;
  html += `<h3 style="font-size:14px">Gap analysis</h3>`;
  html += out.gap_analysis.ready_to_issue
    ? `<p class="ok">✓ All required fields present — ready to finalize.</p>`
    : gaps.map((g) => `<div class="gap">• ${g}</div>`).join("");
  $("draft-body").innerHTML = html;
};

// ---- Learning loop ---------------------------------------------------------
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
