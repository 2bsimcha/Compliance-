# Compliance — CPSC Compliance Consultant (MVP)

An AI-assisted CPSC compliance tool that acts like a human consultant: you plug in a
product (description, URL, or test report), and it runs an **adaptive interview** to
understand the full scope of the product, determines which regulations apply **with
citations and exemptions**, and drafts the required **GCC / CPC** certificate on your
behalf.

Unlike the CPSC Regulatory Robot, this tool is:

- **Personalized** — it branches its questions based on what your product actually is,
  and only asks what is relevant.
- **Citation-first** — every applicable rule and every exemption comes with its legal
  citation (16 CFR part, statute section, ASTM number).
- **Self-learning** — when you tell it about a new law or exemption, it captures that
  knowledge as a *structured rule object* (behind a verification queue) so future
  products benefit.

> ⚠️ **Not legal advice.** This tool provides compliance *guidance*. Children's Product
> Certificates require third-party testing at a CPSC-accepted laboratory. Always keep a
> qualified human/lab in the loop before certifying.

## What's in this MVP

| Piece | Where | What it does |
|-------|-------|--------------|
| **Product dashboard** | `app/main.py`, `app/static/` | Multi-SKU portfolio: aggregate stats + a table of every product with its live compliance state; click through to resume any product's interview, view its assessment, and manage drafts |
| Shared predicate engine | `app/engine/predicates.py` | One evaluator drives both the interview branching and the rule applicability check |
| Adaptive interview | `app/engine/interview.py` | Consultant-style branching questionnaire; each question tied to *why* it's asked |
| Knowledge base | `app/data/knowledge_base.json` + `app/engine/knowledge.py` | Structured CPSC rule objects with citations, exemptions, and verification tiers |
| Applicability engine | `app/engine/rules.py` | Matches product attributes → applicable rules + exemptions + certificate type |
| Certificate drafter | `app/engine/drafter.py` | Drafts a GCC or CPC with all required elements + gap analysis |
| **PDF export** | `app/engine/pdf.py` | Renders a drafted GCC/CPC to a printable PDF, with a DRAFT watermark + outstanding-items section when it isn't yet issuable |
| **Test-report parsing** | `app/engine/report.py` | Upload a lab test-report PDF → extract text → parse tested standards + results → **coverage gap analysis** vs. the testing the assessment requires (covered / missing / failed) |
| Learning loop | `app/engine/knowledge.py` | Capture user-reported rules/exemptions into a review queue with verification tiers |
| **Live eCFR** | `app/engine/ecfr.py` | Talks to the official eCFR API: Title 16 currency, live section text by citation, full-text search, and per-rule "refresh against source" |
| Extraction | `app/engine/extract.py` | Pre-fills product attributes from pasted text / URL / test report — **Claude-backed** (structured output) with a heuristic fallback |
| API + UI | `app/main.py`, `app/static/` | FastAPI backend + a zero-build web UI |

## Live eCFR integration

`app/engine/ecfr.py` wires the tool to the official, free **eCFR API**
(`https://www.ecfr.gov`) so citations are backed by live regulation text, not a static
copy:

| Endpoint | What it returns |
|----------|-----------------|
| `GET /api/ecfr/currency` | How current Title 16 (CPSC) is — the date eCFR content is up to date as of |
| `GET /api/ecfr/section?citation=16 CFR 1303` | The live CFR text for a citation (XML flattened to readable text) |
| `GET /api/ecfr/search?q=lead in paint` | Full-text CFR search, scoped to Title 16 |
| `POST /api/knowledge/refresh` | Refreshes every seed rule against its live source; reports which citations still resolve and how current they are |

Design guarantees:

- **Graceful degradation.** Every eCFR call returns `{"ok": false, "error": ...}` instead
  of raising, so a blocked host or an eCFR outage never breaks assessments (which don't
  depend on the network). If your environment's egress policy blocks `ecfr.gov`, the UI
  simply shows "live lookups unavailable" and everything else keeps working.
- **Caching.** Responses are cached in `ecfr_cache` (SQLite) with a TTL, so eCFR isn't
  hammered; failures are never cached.
- **Fully testable offline.** The HTTP client is injectable, so the whole integration is
  tested with `httpx.MockTransport` — no live network needed (`tests/test_ecfr*.py`).

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000

### Authentication

The whole instance can sit behind a single shared password. Set `APP_PASSWORD` to enable
it (with it unset, auth is disabled for local dev):

```bash
export APP_PASSWORD=your-strong-password   # enables the login gate
export APP_USERNAME=admin                  # optional, defaults to "admin"
export SESSION_SECRET=$(openssl rand -hex 32)  # optional; stable secret across restarts
```

