# Custos deployment prerequisites

For the IT lead at the customer receiving this deployment. Please read this in
full before the deployment date. Most items below are a short conversation or
a single decision, but each one blocks a specific step if it is missing, and
finding that out on deployment day costs everyone a delay.

Custos runs as a single containerized service in your own AWS account, on ECS
Fargate, behind a load balancer, reading its documents from a corpus you
provide and calling a hosted generation model over the internet (or not, see
"Network and egress" below). Nothing about it is shared infrastructure. It is
yours from the first resource created.

## AWS account and ownership

| Item | Why it is needed | What blocks if missing |
|---|---|---|
| Which AWS account this deploys into | Terraform is pointed at exactly one account by its 12 digit id, and refuses to run against any other. | Deployment cannot start. We need the account id before the first `terraform plan`. |
| Who owns that account | AWS billing, IAM root access, and support cases all resolve to this person. | If the account owner is unreachable, nobody can approve the IAM role below or resolve a billing question. |
| Who pays | Confirms whether this account bills to the customer directly or through a reseller or MSP relationship. | Ambiguity here surfaces as a disputed invoice weeks later, not as a blocker now, but it is worth settling up front. |

## Region and data residency

Pick one AWS region before deployment. Once resources exist, moving region
means rebuilding, not relocating. `us-east-1` is the default in this module
because it is usually the cheapest and has the fullest service availability.

Ask: does any law, contract, or internal policy require your document corpus
or its derived data (embeddings, logs) to stay within a specific country or
economic area, for example GDPR data residency inside the EU? If yes, name
the region now.

**Blocks if missing:** we deploy to the default region, and if that turns out
to be the wrong jurisdiction, every resource with data in it has to be torn
down and recreated in the correct region, not just reconfigured.

## The IAM role you create for us

You create an IAM role in your account that our deployment credentials assume.
We do not want, and this module does not need, your root credentials or a
permanent IAM user.

What it needs, at minimum: permission to create and manage VPCs, subnets,
security groups, ECS clusters and services, an Application Load Balancer, an
ECR repository, a Secrets Manager secret container, CloudWatch log groups, and
the two IAM roles the ECS task itself uses (see `ecs.tf` for exactly what
those two roles are allowed to do, they are least-privilege and documented
inline).

How you revoke it: delete the trust relationship on the role, or delete the
role outright, at any time. Nothing about our access depends on you telling us
first. We recommend also setting a role session duration limit and, if your
org supports it, a condition requiring MFA on the assuming principal.

**Blocks if missing:** nothing can be planned or applied. This is the first
concrete deliverable we need from you, before any Terraform command runs
against your account.

## Network and egress: a real choice, not a checkbox

The service needs to call a hosted large language model (currently Anthropic)
to generate answers. That call has to leave your network somehow, or not
leave it at all. This module builds either path, controlled by one variable,
`enable_egress`.

**Egress enabled** (`enable_egress = true`, the default): we create a NAT
gateway. The ECS tasks, in private subnets, can reach the public internet
through it. Simple, and the standard path for any deployment that intends to
call a hosted model. Costs about $0.045/hour for the NAT gateway itself, plus
data processing.

**Air-gapped** (`enable_egress = false`): no NAT gateway, no default route out
of the private subnets, at all. Instead we create VPC endpoints so the service
can still pull its own container image, write logs, and read its secret,
without ever reaching the public internet. This is the choice if your policy
requires no direct internet path from any workload, full stop. Costs about
the same, or slightly less, than the NAT path, priced per interface endpoint.

The real consequence: with egress disabled, the service cannot call an
externally hosted generation model. If you choose air-gapped, that changes
what Custos can do, not just how it is deployed, and that architectural
conversation needs to happen before deployment, not after.

**Blocks if missing:** we default to egress enabled. If your policy actually
requires air-gapped and nobody said so, we build the wrong network topology
and have to rebuild it.

## Generation model API key

