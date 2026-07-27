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
`api.anthropic.com` or to Amazon Bedrock. Only egress-on combinations work
right now: egress on with either provider. Both egress-off (air-gapped)
combinations are blocked at plan time. `llm_provider = "anthropic"` with
`enable_egress = false` fails because there is no route out and no VPC
endpoint can exist for a third party SaaS endpoint. `llm_provider =
"bedrock"` with `enable_egress = false` -- previously the air-gapped
recommendation -- is *also* now blocked: the ECS task definition (`ecs.tf`)
runs a Qdrant vector store sidecar pulled from Docker Hub, which air-gapped
subnets cannot reach and which this module does not mirror into ECR. The
module refuses to plan either blocked combination rather than let it fail
hours later in production. Full detail, including the cost and connectivity
tradeoff of each combination, is in `../PREREQUISITES.md` under "Network and
egress: a real choice, not a checkbox".

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
to add**, confirmed against a real account after the Qdrant sidecar was
added to `ecs.tf` -- the sidecar lives inside the task definition JSON, so it
adds zero Terraform resources of its own. The egress-enabled Bedrock path
(`enable_egress = true`, `llm_provider = "bedrock"`) plans **33 resources to
add** -- one fewer, because Bedrock mode skips the Secrets Manager secret
and its execution-role read policy that Anthropic mode creates, and adds
back only the single Bedrock invoke policy Anthropic mode does not need.
Neither `enable_egress = false` combination produces a plan Terraform will
let you apply. `terraform plan` still walks every other resource and prints
a tentative count for both (37 for `llm_provider = "anthropic"`, 35 for
`llm_provider = "bedrock"`, at time of writing -- these will drift and are
not meaningful, see below) -- preconditions do not stop that walk -- but it
then reports "Terraform planned the following actions, but then encountered
a problem" and exits non-zero, so neither count is ever a real, applicable
plan. `egress_provider_guard` in `guard.tf` carries two `precondition`
blocks, and `enable_egress = false` fails at least one of them regardless of
`llm_provider`: the second precondition (added alongside the Qdrant sidecar,
since air-gapped subnets cannot pull it from Docker Hub) fails every
`enable_egress = false` plan on its own, and `llm_provider = "anthropic"`
additionally fails the pre-existing first precondition. Neither precondition
adds a Terraform resource of its own.

## Docker Hub is a runtime dependency, not just an air-gapped blocker

Every task launch -- not only the blocked air-gapped path above -- pulls the
Qdrant sidecar image from Docker Hub through the NAT gateway. All tasks in
this deployment share one NAT gateway's public IP, and Docker Hub's
anonymous pull rate limit is enforced per IP: a restart storm, or raising
`desired_count`, can hit `toomanyrequests` and land tasks in
`CannotPullContainerError`, the same failure mode the air-gapped guard above
exists to prevent, just from a different cause. Mirroring the image into
the existing ECR repository (the same fix noted above for closing the
air-gapped gap) would remove this dependency too.

## Health check is the readiness gate, not a liveness check

`GET /api/health` is what `aws_lb_target_group.custos` in `alb.tf` polls
(`matcher = "200"`) to decide whether to send traffic to a task. It returns
HTTP 503 while the vector index is not ready and HTTP 200 once it is, because
that decision is the whole point: this task also runs a Qdrant sidecar (see
`ecs.tf`) with ephemeral storage, so every fresh task starts unindexed and
needs a few seconds to reindex the corpus before it can answer anything.

