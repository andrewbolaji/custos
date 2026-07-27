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
