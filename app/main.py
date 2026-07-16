"""FastAPI application wiring the engine to an HTTP API + static web UI.

Endpoints
---------
POST   /api/products                      create a product (optionally pre-fill from text/URL/report)
GET    /api/products                      list products
GET    /api/products/{id}                 product detail (attrs + status)
GET    /api/products/{id}/next-question   the next relevant interview question
POST   /api/products/{id}/answer          record an interview answer
GET    /api/products/{id}/assessment      applicability assessment (rules + citations + exemptions)
POST   /api/products/{id}/draft           draft a GCC/CPC + gap analysis
GET    /api/knowledge                     list knowledge-base rules (official + community)
POST   /api/knowledge/report              capture a user-reported rule (learning loop)
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db, init_db
from .engine import drafter, extract, interview, knowledge, rules
from .engine.ecfr import ECFRClient, parse_citation
from .models import Certificate, Company, EcfrCache, KnowledgeRule, Product
from .schemas import AnswerIn, PartyIn, ProductCreate, ReportedRuleIn


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="CPSC Compliance Consultant", version="0.1.0", lifespan=lifespan)

_STATIC = Path(__file__).resolve().parent / "static"

# Lazily-created shared eCFR client. Tests override this with a mock-transport client.
ecfr_client: ECFRClient | None = None


def get_ecfr() -> ECFRClient:
    global ecfr_client
    if ecfr_client is None:
        ecfr_client = ECFRClient()
    return ecfr_client


# ---------------------------------------------------------------------------
# Products & intake
# ---------------------------------------------------------------------------
@app.post("/api/products")
def create_product(payload: ProductCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
    company = None
    if payload.company_name:
        company = db.scalar(select(Company).where(Company.name == payload.company_name))
        if company is None:
            company = Company(name=payload.company_name)
            db.add(company)
            db.flush()

    attrs: dict[str, Any] = {}
    if payload.source_input:
        attrs = extract.extract_attributes(payload.source_input)

    product = Product(
        name=payload.name,
        company_id=company.id if company else None,
        source_input=payload.source_input,
        attrs=attrs,
        status="interview",
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return _product_dict(product)


@app.get("/api/products")
def list_products(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    active = _active_rules(db)
    products = db.scalars(select(Product).order_by(Product.created_at.desc()))
    return [_product_summary(p, active) for p in products]


@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Aggregate portfolio stats across all products for the dashboard header."""
    active = _active_rules(db)
    summaries = [_product_summary(p, active) for p in db.scalars(select(Product))]
    by_status: dict[str, int] = {}
    by_cert: dict[str, int] = {}
    for s in summaries:
        by_status[s["status"]] = by_status.get(s["status"], 0) + 1
        by_cert[s["certificate_type"]] = by_cert.get(s["certificate_type"], 0) + 1
    return {
        "total": len(summaries),
        "by_status": by_status,
        "by_certificate_type": by_cert,
        "needing_testing": sum(1 for s in summaries if s["testing_required"]),
        "interviews_incomplete": sum(1 for s in summaries if not s["interview_complete"]),
        "with_drafts": sum(1 for s in summaries if s["certificate_count"] > 0),
    }


