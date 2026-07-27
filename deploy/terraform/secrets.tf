# This creates only the empty secret container, never a version, never a value.
# Terraform writes every managed value into state in plaintext, so putting the
# real API key here would mean the key lives forever in every copy of the
# state file, including whatever backend or backup holds it. The value goes in
# out of band, once, by whoever holds the key, using the AWS CLI directly:
#
#   aws secretsmanager put-secret-value \
#     --secret-id custos/${var.environment}/llm-api-key \
#     --secret-string "PASTE_SECRET_HERE" \
#     --profile <aws_profile> \
#     --region <region>
#
# Replace PASTE_SECRET_HERE with the real key. That command never touches
# Terraform, so the key never enters a .tf file, a .tfvars file, or state.

resource "aws_secretsmanager_secret" "llm_api_key" {
  name        = "custos/${var.environment}/llm-api-key"
  description = "Anthropic API key for Custos generation model calls. Value is set out of band, see comment above."

  tags = {
    Name = "custos-${var.environment}-llm-api-key"
  }
}