### Database

SQLite by default (zero config, `./compliance.db`). Set `DATABASE_URL` to a Postgres
connection string to use Postgres instead — the app normalizes the scheme and uses native
`JSONB` columns automatically. No code change needed.

```bash
export DATABASE_URL=postgresql://user:pass@host:5432/dbname   # optional; Postgres
```

### Deploying to a live website

See **[DEPLOY.md](DEPLOY.md)** for a step-by-step Render deployment (custom domain +
HTTPS + managed Postgres), plus notes for Railway, Fly.io, or your own server. A
`render.yaml` Blueprint is included and provisions the database for you.

Run the tests:

```bash
pip install -r requirements.txt
pytest -q
```

## LLM extraction (Claude)

`app/engine/extract.py` turns an unstructured description, web-page text, or test report
into structured product attributes that pre-fill the interview.

- **Backend:** when `ANTHROPIC_API_KEY` is set, it calls the Anthropic Messages API with a
  **structured-output schema** (`messages.parse` + a Pydantic model), so the model fills a
  validated object mapped to the exact controlled vocabulary the rules engine uses — no
  free-text parsing. Model defaults to `claude-opus-4-8`; override with
  `COMPLIANCE_LLM_MODEL` (e.g. `claude-haiku-4-5`) to trade cost for capability.
- **Offline fallback:** with no key (or on any API error) it uses transparent keyword
  heuristics, so the whole app runs with zero configuration.

Two guarantees keep it safe:

- **Never authoritative on the critical fork.** Extraction returns the child age as a
  *hint* (`intended_age_max_hint`), never the authoritative value — the consultant
  interview still asks and confirms the single biggest CPSC fork (children's vs
  general-use). Everything else it fills is a head-start the interview skips if known.
- **Never blocks intake.** Any LLM failure falls back to heuristics with the error
  recorded in `_llm_error`; extraction never raises.

```bash
export ANTHROPIC_API_KEY=sk-ant-...        # enable Claude extraction
export COMPLIANCE_LLM_MODEL=claude-haiku-4-5  # optional: cheaper model
```

## Product dashboard

The home screen is a **portfolio dashboard** across all your products (SKUs):

- **Aggregate stats** — total products, how many need lab testing, how many interviews
  are still open, how many have drafts, and the CPC/GCC split.
- **Product table** — each row shows the product's company, status, certificate type,
  applicable-rule count (with a "lab" flag when testing is required), interview progress,
  and draft count. Every row's compliance state is computed live from stored answers
  against the current rule set — so a newly-verified community rule instantly updates the
  whole portfolio.
- **Click through** to a product to resume its interview mid-flow, view its assessment
  (with live eCFR lookups), draft/manage certificates, or delete it.

Dashboard API: `GET /api/products` (summaries), `GET /api/dashboard` (aggregates),
`DELETE /api/products/{id}`, `GET /api/products/{id}/certificates`.

## How the flow works

1. **Intake** — create a product (optionally paste a description / URL / test report to
   pre-fill attributes via `extract.py`).
2. **Interview** — the engine serves the next relevant question; you answer; it re-branches.
   The interview is driven by the same predicate DSL the rules use.
3. **Assessment** — once enough is known, the applicability engine returns the certificate
   type (GCC vs CPC), the list of applicable rules with citations, and any exemptions.
4. **Draft** — generate a GCC/CPC draft with a gap analysis of what testing is still needed,
   and **download it as a PDF** (`GET /api/products/{id}/certificates/{cert_id}/pdf`). An
   unfinished certificate carries a visible **DRAFT** watermark and an outstanding-items
   section, so it can't be mistaken for a final, issuable certificate.
5. **Test reports** — upload a lab test-report PDF on the product. It's parsed (Claude
   structured output, heuristic fallback) into tested standards + results, then
   **coverage-checked** against the rules that require third-party testing: which
   required tests are covered, which are still missing, and any that were tested but
   *failed*. (Text-based PDFs; OCR for scanned reports is a future addition.)
6. **Learn** — report a new rule/exemption; it enters the review queue as a structured object.

## Roadmap (post-MVP)

- **v2:** real URL scraping + PDF/OCR test-report parsing, RAG over eCFR + Federal Register
  APIs (so citations are always current), product dashboard, expiry reminders.
- **v3:** learning-loop with human-review approval + tiered knowledge, recall monitoring
  (SaferProducts.gov API), supplier/lab portals, audit-defense export packets.

See `app/engine/` for where each of these plugs in — the seams (LLM extraction, rule
sourcing, verification) are already stubbed.
