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

# enable_egress = false with llm_provider = "anthropic" plans and applies
# cleanly and then fails hours later, in production, as a connection timeout:
# the private subnets have no route out, the container starts, the ALB health
# check passes, and every real query hangs until it times out. This guard
# turns that into a plan-time failure instead. A variable validation block
# cannot do this, because validation cannot reference a different variable,
# so this uses the same precondition pattern as the account guard above.
resource "terraform_data" "egress_provider_guard" {
  input = "${var.enable_egress}-${var.llm_provider}"

  lifecycle {
    precondition {
      condition     = !(var.enable_egress == false && var.llm_provider == "anthropic")
      error_message = "Refusing to proceed. Air-gapped mode (enable_egress = false) cannot use the Anthropic provider: the private subnets have no route to api.anthropic.com, and no VPC endpoint for it can exist, because PrivateLink covers AWS services and Marketplace partner services, not arbitrary third party SaaS. Set llm_provider = \"bedrock\" for an air-gapped deployment, or set enable_egress = true to keep the Anthropic provider."
    }
  }
}
