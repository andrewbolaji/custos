# How Custos Protects Your Data

Custos is an AI assistant that answers questions from your company's own documents. It is built to be trustworthy. This page explains how it protects your data in plain language.

## Your documents stay private

Custos only answers from documents you give it. It does not search the internet or make up answers. If your documents do not contain the answer, it says "I don't have information about that" instead of guessing.

Every answer includes source citations so you can verify where the information came from.

## People only see what they are allowed to see

Each document has permissions. An employee asking about the PTO policy sees the handbook. They do not see HR salary records or financial reports unless they have been granted access. This is enforced when the system searches for answers, not just in the display. A restricted document never reaches the AI model for an unauthorized user.

## Personal information is automatically masked

Social Security numbers, personal email addresses, and personal phone numbers are automatically replaced with placeholders like [SSN] or [EMAIL] in every answer. This happens regardless of who is asking, as an extra layer of protection on top of document permissions.

Your company's public contact information (the main phone line, the support email) is not masked, because masking "Call us at [PHONE]" would be unhelpful.

Personal information is also scrubbed from server logs, so it never appears in system records.

## The AI cannot take actions without your approval

Custos can draft emails and file tickets, but it never sends or submits anything without asking you first. A confirmation card appears with the full details. You approve or reject. Nothing happens until you decide.

This protection works even if someone tries to trick the AI through a hidden instruction in a document. In testing, a document containing a hidden command caused the AI to draft an unauthorized email. The system still did not send it. The confirmation gate blocked it, and the action required human approval before anything could happen.

## The AI resists manipulation

Documents in your system might contain tricky instructions (accidentally or deliberately) that try to change the AI's behavior. Custos treats all document content as data to answer from, never as commands to follow. This is built into the system's architecture, not just a suggestion to the AI.

## What we test

Every security protection has an automated test that proves it works:

- **55 security tests** across 5 test suites, all passing
- **Zero unauthorized actions** in adversarial testing
- **Zero PII leaks** on a labeled set of 16 sensitive values
- **Zero unauthorized document retrievals** when permissions are enforced
- **5 injection attack variants** structurally blocked

These tests run automatically and catch any regression before it reaches production.

## What we do not claim

We are honest about scope:

- **Date of birth, salary, address, and personal names** are not automatically masked yet. Masking them reliably requires more advanced AI techniques that would also mask legitimate data (like product prices or office addresses). Document permissions are the primary protection for these.
- **User login and authentication** is a demo simplification. Production deployment would use real identity verification (SSO, JWT tokens).
- We defend the application layer. Network security, infrastructure hardening, and physical security are handled by the hosting environment.

Honesty about limits is a feature, not a weakness. We would rather tell you what is proven than claim more than we can demonstrate.
