"""Tests for PIIRedactor (threat T4, ADR-005).

Covers Tier 1 PII: SSN, email, phone. Verifies allowlist behavior
for company-public contacts and unconditional masking for personal PII.
"""

from __future__ import annotations

import logging

from custos.pii import PIIRedactor


class TestSSNRedaction:
    def test_masks_standard_ssn(self) -> None:
        r = PIIRedactor()
        assert r.redact("SSN: 900-55-0000") == "SSN: [SSN]"

    def test_masks_multiple_ssns(self) -> None:
        r = PIIRedactor()
        text = "SSNs: 900-55-0000 and 900-56-0001"
        result = r.redact(text)
        assert "900-55-0000" not in result
        assert "900-56-0001" not in result
        assert result.count("[SSN]") == 2

    def test_does_not_mask_non_ssn_numbers(self) -> None:
        r = PIIRedactor()
        assert r.redact("Order 12345") == "Order 12345"
        assert r.redact("Price: $1,200") == "Price: $1,200"


class TestEmailRedaction:
    def test_masks_personal_email(self) -> None:
        r = PIIRedactor()
        assert r.redact("email: james.santos@example.org") == "email: [EMAIL]"

    def test_masks_example_com_email(self) -> None:
        r = PIIRedactor()
        assert r.redact("chen.nakamura@example.com") == "[EMAIL]"

    def test_preserves_company_domain_email(self) -> None:
        r = PIIRedactor()
        text = "Contact support@meridian-example.com"
        assert "support@meridian-example.com" in r.redact(text)

    def test_preserves_company_domain_any_user(self) -> None:
        r = PIIRedactor()
        text = "dispatch@meridian-example.com"
        assert "dispatch@meridian-example.com" in r.redact(text)

    def test_masks_non_company_domain(self) -> None:
        r = PIIRedactor()
        assert r.redact("attacker@evil.com") == "[EMAIL]"


class TestPhoneRedaction:
    def test_masks_personal_phone(self) -> None:
        r = PIIRedactor()
        assert r.redact("Phone: (555) 555-0102") == "Phone: [PHONE]"

    def test_preserves_company_scheduling_line(self) -> None:
        r = PIIRedactor()
        text = "Call us at (555) 555-0100"
        assert "(555) 555-0100" in r.redact(text)

    def test_preserves_company_after_hours_line(self) -> None:
        r = PIIRedactor()
        text = "After-hours: (555) 555-0101"
        assert "(555) 555-0101" in r.redact(text)

    def test_masks_other_555_numbers(self) -> None:
        r = PIIRedactor()
        assert r.redact("(555) 555-0103") == "[PHONE]"

    def test_masks_hyphen_format(self) -> None:
        r = PIIRedactor()
        assert r.redact("555-555-0104") == "[PHONE]"


class TestCompositeRedaction:
    def test_full_hr_record(self) -> None:
        """An HR record with all Tier 1 PII types gets fully masked."""
        r = PIIRedactor()
        record = (
            "Employee: James Santos\n"
            "Email: james.santos@example.org\n"
            "Phone: (555) 555-0100\n"  # This IS the company line
            "SSN: 900-55-0000\n"
            "Personal Phone: (555) 555-0102\n"
        )
        result = r.redact(record)
        assert "900-55-0000" not in result
        assert "[SSN]" in result
        assert "james.santos@example.org" not in result
        assert "[EMAIL]" in result
        # Company line preserved, personal phone masked
        assert "(555) 555-0100" in result
        assert "(555) 555-0102" not in result
        assert "[PHONE]" in result

    def test_mixed_operational_and_pii(self) -> None:
        """Operational data (prices, company contacts) survives alongside PII masking."""
        r = PIIRedactor()
        text = (
            "Water heater replacement costs $1,200. "
            "Call (555) 555-0100 to schedule. "
            "Employee SSN is 900-55-0000."
        )
        result = r.redact(text)
        assert "$1,200" in result
        assert "(555) 555-0100" in result
        assert "900-55-0000" not in result


class TestCustomAllowlist:
    def test_custom_allowed_phones(self) -> None:
        r = PIIRedactor(allowed_phones={"(555) 555-0199"})
        assert r.redact("(555) 555-0199") == "(555) 555-0199"
        assert r.redact("(555) 555-0100") == "[PHONE]"  # No longer allowed

    def test_custom_allowed_domains(self) -> None:
        r = PIIRedactor(allowed_email_domains={"custom.example.com"})
        assert "user@custom.example.com" in r.redact("user@custom.example.com")
        assert r.redact("user@meridian-example.com") == "[EMAIL]"  # No longer allowed

    def test_empty_allowlists(self) -> None:
        r = PIIRedactor(allowed_phones=set(), allowed_email_domains=set())
        assert r.redact("(555) 555-0100") == "[PHONE]"
        assert r.redact("x@meridian-example.com") == "[EMAIL]"


class TestLogFilter:
    def test_pii_scrubbed_from_log_records(self) -> None:
        """The log filter must mask PII in log messages."""
        from custos.api import _PIILogFilter

        f = _PIILogFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="User SSN is 900-55-0000 and email is james@example.org",
            args=None,
            exc_info=None,
        )
        f.filter(record)
        assert "900-55-0000" not in record.msg
        assert "james@example.org" not in record.msg
        assert "[SSN]" in record.msg
        assert "[EMAIL]" in record.msg
