# A CloudWatch log group created with no retention setting keeps every log
# line forever and bills for that storage forever. This is a common surprise
# line item on a customer's first AWS bill, so retention is explicit here and
# controlled by var.log_retention_days rather than left at the default.

resource "aws_cloudwatch_log_group" "custos" {
  name              = "/ecs/custos-${var.environment}"
  retention_in_days = var.log_retention_days

  tags = {
    Name = "custos-${var.environment}-logs"
  }
}
