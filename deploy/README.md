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
- A decision on egress vs air-gapped, see "Network and egress: a real choice, not a checkbox".
- An Anthropic API key and a named holder, see "Generation model API key".
- DNS control and an ACM certificate, if a custom domain is wanted, see "Custom domain and TLS".
- Corpus format, volume, location, and access rules, see "Your document corpus".

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

# 9. Put the real Anthropic API key into the secret container, out of band,
#    never through Terraform. See deploy/terraform/secrets.tf for why.
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

## Cost table

AWS list price for `us-east-1`, verify before quoting a customer, prices
change and regions differ.

| Component | Rate | Notes |
|---|---|---|
| Application Load Balancer | ~$0.0225/hour | Plus a small per-LCU usage charge under real traffic. |
| NAT gateway (`enable_egress = true`) | ~$0.045/hour | Plus data processing per GB. Not created when air-gapped. |
| VPC interface endpoint (`enable_egress = false`) | ~$0.01/hour each | Four of them: ecr.api, ecr.dkr, logs, secretsmanager. |
| VPC gateway endpoint (S3) | $0 | No hourly charge, only created when air-gapped. |
| Fargate task, default size (0.5 vCPU / 1 GB) | ~$0.0247/hour | Scales linearly with `task_cpu`, `task_memory`, and `desired_count`. |
| ECR storage | $0.10/GB-month | Negligible for a demo corpus, this is layer storage, not documents. |
| Secrets Manager secret | $0.40/month flat | Per secret, regardless of how often it is read. |
| CloudWatch Logs | ~$0.50/GB ingested, ~$0.03/GB-month stored | Usage-based, depends on log volume and `log_retention_days`. |

With the default egress-enabled path (ALB + NAT + one small Fargate task),
the hourly rate is roughly **$0.09/hour**. A three hour demo costs on the
order of **$0.28** in compute. Left running for a full month (730 hours),
the same footprint costs on the order of **$67**, before the flat $0.40/month
Secrets Manager charge and any CloudWatch storage. This is the whole argument
for standing up, proving the point, and tearing down, rather than leaving a
demo account running.

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
