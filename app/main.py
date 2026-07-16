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

from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db, init_db
from .engine import drafter, extract, interview, knowledge, rules
from .models import Certificate, Company, KnowledgeRule, Product
from .schemas import AnswerIn, PartyIn, ProductCreate, ReportedRuleIn

app = FastAPI(title="CPSC Compliance Consultant", version="0.1.0")

_STATIC = Path(__file__).resolve().parent / "static"


@app.on_event("startup")
def _startup() -> None:
    init_db()


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
    return [_product_dict(p) for p in db.scalars(select(Product).order_by(Product.created_at.desc()))]


@app.get("/api/products/{product_id}")
def get_product(product_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _product_dict(_get(db, product_id))


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
        "attrs": p.attrs,
        "status": p.status,
        "source_input": p.source_input,
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


app.mount("/static", StaticFiles(directory=_STATIC), name="static")