@app.get("/api/products/{product_id}")
def get_product(product_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _product_dict(_get(db, product_id))


@app.delete("/api/products/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    product = _get(db, product_id)
    db.delete(product)
    db.commit()
    return {"deleted": product_id}


@app.get("/api/products/{product_id}/certificates")
def list_certificates(product_id: int, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    _get(db, product_id)  # 404 if missing
    certs = db.scalars(
        select(Certificate).where(Certificate.product_id == product_id).order_by(Certificate.created_at.desc())
    )
    return [
        {
            "id": c.id,
            "cert_type": c.cert_type,
            "draft": c.draft,
            "gap_analysis": c.gap_analysis,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "ready_to_issue": c.gap_analysis.get("ready_to_issue", False),
        }
        for c in certs
    ]


# ---------------------------------------------------------------------------
# Interview
# ---------------------------------------------------------------------------
@app.get("/api/products/{product_id}/next-question")
def next_question(product_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    product = _get(db, product_id)
    q = interview.next_question(dict(product.attrs))
    return {
        "question": q,
        "progress": interview.progress(dict(product.attrs)),
        "complete": q is None,
    }


@app.post("/api/products/{product_id}/answer")
def answer(product_id: int, payload: AnswerIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    product = _get(db, product_id)
    attrs = dict(product.attrs)
    try:
        interview.apply_answer(attrs, payload.key, payload.value)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    product.attrs = attrs
    nxt = interview.next_question(attrs)
    product.status = "assessed" if nxt is None else "interview"
    db.commit()
    return {
        "attrs": attrs,
        "next_question": nxt,
        "progress": interview.progress(attrs),
        "complete": nxt is None,
    }


# ---------------------------------------------------------------------------
# Assessment & drafting
# ---------------------------------------------------------------------------
@app.get("/api/products/{product_id}/assessment")
def assessment(product_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    product = _get(db, product_id)
    return rules.assess(dict(product.attrs), _active_rules(db))


@app.post("/api/products/{product_id}/draft")
def draft(product_id: int, party: PartyIn | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    product = _get(db, product_id)
    result = rules.assess(dict(product.attrs), _active_rules(db))
    out = drafter.draft_certificate(
        {"name": product.name},
        result,
        party.model_dump(exclude_none=True) if party else None,
    )
    cert = Certificate(
        product_id=product.id,
        cert_type=out["draft"]["certificate_type"],
        draft=out["draft"],
        gap_analysis=out["gap_analysis"],
    )
    db.add(cert)
    product.status = "drafted"
    db.commit()
    return out


# ---------------------------------------------------------------------------
# Knowledge base & learning loop
# ---------------------------------------------------------------------------
@app.get("/api/knowledge")
def list_knowledge(include_unverified: bool = False, db: Session = Depends(get_db)) -> dict[str, Any]:
    community = [
        {**kr.rule, "verification_tier": kr.verification_tier, "status": kr.status, "db_id": kr.id}
        for kr in db.scalars(select(KnowledgeRule).order_by(KnowledgeRule.created_at.desc()))
        if include_unverified or kr.verification_tier != "community_unverified"
    ]
    return {"official": knowledge.load_seed_rules(), "community": community}


@app.post("/api/knowledge/report")
def report_rule(payload: ReportedRuleIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    report = payload.model_dump(exclude_none=True)
    follow_ups = knowledge.missing_capture_questions(report)
    structured = knowledge.capture_reported_rule(report)
    kr = KnowledgeRule(
        rule=structured,
        verification_tier=structured["verification_tier"],
        status=structured["status"],
        reported_by=report.get("reported_by"),
    )
    db.add(kr)
    db.commit()
    db.refresh(kr)
    return {
        "captured": structured,
        "db_id": kr.id,
        "follow_up_questions": follow_ups,
        "note": "Filed in the review queue as community_unverified. It will not affect assessments until a reviewer verifies it.",
    }


# ---------------------------------------------------------------------------
# eCFR — live Code of Federal Regulations lookups
# ---------------------------------------------------------------------------
@app.get("/api/ecfr/currency")
def ecfr_currency(db: Session = Depends(get_db)) -> dict[str, Any]:
    """How current Title 16 (CPSC's title) is in eCFR."""
    return _cached(db, "currency:title-16", 24, lambda: get_ecfr().title_currency(16))


@app.get("/api/ecfr/section")
def ecfr_section(citation: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Fetch the live CFR text for a citation, e.g. ?citation=16 CFR 1303."""
    ref = parse_citation(citation)
    if ref is None:
        return {"ok": False, "error": "No CFR reference found in citation.", "citation": citation}
    return _cached(db, f"section:{ref.label}", 24, lambda: get_ecfr().section_text(ref))


@app.get("/api/ecfr/search")
def ecfr_search(q: str, per_page: int = 5, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Full-text search the CFR (scoped to Title 16 by default)."""
    return _cached(db, f"search:{per_page}:{q}", 6, lambda: get_ecfr().search(q, per_page=per_page))


@app.post("/api/knowledge/refresh")
def refresh_knowledge(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Refresh every seed rule against its live eCFR source (currency + text).

    This is the mechanism that keeps the knowledge base honest: it reports which
    citations still resolve and how current they are, so stale rules get flagged.
    """
    client = get_ecfr()
    statuses = []
    for rule in knowledge.load_seed_rules():
        status = _cached(
            db, f"refresh:{rule['id']}", 24, lambda r=rule: client.refresh_rule(r)
        )
        statuses.append(status)
    resolved = sum(1 for s in statuses if s.get("resolved"))
    return {
        "refreshed": len(statuses),
        "resolved": resolved,
        "unresolved": len(statuses) - resolved,
        "statuses": statuses,
    }


def _cached(db: Session, key: str, ttl_hours: int, producer: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Return a cached eCFR payload if fresh; otherwise call ``producer`` and cache it.

    Failed/unreachable results (``ok`` is False, or ``resolved`` is False) are NOT
    cached, so a transient network block doesn't get pinned for the whole TTL.
    """
    entry = db.scalar(select(EcfrCache).where(EcfrCache.cache_key == key))
    if entry is not None:
        age = datetime.now(timezone.utc) - entry.fetched_at.replace(tzinfo=timezone.utc)
        if age < timedelta(hours=ttl_hours):
            return {**entry.payload, "_cached": True}

    payload = producer()
    cacheable = payload.get("ok", True) and payload.get("resolved", True)
    if cacheable:
        if entry is None:
            db.add(EcfrCache(cache_key=key, payload=payload))
        else:
            entry.payload = payload
            entry.fetched_at = datetime.now(timezone.utc)
        db.commit()
    return payload


# ---------------------------------------------------------------------------
# Helpers + static UI
# ---------------------------------------------------------------------------
def _active_rules(db: Session) -> list[dict[str, Any]]:
    """Rules used for assessment: official seed rules + any community-*verified* rules."""
    active = list(knowledge.load_seed_rules())
    for kr in db.scalars(select(KnowledgeRule).where(KnowledgeRule.verification_tier == "community_verified")):
        active.append(kr.rule)
    return active


def _get(db: Session, product_id: int) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


def _product_dict(p: Product) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "company_id": p.company_id,
        "company_name": p.company.name if p.company else None,
        "attrs": p.attrs,
        "status": p.status,
        "source_input": p.source_input,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _product_summary(p: Product, active_rules: list[dict[str, Any]]) -> dict[str, Any]:
    """A dashboard row: identity + computed compliance state for one product.

    The assessment and interview progress are computed on the fly from the stored
    attributes (no network, no persistence needed), so the dashboard always reflects
    the current rule set — including any newly-verified community rules.
    """
    attrs = dict(p.attrs)
    result = rules.assess(attrs, active_rules)
    prog = interview.progress(attrs)
    complete = interview.next_question(attrs) is None
    return {
        "id": p.id,
        "name": p.name,
        "company_name": p.company.name if p.company else None,
        "status": p.status,
        "certificate_type": result["certificate_type"],
        "applicable_count": len(result["applicable_rules"]),
        "testing_required": result["third_party_testing_required"],
        "questions_answered": prog["answered"],
        "questions_relevant": prog["relevant"],
        "interview_complete": complete,
        "certificate_count": len(p.certificates),
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


app.mount("/static", StaticFiles(directory=_STATIC), name="static")
