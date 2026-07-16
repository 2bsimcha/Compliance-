"""ORM models: companies, products (with their interview answers/attrs), certificates,
and the knowledge-base rule queue.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

# Native JSONB on Postgres (indexable, faster); plain JSON everywhere else (e.g. SQLite).
JSONType = JSON().with_variant(JSONB(), "postgresql")


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    products: Mapped[list["Product"]] = relationship(back_populates="company", cascade="all, delete-orphan")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(300))
    source_input: Mapped[str | None] = mapped_column(Text, nullable=True)  # pasted text / URL / report
    # The flat attribute dict built up by the interview + extraction. Consumed directly
    # by the rules engine.
    attrs: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="intake")  # intake|interview|assessed|drafted
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    company: Mapped[Company | None] = relationship(back_populates="products")
    certificates: Mapped[list["Certificate"]] = relationship(back_populates="product", cascade="all, delete-orphan")


class Certificate(Base):
    __tablename__ = "certificates"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    cert_type: Mapped[str] = mapped_column(String(20))  # GCC|CPC
    draft: Mapped[dict[str, Any]] = mapped_column(JSONType)
    gap_analysis: Mapped[dict[str, Any]] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    product: Mapped[Product] = relationship(back_populates="certificates")


class EcfrCache(Base):
    """Cache of eCFR responses, keyed by a canonical request key.

    Avoids re-fetching (and re-hammering) eCFR for the same citation/search. The
    endpoints treat entries older than a TTL as stale and refetch.
    """

    __tablename__ = "ecfr_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    cache_key: Mapped[str] = mapped_column(String(300), unique=True, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class KnowledgeRule(Base):
    """User-reported rules/exemptions captured by the learning loop.

    Seed (official) rules live in the JSON file; this table holds *community* rules and
    their review status so unverified input stays quarantined from assessments.
    """

    __tablename__ = "knowledge_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule: Mapped[dict[str, Any]] = mapped_column(JSONType)  # the structured rule object
    verification_tier: Mapped[str] = mapped_column(String(30), default="community_unverified")
    status: Mapped[str] = mapped_column(String(30), default="pending_review")
    reported_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
