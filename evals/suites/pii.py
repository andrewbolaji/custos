"""PII detection and redaction evals (EVALS.md section 4, threat T4).

Measures per-type precision and recall on the corpus's labeled synthetic
PII (reserved-range SSNs, RFC 2606 emails, ITU-T 555 phones). Proves
redaction masks in answers AND that company-public contacts survive.

Tier 1 only (Phase 3): SSN, email, phone.
"""

from __future__ import annotations

from custos.pii import PIIRedactor
from evals.harness import EvalResult

# Labeled PII from corpus/output/hr-001.md (reserved-range synthetic data)
_LABELED_SSNS = [
    "900-55-0000", "900-56-0001", "900-57-0002",
    "900-58-0003", "900-59-0004", "900-60-0005",
]

_LABELED_PERSONAL_EMAILS = [
    "james.santos@example.org",
    "robert.obrien@example.org",
    "robert.reeves@example.com",
    "david.johansson@example.org",
    "chen.nakamura@example.com",
    "james.garcia@example.org",
]

_LABELED_PERSONAL_PHONES = [
    "(555) 555-0102", "(555) 555-0103",
    "(555) 555-0104", "(555) 555-0105",
]

# Company-public contacts that must NOT be masked
_COMPANY_PHONES = ["(555) 555-0100", "(555) 555-0101"]
_COMPANY_EMAILS = ["support@meridian-example.com", "dispatch@meridian-example.com"]


def _eval_ssn_redaction() -> list[EvalResult]:
    """Every labeled SSN must be masked."""
    r = PIIRedactor()
    results = []
    for ssn in _LABELED_SSNS:
        text = f"Employee SSN: {ssn}"
        redacted = r.redact(text)
        masked = ssn not in redacted and "[SSN]" in redacted
        results.append(EvalResult(
            suite="pii",
            case_name=f"ssn_masked: {ssn}",
            passed=masked,
            metric="ssn_recall",
            score=1.0 if masked else 0.0,
            detail="" if masked else f"SSN leaked: {redacted}",
        ))
    return results


def _eval_email_redaction() -> list[EvalResult]:
    """Personal emails masked, company emails preserved."""
    r = PIIRedactor()
    results = []

    for email in _LABELED_PERSONAL_EMAILS:
        text = f"Contact: {email}"
        redacted = r.redact(text)
        masked = email not in redacted and "[EMAIL]" in redacted
        results.append(EvalResult(
            suite="pii",
            case_name=f"personal_email_masked: {email}",
            passed=masked,
            metric="email_recall",
            score=1.0 if masked else 0.0,
            detail="" if masked else f"Email leaked: {redacted}",
        ))

    for email in _COMPANY_EMAILS:
        text = f"Contact: {email}"
        redacted = r.redact(text)
        preserved = email in redacted
        results.append(EvalResult(
            suite="pii",
            case_name=f"company_email_preserved: {email}",
            passed=preserved,
            metric="allowlist_precision",
            score=1.0 if preserved else 0.0,
            detail="" if preserved else f"Company email was masked: {redacted}",
        ))

    return results


def _eval_phone_redaction() -> list[EvalResult]:
    """Personal phones masked, company lines preserved."""
    r = PIIRedactor()
    results = []

    for phone in _LABELED_PERSONAL_PHONES:
        text = f"Phone: {phone}"
        redacted = r.redact(text)
        masked = phone not in redacted and "[PHONE]" in redacted
        results.append(EvalResult(
            suite="pii",
            case_name=f"personal_phone_masked: {phone}",
            passed=masked,
            metric="phone_recall",
            score=1.0 if masked else 0.0,
            detail="" if masked else f"Phone leaked: {redacted}",
        ))

    for phone in _COMPANY_PHONES:
        text = f"Call {phone} to schedule."
        redacted = r.redact(text)
        preserved = phone in redacted
        results.append(EvalResult(
            suite="pii",
            case_name=f"company_phone_preserved: {phone}",
            passed=preserved,
            metric="allowlist_precision",
            score=1.0 if preserved else 0.0,
            detail="" if preserved else f"Company phone was masked: {redacted}",
        ))

    return results


def _eval_composite_hr_record() -> EvalResult:
    """A full HR record with all Tier 1 PII types must be fully masked."""
    r = PIIRedactor()
    record = (
        "Employee 1: James Santos\n"
        "Email: james.santos@example.org\n"
        "Phone: (555) 555-0102\n"
        "SSN: 900-55-0000\n"
        "Date of Birth: 1990-07-29\n"
        "Address: 200 Testdata Ave, Houston, TX 77001\n"
        "Salary: $53,000/year\n"
    )
    redacted = r.redact(record)

    leaks = []
    if "900-55-0000" in redacted:
        leaks.append("SSN")
    if "james.santos@example.org" in redacted:
        leaks.append("email")
    if "(555) 555-0102" in redacted:
        leaks.append("phone")

    passed = len(leaks) == 0
    return EvalResult(
        suite="pii",
        case_name="composite_hr_record",
        passed=passed,
        metric="pii_leak_rate",
        score=0.0 if passed else float(len(leaks)),
        detail="" if passed else f"Leaked: {', '.join(leaks)}",
    )


def _eval_aggregate_leak_rate() -> EvalResult:
    """Aggregate: zero Tier 1 PII must leak across all labeled values."""
    r = PIIRedactor()
    all_pii = _LABELED_SSNS + _LABELED_PERSONAL_EMAILS + _LABELED_PERSONAL_PHONES

    leaks = []
    for val in all_pii:
        if val in r.redact(f"Data: {val}"):
            leaks.append(val)

    passed = len(leaks) == 0
    return EvalResult(
        suite="pii",
        case_name="aggregate_pii_leak_rate",
        passed=passed,
        metric="pii_leak_rate",
        score=0.0 if passed else len(leaks) / len(all_pii),
        detail=(
            f"0/{len(all_pii)} leaked" if passed
            else f"{len(leaks)}/{len(all_pii)} leaked: {leaks}"
        ),
    )


def run() -> list[EvalResult]:
    """Run all PII eval cases."""
    results: list[EvalResult] = []
    results.extend(_eval_ssn_redaction())
    results.extend(_eval_email_redaction())
    results.extend(_eval_phone_redaction())
    results.append(_eval_composite_hr_record())
    results.append(_eval_aggregate_leak_rate())
    return results
