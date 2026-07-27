# Deploying Custos into a customer AWS account

This Terraform module stands up Custos as a single ECS Fargate service inside
a new VPC in the customer's own AWS account. It builds the network, load
balancer, container registry, and secret container needed to run the service,
but never creates real AWS resources until someone reviews a plan and runs
apply on purpose. Tearing it back down is a single command, because the
operating model here is stand up, prove, tear down, not leave it running.

## Prerequisites

Read `../PREREQUISITES.md` in full before starting. In short:

- AWS account id, owner, and billing contact, see "AWS account and ownership".
- Region and any data residency requirement, see "Region and data residency".
- An IAM role we can assume, see "The IAM role you create for us".
- A decision on `enable_egress` and `llm_provider` together, see "Network and egress: a real choice, not a checkbox".
- If `llm_provider = "anthropic"`, an Anthropic API key and a named holder; if `llm_provider = "bedrock"`, verified model access and daily token quota in the target account, see "Generation model credentials" and "Bedrock account prerequisites".
- DNS control and an ACM certificate, if a custom domain is wanted, see "Custom domain and TLS".
- Corpus format, volume, location, and access rules, see "Your document corpus".

## `enable_egress` and `llm_provider`

These two variables are decided together, not one at a time. `enable_egress`
controls whether the private subnets have a NAT gateway route to the public
internet at all. `llm_provider` controls whether the model call goes to
`api.anthropic.com` or to Amazon Bedrock. Three of the four combinations
work: egress on with either provider, and egress off with `llm_provider =
"bedrock"` (air-gapped, fully functional, the recommendation for any
no-internet policy). The fourth, egress off with `llm_provider =
"anthropic"`, does not work, because there is no route out and no VPC
endpoint can exist for a third party SaaS endpoint, and the module now
refuses to plan that combination at all rather than let it fail hours later
in production. Full detail, including the cost and connectivity tradeoff of
each combination, is in `../PREREQUISITES.md` under "Network and egress: a
real choice, not a checkbox".

## Command sequence

```bash
# 1. Point the AWS CLI and Terraform at the customer account, using the role
#    described in PREREQUISITES.md. Never use personal or root credentials.
export AWS_PROFILE=custos-demo

# 2. Copy the example vars and fill in the real account id and any overrides.
cp deploy/terraform/terraform.tfvars.example deploy/terraform/terraform.tfvars

cd deploy/terraform

# 3. Download the AWS provider and set up local state.
terraform init

# 4. Confirm the configuration is syntactically and internally valid.
terraform validate

# 5. Compute what would change, save it, and read it. This is the step that
#    matters most, nothing after this should surprise you.
terraform plan -out=custos.tfplan

# 6. Review the saved plan output with whoever owns the account before
#    proceeding. Confirm the resource count and the account id in the guard
#    check match what you expect.

# 7. Apply the reviewed plan. This is the only step that creates real,
#    billable AWS resources.
terraform apply custos.tfplan

# 8. Build the image and push it to the ECR repository Terraform just created.
aws ecr get-login-password --profile "$AWS_PROFILE" | \
  docker login --username AWS --password-stdin "$(terraform output -raw ecr_repository_url | cut -d/ -f1)"
docker build -t "$(terraform output -raw ecr_repository_url):latest" ../..
docker push "$(terraform output -raw ecr_repository_url):latest"

# 9. Anthropic mode only (llm_provider = "anthropic"). Put the real Anthropic
#    API key into the secret container, out of band, never through Terraform.
#    See deploy/terraform/secrets.tf for why. In Bedrock mode, secret_arn is
#    null, this command has nothing to target, and there is no equivalent
#    step: that is the point of Bedrock mode, not an omission. Skip step 9
#    entirely if llm_provider = "bedrock".
aws secretsmanager put-secret-value \
  --secret-id "$(terraform output -raw secret_arn)" \
  --secret-string "PASTE_SECRET_HERE" \
  --profile "$AWS_PROFILE"

# 10. Force a new deployment so the running task picks up the image and the
#     secret for the first time.
aws ecs update-service \
  --cluster "$(terraform output -raw ecs_cluster_name)" \
  --service "$(terraform output -raw ecs_service_name)" \
  --force-new-deployment \
  --profile "$AWS_PROFILE"

# 11. When the demo or engagement is over, tear it down. See "Teardown" below
#     before running this.
terraform destroy
```

