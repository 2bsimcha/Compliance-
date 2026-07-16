"""Tests for cross-database support (SQLite default, Postgres via DATABASE_URL).

These run offline — no Postgres server needed. They verify URL normalization and that
the JSON columns compile to native JSONB on the Postgres dialect. A live Postgres
round-trip is exercised separately during development.
"""
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.database import normalize_database_url
from app.models import Certificate, EcfrCache, KnowledgeRule, Product


def test_normalize_rewrites_managed_host_schemes():
    # Managed hosts hand out driver-less schemes; SQLAlchemy needs an explicit driver.
    assert normalize_database_url("postgres://u:p@h:5432/db") == "postgresql+psycopg://u:p@h:5432/db"
    assert normalize_database_url("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"


def test_normalize_leaves_qualified_and_sqlite_untouched():
    assert normalize_database_url("postgresql+psycopg://u@h/db") == "postgresql+psycopg://u@h/db"
    assert normalize_database_url("sqlite:///./compliance.db") == "sqlite:///./compliance.db"


def test_json_columns_are_jsonb_on_postgres():
    pg = postgresql.dialect()
    for model in (Product, Certificate, EcfrCache, KnowledgeRule):
        ddl = str(CreateTable(model.__table__).compile(dialect=pg))
        assert "JSONB" in ddl, f"{model.__tablename__} should use JSONB on Postgres:\n{ddl}"
