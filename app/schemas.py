"""Pydantic request/response schemas for the API."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ProductCreate(BaseModel):
    name: str
    company_name: str | None = None
    source_input: str | None = None  # pasted description / URL / test report to pre-fill attrs


class AnswerIn(BaseModel):
    key: str
    value: Any


class PartyIn(BaseModel):
    certifier_name: str | None = None
    certifier_address: str | None = None
    records_contact_name: str | None = None
    records_contact_email: str | None = None
    records_contact_phone: str | None = None
    manufacture_date: str | None = None
    manufacture_place: str | None = None
    testing_date: str | None = None
    testing_place: str | None = None
    labs: list[str] | None = None


class ReportedRuleIn(BaseModel):
    title: str
    citation: str | None = None
    summary: str | None = None
    category: str | None = None
    standard: str | None = None
    cert_required: str | None = None
    third_party_testing: bool | None = None
    applies_when: dict[str, Any] | bool | None = None
    source_url: str | None = None
    reported_by: str | None = None
