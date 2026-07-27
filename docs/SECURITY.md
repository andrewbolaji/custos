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

## Where the model credential lives

If you deploy Custos in the standard configuration, the key that lets Custos talk to its AI model is stored encrypted, and only the one service that needs it can read it. The AWS customer deployment also supports `llm_provider = "bedrock"` (Amazon Bedrock as the model backend, see `deploy/PREREQUISITES.md`), where there is no key at all to store: the service authenticates to the model using temporary credentials that AWS itself issues to the running service and rotates automatically, and nothing sits in a secrets store waiting to be stolen. That credential-free property holds with `enable_egress = true`. **It does not currently extend to a fully air-gapped deployment** (`enable_egress = false`, no route to the public internet from any workload): the AWS module's ECS task also runs a Qdrant vector store sidecar pulled from Docker Hub, which air-gapped subnets cannot reach, so `enable_egress = false` is blocked at Terraform plan time for every `llm_provider`. Ask your deployment contact which configuration you are running, and whether air-gapped is a hard requirement -- if so, see `deploy/PREREQUISITES.md` for what closing that gap would take.

## What we do not claim

Scope of these guarantees:

- **Date of birth, salary, address, and personal names** are not automatically masked yet. Detectors precise enough to catch these categories also catch legitimate data of the same shape, such as product prices and office addresses, and a masker with that false-positive rate degrades retrieval more than it protects. Document permissions are the primary control here.
- **Identity** is supplied by the deployment, not by Custos. Access control is enforced at retrieval against whatever user context is passed in, so an SSO or JWT integration changes the identity source without touching the ACL path.
- We defend the application layer. Network security, infrastructure hardening, and physical security are handled by the hosting environment.

