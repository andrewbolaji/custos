"""PII detection and redaction (threat T4, ADR-005).

Tier 1 (Phase 3): structurally unambiguous PII that does not collide
with operational data. SSN, personal email, personal phone.

Tier 2 (ROADMAP): context-dependent PII requiring NER/disambiguation:
DOB, salary, address, personal names. Not shipped in Phase 3 because
naive regex would miss cases or corrupt operational answers.

The redactor runs inside resolve_response() on the COMPLETE answer
text (single source of truth for all output cleaning) and in the
server log filter. Unconditional: masks regardless of user tier.
"""

from __future__ import annotations

import re

from custos.interfaces import Redactor

# ---------------------------------------------------------------------------
# Company-public contact allowlist (ADR-005)
#
# These values survive redaction. They are work/directory contacts,
# not personal PII. Scoped to the demo corpus; production would
# populate from company config.
# ---------------------------------------------------------------------------

ALLOWED_PHONES: set[str] = {
    "(555) 555-0100",  # Scheduling line (faq-001.md)
    "(555) 555-0101",  # After-hours line (faq-001.md)
}

# Emails at the company domain are work/directory contacts by intent.
# Personal employee emails in the corpus use example.org / example.com
# (RFC 2606 reserved), which are NOT allowlisted.
ALLOWED_EMAIL_DOMAINS: set[str] = {
    "meridian-example.com",
}

# ---------------------------------------------------------------------------
# Patterns (Tier 1 only)
# ---------------------------------------------------------------------------

# SSN: 3-2-4 digits separated by hyphens
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

# Email: standard pattern
_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)

# Phone: (XXX) XXX-XXXX or XXX-XXX-XXXX
_PHONE_RE = re.compile(
    r"\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b"
)


class PIIRedactor(Redactor):
    """Regex-based PII redactor for Tier 1 (SSN, email, phone).

    Unconditional masking with company-public contact allowlist.
    """

    def __init__(
        self,
        *,
        allowed_phones: set[str] | None = None,
        allowed_email_domains: set[str] | None = None,
    ) -> None:
        self._allowed_phones = allowed_phones if allowed_phones is not None else ALLOWED_PHONES
        self._allowed_domains = (
            allowed_email_domains
            if allowed_email_domains is not None
            else ALLOWED_EMAIL_DOMAINS
        )

    def redact(self, text: str) -> str:
        """Replace Tier 1 PII with typed placeholders."""
        # Order matters: SSN first (most specific), then email, then phone
        text = _SSN_RE.sub("[SSN]", text)
        text = self._redact_emails(text)
        text = self._redact_phones(text)
        return text

    def _redact_emails(self, text: str) -> str:
        """Mask emails unless the domain is allowlisted."""
        def _replace(match: re.Match[str]) -> str:
            email = match.group(0)
            domain = email.split("@", 1)[1].lower()
            if domain in self._allowed_domains:
                return email
            return "[EMAIL]"
        return _EMAIL_RE.sub(_replace, text)

    def _redact_phones(self, text: str) -> str:
        """Mask phones unless the exact value is allowlisted."""
        def _replace(match: re.Match[str]) -> str:
            phone = match.group(0)
            if phone in self._allowed_phones:
                return phone
            return "[PHONE]"
        return _PHONE_RE.sub(_replace, text)
