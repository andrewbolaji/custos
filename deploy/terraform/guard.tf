# The single most expensive mistake in Terraform is applying into the wrong
# AWS account. Credentials are ambient, picked up from whatever profile or
# environment variable happens to be active in the shell, and nothing about
# running `terraform apply` forces you to look at which account you are about
# to change. This resource fails the plan immediately, before anything else
# is created or modified, if the caller identity does not match the account
# id the operator declared they intended to target.

data "aws_caller_identity" "current" {}

resource "terraform_data" "account_guard" {
  input = data.aws_caller_identity.current.account_id

  lifecycle {
    precondition {
      condition     = data.aws_caller_identity.current.account_id == var.expected_account_id
      error_message = "Refusing to proceed. Expected AWS account ${var.expected_account_id}, but the active credentials resolve to account ${data.aws_caller_identity.current.account_id}. Check your AWS profile before re-running."
    }
  }
}

# Two independent reasons enable_egress = false can be unsafe to build, so
# this resource carries two precondition blocks (Terraform evaluates every
# precondition in a lifecycle block and reports every one that fails, not
# just the first) rather than two separate guard resources. Keeping both
# checks on one terraform_data resource, instead of adding a second one,
# also matters concretely here: the Qdrant sidecar added to ecs.tf lives
# inside the task definition JSON and deliberately adds zero Terraform
# resources of its own (see deploy/README.md's "Verified resource counts"),
# and a second guard *resource* would have silently broken that invariant.
#
# 1. enable_egress = false with llm_provider = "anthropic" plans and applies
#    cleanly and then fails hours later, in production, as a connection
#    timeout: the private subnets have no route out, the container starts,
#    the ALB health check passes, and every real query hangs until it times
#    out. A variable validation block cannot do this, because validation
#    cannot reference a different variable, so this uses the same
#    precondition pattern as the account guard above.
#
# 2. enable_egress = false at all (regardless of llm_provider) cannot pull
#    the Qdrant sidecar added to ecs.tf. That sidecar (qdrant/qdrant, the
#    actual RAG vector store backend) is pulled straight from Docker Hub,
#    because there was previously no vector store anywhere in this AWS
#    deployment at all. aws_ecr_repository.custos (ecr.tf) mirrors only the
#    custos application image; nothing in this module mirrors qdrant/qdrant
#    into ECR. In air-gapped mode there is no NAT gateway and no route out
#    of the private subnets -- network.tf's interface endpoints cover
#    ecr.api, ecr.dkr, logs, and bedrock-runtime only, none of which is
#    Docker Hub. Left unguarded this fails exactly like reason 1 above: the
#    plan and apply succeed, the task sits in PENDING, and
#    CannotPullContainerError only surfaces once someone checks the ECS
#    console in production. Until this module mirrors the Qdrant image into
#    ECR (or an alternative sidecar-free path exists), air-gapped
#    deployments of any llm_provider are blocked at plan time instead.
resource "terraform_data" "egress_provider_guard" {
  input = "${var.enable_egress}-${var.llm_provider}"

  lifecycle {
    precondition {
      condition     = !(var.enable_egress == false && var.llm_provider == "anthropic")
      error_message = "Refusing to proceed. Air-gapped mode (enable_egress = false) cannot use the Anthropic provider even on top of the general air-gapped block below: the private subnets have no route to api.anthropic.com, and no VPC endpoint for it can exist, because PrivateLink covers AWS services and Marketplace partner services, not arbitrary third party SaaS. This is a SEPARATE, Anthropic-specific problem from the Qdrant sidecar issue in the other precondition on this resource -- fixing one does not fix the other. Set enable_egress = true to use the Anthropic provider at all."
    }

    precondition {
      condition     = var.enable_egress == true
      error_message = "Refusing to proceed. enable_egress = false (air-gapped) cannot currently run this module AT ALL, regardless of llm_provider: the ECS task definition's Qdrant sidecar (see ecs.tf) is pulled from Docker Hub at apply time, and air-gapped subnets have no route to Docker Hub and no ECR mirror of that image. There is currently no air-gapped combination this module can deploy. Set enable_egress = true, or mirror qdrant/qdrant:v1.18.0 into an ECR repository this module can reach and update ecs.tf before attempting an air-gapped deployment."
    }
  }
}
