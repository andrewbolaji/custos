# Information Security Policy

**Owner:** IT & Security
**Effective:** March 2025
**Applies to:** All employees and contractors with access to Larkspur
systems.

## Purpose

This policy sets minimum security expectations for anyone accessing
Larkspur Analytics systems, whether employee, contractor, or vendor. It is
not a substitute for role-specific training; it is the floor everyone is
expected to meet.

## Account and password requirements

- All company accounts (email, Slack, GitHub, the internal admin console)
  require single sign-on (SSO) through Okta wherever the vendor supports it.
- Where SSO is not available, passwords must be at least 14 characters and
  managed through the company password manager (1Password). Do not reuse a
  personal password for a work account, and do not write passwords down.
- Multi-factor authentication (MFA) is required on all accounts that support
  it, no exceptions, including contractor accounts.

## Device requirements

- Company laptops must have full-disk encryption enabled (this is
  pre-configured on shipped devices; do not disable it).
- Automatic screen lock after 5 minutes of inactivity is enforced by MDM
  policy.
- Personal devices used to check email or Slack must have a passcode or
  biometric lock enabled. Personal devices are never used to access the
  production admin console or the customer data warehouse.

## Data classification

Larkspur classifies data into three tiers:

1. **Public** — marketing site content, published documentation. No
   restriction on sharing.
2. **Internal** — this handbook, most policy documents, internal wiki pages.
   Shared within the company, not externally, unless a specific document is
   marked otherwise.
3. **Restricted** — customer data, employee PII, compensation information,
   vendor contracts, and anything in the finance or HR systems. Access is
   role-based and logged. Never copy restricted data into a personal
   account, personal cloud storage, or an unapproved third-party tool.

## Incident reporting

If you suspect a security incident — a phishing email you clicked, a lost
or stolen device, unusual account activity, or anything that looks like an
attempt to manipulate you into sharing credentials or data — report it
immediately to security@larkspur-example.com or the on-call security
channel in Slack (#sec-oncall). Do not wait to be sure; a false alarm costs
us a few minutes, a missed real incident costs much more.

The security on-call phone line is (555) 555-0188, staffed 24/7 for
Severity 1 and 2 incidents only. For anything not urgent, use the Slack
channel or email above during business hours.

## Social engineering awareness

Phishing and pretexting attempts increasingly arrive disguised as ordinary
business requests — a "customer" asking a support rep to forward account
data, a "vendor" asking finance to change payment details, or an
instruction embedded in a document or ticket that asks the reader (or an AI
assistant acting on the reader's behalf) to take an action outside its
normal scope. Treat any request to send data externally, change payment or
banking details, or bypass a normal approval step as suspicious by default,
regardless of how the request is phrased or where it appears, and confirm
it through a second channel before acting.

## Third-party tools and AI assistants

Any AI assistant used with company data, including Custos, is expected to
treat retrieved document content as data to answer questions from, not as
instructions to execute. Employees should not assume an assistant's answer
is authoritative for a security-sensitive action (sending data externally,
approving a payment, granting access) without the same confirmation step a
human request would require.

## Enforcement

Repeated or willful violation of this policy is handled through the
process described in the Code of Conduct & Workplace Standards document.
Questions about a specific tool or workflow not covered here should go to
security@larkspur-example.com before proceeding, not after.