Custos calls Anthropic's API to generate answers. Someone in your
organization, or in ours depending on the commercial arrangement, holds an
Anthropic API key.

Decide now: whose account is the key issued under, who is the named holder of
record, and who is responsible for rotating it if it is ever exposed. The key
itself is never put into Terraform or committed anywhere. It is placed
directly into the AWS Secrets Manager container we create, using a single AWS
CLI command run out of band (see `deploy/terraform/secrets.tf`), by whoever
holds it.

**Blocks if missing:** the ECS service will start, pass its health check, and
then fail every actual query with an authentication error the moment someone
tries to use it. This is the classic "it's up but it doesn't work" failure
mode, so have the key ready before go-live, not during.

## Custom domain and TLS

If you want Custos reachable at a domain you own, rather than the load
balancer's raw AWS DNS name, you need:

- Control of the DNS zone for that domain, or someone on your side who can add
  a CNAME record on request.
- An ACM certificate issued for that domain, in the same region as the
  deployment. The HTTPS listener is written and ready in `alb.tf` but left
  commented out until this certificate ARN exists.

**Blocks if missing:** the deployment works over plain HTTP on the ALB's AWS
DNS name. That is fine for a demo, not acceptable for anything handling real
traffic, so treat the certificate as a prerequisite for go-live, not a
nice-to-have added later.

## Your document corpus

Tell us, roughly:

- What formats the documents are in (PDF, Word, Markdown, HTML, something
  else).
- Roughly how many documents, and total size.
- Where they live today (a file share, SharePoint, Google Drive, a wiki, an
  existing document management system).
- Who inside your organization is allowed to see each category of document.
  This maps directly to the access control rules enforced in the retriever, so
  we need your actual permission boundaries, not a simplified version of them.

**Blocks if missing:** we cannot build the ingestion step or configure access
control without knowing the shape and sensitivity of what is being ingested.
A generic demo corpus is not a substitute for this conversation.

## Roles and permissions

How does your organization decide who can ask Custos which questions, and
does that mapping already exist in an identity provider (Okta, Azure AD,
Google Workspace, something else) that we should integrate with, or is it a
new access model built for this deployment?

**Blocks if missing:** we deploy with the simplest access model available
(single shared credential or a flat role list) and it has to be reworked once
your actual identity provider and role structure are known. That rework
touches the access control layer, which is one of the two or three places in
this system where correctness actually matters.

## Network: new or existing VPC

This module creates a new VPC by default, with a `10.40.0.0/16` CIDR range.
Two things to confirm:

- Do you want Custos in its own new VPC (the default, simplest, most isolated
  option), or peered into or placed inside an existing VPC you already run?
- If a new VPC, does `10.40.0.0/16` collide with any range you already use or
  connect to over VPN, Transit Gateway, or peering? If so, tell us the range
  to use instead.

**Blocks if missing:** a CIDR collision does not fail cleanly. It either fails
the plan with a routing conflict, or worse, succeeds and creates ambiguous
routing that is hard to diagnose later. Confirm the range before the first
apply, not after.

## Log retention and data handling

Application logs are kept in CloudWatch for `log_retention_days`, 7 days by
default. Tell us if your data handling policy requires a longer retention
window for audit purposes, or a shorter one for data minimization. This is one
Terraform variable to change, but we need the number from you, not a guess.

**Blocks if missing:** we ship the 7 day default, which either fails a
compliance audit that expected longer retention, or over-retains relative to
a policy that expected shorter.

## Sign-off and point of contact

Two names, please:

- Who signs off on the security review before go-live. This is usually
  someone who has read `THREAT_MODEL.md` and is satisfied with the controls
  described there, not necessarily the same person as the account owner
  above.
- A named technical contact on your side, with actual availability during the
  deployment window, who can grant IAM access, confirm DNS changes, and answer
  questions about the corpus in real time.

**Blocks if missing:** deployment day stalls waiting for someone to answer a
question or approve an action, and there is no way to know who that person is
supposed to be.
