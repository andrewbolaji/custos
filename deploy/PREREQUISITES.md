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

The service needs to call a hosted large language model to generate answers.
Which model it calls, and whether that call leaves your network at all, is
now a decision made by two independent Terraform variables together, not one
checkbox: `enable_egress` and `llm_provider`. They combine into four possible
deployments, three of which work and one of which does not.

`enable_egress = true`, `llm_provider = "anthropic"` (the default): we create
a NAT gateway. The ECS tasks, in private subnets, can reach the public
internet through it, and the service calls `api.anthropic.com` directly.
Simple, and the standard path for a deployment with no air-gap requirement.
Costs about $0.045/hour for the NAT gateway itself, plus data processing.

`enable_egress = true`, `llm_provider = "bedrock"`: also works. There is
still a NAT gateway, but the model call goes to Amazon Bedrock over AWS's own
network rather than to a third party endpoint. Worth choosing over the
default if you want Bedrock for billing or procurement reasons even though
you have no air-gap requirement.

`enable_egress = false`, `llm_provider = "bedrock"`: **air-gapped and fully
functional.** No NAT gateway, no route to the public internet from any
workload, and the model call reaches Bedrock over a private
`bedrock-runtime` VPC interface endpoint that never leaves AWS's network.
This is the combination to choose if your policy requires no direct internet
path from any workload, full stop. Costs about the same, or slightly less,
than the NAT path, priced per interface endpoint: four interface endpoints
(`ecr.api`, `ecr.dkr`, `logs`, `bedrock-runtime`) at roughly $0.01/hour each,
plus one S3 gateway endpoint at no hourly charge.

`enable_egress = false`, `llm_provider = "anthropic"`: **does not work.** The
private subnets have no route out, there is no VPC endpoint for
`api.anthropic.com`, and one cannot be created, because AWS PrivateLink
reaches AWS services and AWS Marketplace partner services, not arbitrary
third party SaaS. The failure mode here is the nasty kind: the apply
succeeds, the container starts, the ALB health check passes, and only then
does every real query fail on a connection timeout, discovered in production
rather than at plan time. A plan-time guard in the Terraform module now
refuses to build this combination at all (see the `egress_provider_guard`
precondition in `guard.tf`), so this failure mode is caught before an apply
ever runs, not after.

If air-gapped is your requirement, the combination to ask for is
`enable_egress = false` with `llm_provider = "bedrock"`, and that
architectural conversation, which model backend you are actually going to
run on, needs to happen before deployment, not after.

**Blocks if missing:** we default to egress enabled with the Anthropic
provider. If your policy actually requires air-gapped and nobody said so, we
build the wrong network topology and the wrong model provider, and have to
rebuild both.

## Generation model credentials

What this section asks of you depends on which `llm_provider` you chose
above.

**Anthropic path** (`llm_provider = "anthropic"`). Custos calls Anthropic's
API to generate answers. Someone in your organization, or in ours depending
on the commercial arrangement, holds an Anthropic API key.

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

**Bedrock path** (`llm_provider = "bedrock"`). There is no key. The running
ECS task authenticates to Amazon Bedrock as its own task role, using SigV4,
and the credentials for that role are delivered to the container by the ECS
agent and rotate automatically. Consequently, in this mode, no long-lived
model credential exists anywhere in the deployment: not in Secrets Manager,
because no such secret is created, not in the task definition, and not in an
environment variable or on disk. Nothing to issue, nothing to hand off,
nothing to rotate.

This statement is scoped narrowly to model access credentials. It says
nothing about credentials used for anything other than calling the model, and
nothing about the deployment credentials used to run Terraform itself, which
are a separate concern covered in "The IAM role you create for us" above.

**Blocks if missing:** two Bedrock-specific prerequisites still have to be in
place before go-live even though there is no key to hand over. See "Bedrock
account prerequisites" below.

## Bedrock account prerequisites (only if `llm_provider = "bedrock"`)

These two prerequisites live in AWS account state, not in Terraform code,
which means `terraform plan` and `terraform apply` both succeed whether or
not either one is actually satisfied. Both block go-live, and both have lead
time, so read this section even though nothing here shows up as a plan-time
error.

Model access. Anthropic's models must be enabled in the target account
before any invocation succeeds. If this is the first time anyone has used
Anthropic models on Bedrock in this account, someone submits a use case
details form, once per account, or once at the organization's management
account to cover every member account under it. **Blocks if missing:** the
apply succeeds, the container starts, the health check passes, and the first
real query returns an access denied error. The same "it's up but it doesn't
work" shape as a missing API key, just moved from the Anthropic path to the
Bedrock path.

Daily token quota. Bedrock's default per-model quotas vary by account, and
AWS documents that the defaults assigned to an account may depend on factors
including payment history. A newly created account, including one created
through AWS Organizations for this deployment, can land with a daily token
quota of zero for the model you intend to use. Verify the quota before
deployment day:

```
aws service-quotas get-service-quota \
  --service-code bedrock \
  --quota-code L-B29C9321 \
  --region us-east-1 \
  --query 'Quota.[QuotaName,Value,Adjustable]' \
  --output text
```

`L-B29C9321` is the quota code for the Claude Sonnet 4.6 daily token quota
specifically. Every model has its own code, so check the code for whichever
model you are actually deploying. This quota is not self-service adjustable,
so raising it means opening a Support Center case, not calling an API.
**Blocks if missing:** every query fails with a throttling error reading "Too
many tokens per day," and the turnaround on a support case is measured in
days, so treat this as a "file it two weeks out" item, not a deployment day
item.

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