Verified resource counts, from `terraform plan` against a real account with
the AWS provider pinned in `.terraform.lock.hcl` (counts will drift if the
provider version changes): the default egress-enabled Anthropic path
(`enable_egress = true`, `llm_provider = "anthropic"`) plans **34 resources
to add**. The air-gapped Bedrock path (`enable_egress = false`, `llm_provider
= "bedrock"`) plans **36 resources to add**. The disallowed combination
(`enable_egress = false`, `llm_provider = "anthropic"`) does not reach a
resource count at all, it fails at the `egress_provider_guard` precondition
in `guard.tf` before Terraform computes one.

## Cost table

AWS list price for `us-east-1`, verify before quoting a customer, prices
change and regions differ.

| Component | Rate | Notes |
|---|---|---|
| Application Load Balancer | ~$0.0225/hour | Plus a small per-LCU usage charge under real traffic. |
| NAT gateway (`enable_egress = true`) | ~$0.045/hour | Plus data processing per GB. Not created when air-gapped. |
| VPC interface endpoint (`enable_egress = false`) | ~$0.01/hour each | Four of them in Bedrock air-gapped mode: `ecr.api`, `ecr.dkr`, `logs`, `bedrock-runtime`. See `network.tf`. |
| VPC gateway endpoint (S3) | $0 | No hourly charge, only created when air-gapped. |
| Fargate task, default size (0.5 vCPU / 1 GB) | ~$0.0247/hour | Scales linearly with `task_cpu`, `task_memory`, and `desired_count`. |
| ECR storage | $0.10/GB-month | Negligible for a demo corpus, this is layer storage, not documents. |
| Secrets Manager secret (`llm_provider = "anthropic"` only) | $0.40/month flat | Per secret, regardless of how often it is read. Not created, and not billed, in Bedrock mode. |
| CloudWatch Logs | ~$0.50/GB ingested, ~$0.03/GB-month stored | Usage-based, depends on log volume and `log_retention_days`. |

Bedrock itself has no fixed infrastructure row in this table beyond the
`bedrock-runtime` interface endpoint listed above. Model invocation is billed
separately, per input and output token, at whatever Bedrock's current
per-token rate is for the model you select. That is a usage-based cost, not
a fixed hourly rate, and is not included in the hourly figures below.

With the default egress-enabled Anthropic path (ALB + NAT + one small Fargate
task), the hourly rate is roughly **$0.09/hour**. A three hour demo costs on
the order of **$0.28** in compute. Left running for a full month (730
hours), the same footprint costs on the order of **$67**, before the flat
$0.40/month Secrets Manager charge and any CloudWatch storage. In Bedrock
mode the Secrets Manager charge does not apply, and in air-gapped Bedrock
mode the NAT gateway line is replaced by the interface and gateway endpoint
lines in the table above. This is the whole argument for standing up, proving
the point, and tearing down, rather than leaving a demo account running.

## Teardown

**Tearing down is not optional cleanup, it is part of the deployment model.**
Every environment stood up for a demo or a trial should be destroyed when the
engagement ends, not left running on the assumption someone will get to it.

```bash
cd deploy/terraform
terraform destroy
```

Two things `terraform destroy` will do that are easy to miss:

- It removes the ECR repository even though it holds pushed images, only
  because `force_delete = true` is set in `ecr.tf`. Without that flag, destroy
  would fail outright on a non-empty repository, and someone would have to
  delete images by hand first.
- It deletes the CloudWatch log group along with every log line inside it,
  permanently. If the engagement or a compliance requirement needs those logs
  retained, export them before running destroy, not after.

## What CI checks

Every push and pull request against this repository runs `terraform fmt
-check -recursive`, `terraform init -backend=false`, and `terraform validate`
against this directory, and none of those three commands need AWS
credentials to run.

That coverage has a real boundary. `lifecycle.precondition` blocks, like the
account guard and the egress and provider guard in `guard.tf`, and `count`
expressions, like the ones in `network.tf` that toggle resources on and off
between egress-enabled and air-gapped mode, are both evaluated at plan time,
not at validate time, so CI does not exercise either. The air-gapped guard
described above is enforced when you run `terraform plan` yourself, as in
step 5 of the command sequence, not by this repository's CI.
