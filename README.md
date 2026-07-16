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
| Shared predicate engine | `app/engine/predicates.py` | One evaluator drives both the interview branching and the rule applicability check |
| Adaptive interview | `app/engine/interview.py` | Consultant-style branching questionnaire; each question tied to *why* it's asked |
| Knowledge base | `app/data/knowledge_base.json` + `app/engine/knowledge.py` | Structured CPSC rule objects with citations, exemptions, and verification tiers |
| Applicability engine | `app/engine/rules.py` | Matches product attributes → applicable rules + exemptions + certificate type |
| Certificate drafter | `app/engine/drafter.py` | Drafts a GCC or CPC with all required elements + gap analysis |
| Learning loop | `app/engine/knowledge.py` | Capture user-reported rules/exemptions into a review queue with verification tiers |
| Extraction | `app/engine/extract.py` | Pre-fills product attributes from pasted text / URL / test report (LLM-pluggable) |
| API + UI | `app/main.py`, `app/static/` | FastAPI backend + a zero-build web UI |

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000

Run the tests:

```bash
pip install -r requirements.txt
pytest -q
```

## How the flow works

1. **Intake** — create a product (optionally paste a description / URL / test report to
   pre-fill attributes via `extract.py`).
2. **Interview** — the engine serves the next relevant question; you answer; it re-branches.
   The interview is driven by the same predicate DSL the rules use.
3. **Assessment** — once enough is known, the applicability engine returns the certificate
   type (GCC vs CPC), the list of applicable rules with citations, and any exemptions.
4. **Draft** — generate a GCC/CPC draft with a gap analysis of what testing is still needed.
5. **Learn** — report a new rule/exemption; it enters the review queue as a structured object.

## Roadmap (post-MVP)

- **v2:** real URL scraping + PDF/OCR test-report parsing, RAG over eCFR + Federal Register
  APIs (so citations are always current), product dashboard, expiry reminders.
- **v3:** learning-loop with human-review approval + tiered knowledge, recall monitoring
  (SaferProducts.gov API), supplier/lab portals, audit-defense export packets.

See `app/engine/` for where each of these plugs in — the seams (LLM extraction, rule
sourcing, verification) are already stubbed.
