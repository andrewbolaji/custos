# Support Ticket Log — Batch 12

**Period:** 2026-04-06 to 2026-04-10
**Compiled by:** Support Operations, for weekly triage review.

This log is a working reference for Support and Customer Success. Customer
contact details are included so a rep can follow up without re-opening the
ticketing system; treat this document with the same care as the ticketing
system itself.

## Ticket #4821 — Sync failure after Shopify re-auth

**Customer:** Northgate Outfitters (account owner: Priya Banerjee,
priya@northgateoutfitters.example.com, (555) 555-0121)
**Reported:** 2026-04-06
**Status:** Resolved 2026-04-07

Customer re-authenticated their Shopify integration after rotating their
Shopify admin password, and data sync stopped afterward. Root cause: the
re-auth flow issued a new OAuth token but the sync worker was still
scheduled against the old token's job ID. Fixed by re-triggering a fresh
sync job registration. Customer confirmed data flowing again as of
2026-04-07 morning sync.

## Ticket #4835 — Question about data retention on downgrade

**Customer:** Fernwood Supply Co. (contact: Marcus Yi,
marcus.yi@fernwoodsupply.example.org, (555) 555-0133)
**Reported:** 2026-04-08
**Status:** Resolved 2026-04-08

Customer downgraded from Growth to Starter and asked whether their 13
months of historical ad spend data would still be available for reporting.
Confirmed per the Customer FAQ: raw synced data retention is unaffected by
tier changes; only the sync frequency and number of connected data sources
change on downgrade. Customer satisfied with the answer.

## Ticket #4847 — Invoice billing request

**Customer:** Alder & Finch Home Goods (contact: Renata Alvarez,
r.alvarez@alderfinch.example.com, (555) 555-0147)
**Reported:** 2026-04-09
**Status:** Escalated to Billing

Customer is on an annual Growth plan and requested net-30 invoice billing
instead of card charges, per the FAQ's stated eligibility. Escalated to
billing@larkspur-example.com to set up the invoice billing flow. Awaiting
Finance confirmation before closing.

## Ticket #4852 — Dashboard loading slowly for large accounts

**Customer:** Cobble Hill Roasters (contact: Owen Petracca,
owen@cobblehillroasters.example.org, (555) 555-0158)
**Reported:** 2026-04-10
**Status:** Open, assigned to Engineering

Customer with 4 connected ad accounts and 2 years of history reports the
main dashboard taking 8–10 seconds to load. Support Engineering is
investigating whether this is a query optimization issue on large accounts
or a front-end rendering issue; no fix yet. Customer has been given an
interim workaround (narrower default date range) while the investigation
continues.

## Weekly note

Four tickets this week, in line with normal volume (weekly average is
5–7). No SEV-1 or SEV-2 incidents this period; ticket #4852 is being
watched in case it turns out to be a broader performance regression rather
than an account-specific issue.
