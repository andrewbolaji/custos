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
    """Test PII scrubbing through the REAL logging path.

    Uses a child logger (like custos.api uses logging.getLogger(__name__)),
    captures handler output, and verifies PII is redacted in the final
    formatted string. Tests f-string, %s args, and exception tracebacks.
    """

    def _capture_log_output(self, logger_name: str, log_fn) -> str:  # type: ignore[no-untyped-def]
        """Run log_fn(logger), capture and return the handler output."""
        from custos.api import PIIFormatter

        child = logging.getLogger(logger_name)
        child.setLevel(logging.DEBUG)

        handler = logging.StreamHandler(stream=__import__("io").StringIO())
        handler.setFormatter(PIIFormatter())
        child.addHandler(handler)
        try:
            log_fn(child)
            handler.flush()
            return handler.stream.getvalue()
        finally:
            child.removeHandler(handler)

    def test_fstring_pii_redacted_via_child_logger(self) -> None:
        """PII in an f-string message through a child logger is redacted."""
        ssn = "900-55-0000"
        email = "james@example.org"
        output = self._capture_log_output(
            "custos.test.fstring",
            lambda log: log.info(f"SSN is {ssn} email {email}"),
        )
        assert "900-55-0000" not in output, f"SSN leaked in log: {output!r}"
        assert "james@example.org" not in output, f"Email leaked in log: {output!r}"
        assert "[SSN]" in output
        assert "[EMAIL]" in output

    def test_percent_args_pii_redacted_via_child_logger(self) -> None:
        """PII passed as %s args through a child logger is redacted."""
        output = self._capture_log_output(
            "custos.test.args",
            lambda log: log.info("SSN %s email %s", "900-55-0000", "james@example.org"),
        )
        assert "900-55-0000" not in output, f"SSN leaked in log: {output!r}"
        assert "james@example.org" not in output, f"Email leaked in log: {output!r}"

    def test_exception_traceback_pii_redacted(self) -> None:
        """PII inside an exception message in a traceback is redacted."""
        def _log_with_exception(log: logging.Logger) -> None:
            try:
                raise ValueError("User SSN is 900-55-0000")
            except ValueError:
                log.exception("Failed for james@example.org")

        output = self._capture_log_output("custos.test.exc", _log_with_exception)
        assert "900-55-0000" not in output, f"SSN leaked in traceback: {output!r}"
        assert "james@example.org" not in output, f"Email leaked in traceback: {output!r}"
