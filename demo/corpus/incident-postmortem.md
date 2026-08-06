# Incident Postmortem: 2026-05-14 Billing Sync Outage

**Severity:** SEV-2
**Duration:** 47 minutes (14:02–14:49 PT)
**Author:** Elena Vasquez, Head of Engineering
**Status:** Complete. Action items tracked below.

## Summary

Billing sync jobs failed for 47 minutes on 2026-05-14, causing new customer
subscription upgrades to not reflect on invoices generated during the
window. No customer was overcharged. 6 customers were undercharged for
prorated upgrade amounts, totaling approximately $340, corrected in the
next billing cycle.

## Timeline (Pacific time)

- **14:02** — Billing sync job begins failing silently after a scheduled
  database credential rotation. Alerts did not fire because the sync job's
  error handling logged failures at INFO level instead of ERROR.
- **14:11** — First customer-reported issue: a Customer Success rep
  (reported by Dana Osei) flags that a customer's plan upgrade isn't
  showing on their invoice.
- **14:20** — On-call engineer confirms the sync job is failing and begins
  investigating the credential rotation as the likely cause.
- **14:38** — Root cause confirmed: the sync job's database connection
  string was not updated as part of the automated rotation, because it read
  credentials from a separate config path than the other services rotated
  that day.
- **14:49** — Fix deployed, sync job resumes processing the backlog.
  Backlog fully cleared by 15:10.

## Root cause

The billing sync job read its database credentials from a legacy config
path that the credential-rotation automation did not know about. The
rotation script updated every service registered in the standard config
registry; the billing sync job predated that registry and was never
migrated into it.

## Impact

- 6 customer accounts had upgrade proration not reflected on their invoice
  for one billing cycle. All 6 were corrected in the next cycle with a
  clear line item explaining the correction.
- No data loss. No customer PII was exposed. No downstream system depended
  on the billing sync completing within a specific window, so the failure
  was contained to invoicing accuracy, not service availability.

## Why detection was slow

The 9-minute gap between the failure starting and a human noticing it was
caused by the sync job's own error handling: connection failures were
caught and logged at INFO level rather than re-raised or logged at ERROR,
so the on-call alerting rules (which page on ERROR-level logs from
billing-critical services) never fired. Detection came from a Customer
Success report, not from monitoring.

## Action items

| Item | Owner | Status |
|---|---|---|
| Migrate billing sync job's config into the standard credential registry | Platform team | Done (2026-05-16) |
| Change billing sync connection failures to ERROR-level logging with paging | Platform team | Done (2026-05-16) |
| Audit all other pre-registry services for the same credential-rotation gap | Platform team | Done (2026-05-22), 2 additional services found and migrated |
| Add a billing sync heartbeat check independent of the job's own logging | Platform team | In progress, target 2026-06-30 |

## Lessons

Silent failure modes are worse than loud ones. A service that fails loudly
and pages someone is a bounded incident; a service that fails quietly and
is caught by a customer-facing team nine minutes later is the same
technical failure with a worse outcome. The action items above target the
detection gap specifically, not just the credential path that caused this
particular incident.
