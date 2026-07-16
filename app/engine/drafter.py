"""Certificate drafter.

Drafts a GCC (General Certificate of Conformity) or CPC (Children's Product
Certificate) from an assessment. Both certificate types share the same seven required
elements under 16 CFR 1110; a CPC additionally must identify the CPSC-accepted third
party lab(s). The drafter also produces a **gap analysis**: what is still missing before
the certificate would be valid (e.g. required lab tests not yet on file).
"""
from __future__ import annotations

from datetime import date
from typing import Any

# The seven required elements of every certificate under 16 CFR 1110.11.
REQUIRED_ELEMENTS = [
    "product_identification",
    "citations_to_regulations",
    "identification_of_certifier",       # importer (imports) or domestic manufacturer
    "contact_for_records",
    "date_and_place_of_manufacture",
    "date_and_place_of_testing",
    "third_party_lab_identification",    # CPC only; N/A for GCC
]


def draft_certificate(product: dict[str, Any], assessment: dict[str, Any], party: dict[str, Any] | None = None) -> dict[str, Any]:
    """Produce a certificate draft + gap analysis.

    ``party`` optionally supplies the responsible-party fields (importer/manufacturer
    name, address, records contact, manufacture and testing details). Anything missing
    is surfaced as a placeholder in the draft and flagged in the gap analysis.
    """
    party = party or {}
    cert_type = assessment.get("certificate_type", "undetermined")

    rules = assessment.get("applicable_rules", [])
    citations = [
        {"title": r["title"], "citation": r["citation"], "standard": r.get("standard")}
        for r in rules
    ]

    draft = {
        "certificate_type": cert_type,
        "product_identification": product.get("name") or "[PRODUCT NAME/DESCRIPTION REQUIRED]",
        "citations_to_regulations": citations or [{"note": "No mandatory standards identified; a GCC may still be advisable."}],
        "certifier": {
            "name": party.get("certifier_name") or "[IMPORTER OR U.S. MANUFACTURER NAME REQUIRED]",
            "address": party.get("certifier_address") or "[FULL ADDRESS REQUIRED]",
        },
        "records_contact": {
            "name": party.get("records_contact_name") or "[RECORDS CONTACT NAME REQUIRED]",
            "email": party.get("records_contact_email") or "[EMAIL REQUIRED]",
            "phone": party.get("records_contact_phone") or "[PHONE REQUIRED]",
        },
        "manufacture": {
            "date": party.get("manufacture_date") or "[MFG DATE (mm/yyyy) REQUIRED]",
            "place": party.get("manufacture_place") or "[CITY, STATE/PROVINCE, COUNTRY REQUIRED]",
        },
        "testing": {
            "date": party.get("testing_date") or "[TEST DATE REQUIRED]",
            "place": party.get("testing_place") or "[TEST LOCATION REQUIRED]",
        },
        "issued_on": date.today().isoformat(),
        "disclaimer": "DRAFT — not legal advice. Verify all fields and retain supporting test records.",
    }

    if cert_type == "CPC":
        draft["third_party_labs"] = party.get("labs") or ["[CPSC-ACCEPTED LAB NAME + CPSC LAB CODE REQUIRED]"]

    return {
        "draft": draft,
        "gap_analysis": _gap_analysis(cert_type, assessment, party),
    }


def _gap_analysis(cert_type: str, assessment: dict[str, Any], party: dict[str, Any]) -> dict[str, Any]:
    """Everything still needed before this certificate is valid & defensible."""
    gaps: list[str] = []

    if cert_type == "undetermined":
        gaps.append("Determine whether this is a children's product (finish the interview) before a certificate type can be assigned.")

    for r in assessment.get("testing_rules", []):
        gaps.append(f"Third-party lab testing required for: {r['title']} ({r['citation']}). Obtain a passing test report from a CPSC-accepted lab.")

    if cert_type == "CPC" and not party.get("labs"):
        gaps.append("Identify the CPSC-accepted third party laboratory (name + CPSC lab code) that performed the testing.")

    for field, label in [
        ("certifier_name", "certifier (importer/manufacturer) name"),
        ("certifier_address", "certifier address"),
        ("records_contact_email", "records contact"),
        ("manufacture_date", "date/place of manufacture"),
        ("testing_date", "date/place of testing"),
    ]:
        if not party.get(field):
            gaps.append(f"Provide the {label}.")

    return {
        "ready_to_issue": not gaps,
        "outstanding": gaps,
    }