While the app is still building its index, there is no listening socket at
all yet -- `custos.boot.wait_for_qdrant` and the corpus reindex both run
inside FastAPI's startup lifespan, before uvicorn binds the port, so the ALB
sees connection-refused during that window either way. The case an
always-200 endpoint actually breaks is the one *after* boot: if
`wait_for_qdrant`'s 60s poll times out, or the index never reaches the
expected chunk count, the app still binds its socket and starts serving
(`_index_ready` just stays `False`) -- permanently degraded, not still
booting. An endpoint that reports liveness ("the process is up") instead of
readiness ("the process can serve a real request") would report that
permanently-broken task as healthy forever: the ALB would keep routing
`/api/chat` traffic to it, every one of those requests would fail, and
nothing would ever flip the target back to unhealthy. Returning 503 while
`_index_ready` is `False` is what lets the ALB catch that state at all; the
self-heal recheck already in `health()` is what gives the task a path back
to 200 without a restart -- but that path is bounded, not indefinite. With
`health_check_grace_period_seconds = 180` and the ALB's `interval = 10`,
`unhealthy_threshold = 3` (`alb.tf`), a task still degraded roughly 210s
after reaching RUNNING is deregistered and replaced by ECS regardless; at
`HEALTH_RECHECK_INTERVAL = 30` seconds between attempts, that is only about
six self-heal attempts to recover in, not an unlimited window.

## Cost table

AWS list price for `us-east-1`, verify before quoting a customer, prices
change and regions differ.

| Component | Rate | Notes |
|---|---|---|
| Application Load Balancer | ~$0.0225/hour | Plus a small per-LCU usage charge under real traffic. |
| NAT gateway (`enable_egress = true`) | ~$0.045/hour | Plus data processing per GB. Not created when air-gapped. |
| VPC interface endpoint (`enable_egress = false`) | ~$0.01/hour each | Four of them in Bedrock air-gapped mode: `ecr.api`, `ecr.dkr`, `logs`, `bedrock-runtime`. See `network.tf`. Currently unreachable: `egress_provider_guard` in `guard.tf` blocks every `enable_egress = false` plan, so this row does not apply to any combination the module will currently deploy. |
| VPC gateway endpoint (S3) | $0 | No hourly charge, only created when air-gapped -- same currently-blocked caveat as the row above. |
| Fargate task, default size (1 vCPU / 2 GB) | ~$0.0494/hour | At published Fargate Linux/x86 rates of $0.04048/vCPU-hour and $0.004445/GB-hour: 1 × $0.04048 + 2 × $0.004445 = $0.04937/hour. The task now runs the custos app container and a Qdrant sidecar together (see `ecs.tf`), which is why the default size doubled from the prior 0.5 vCPU / 1 GB. Scales linearly with `task_cpu`, `task_memory`, and `desired_count`. |
| ECR storage | $0.10/GB-month | Negligible for a demo corpus, this is layer storage, not documents. |
| Secrets Manager secret (`llm_provider = "anthropic"` only) | $0.40/month flat | Per secret, regardless of how often it is read. Not created, and not billed, in Bedrock mode. |
| CloudWatch Logs | ~$0.50/GB ingested, ~$0.03/GB-month stored | Usage-based, depends on log volume and `log_retention_days`. |

Bedrock itself has no fixed infrastructure row in this table beyond the
`bedrock-runtime` interface endpoint listed above. Model invocation is billed
separately, per input and output token, at whatever Bedrock's current
per-token rate is for the model you select. That is a usage-based cost, not
a fixed hourly rate, and is not included in the hourly figures below.

With the default egress-enabled Anthropic path (ALB + NAT + one Fargate task
running both the custos app container and the Qdrant sidecar), the hourly
rate is roughly $0.0225 + $0.045 + $0.0494 = **$0.12/hour**. A three hour
demo costs on the order of **$0.35** in compute. Left running for a full
month (730 hours), the same footprint costs on the order of **$85**, before
the flat $0.40/month Secrets Manager charge and any CloudWatch storage. In
Bedrock mode the Secrets Manager charge does not apply, but the ALB, NAT, and
Fargate task lines are otherwise the same, since only egress-enabled
deployments currently plan at all (see "`enable_egress` and `llm_provider`"
above) -- the VPC interface and gateway endpoint rows in the table above
describe the air-gapped path, which `egress_provider_guard` in
`guard.tf` blocks before it can be applied. This is the whole argument for
standing up, proving the point, and tearing down, rather than leaving a demo
account running.

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
