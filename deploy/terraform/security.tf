# Referencing a security group by id, rather than allowing a CIDR range, is
# what makes "only the load balancer can talk to the app" a fact enforced by
# AWS rather than a hope written in a comment. A CIDR rule would also let
# anything else launched into that same subnet range reach the task.

resource "aws_security_group" "alb" {
  name        = "custos-${var.environment}-alb"
  description = "Custos ALB. Inbound HTTP/HTTPS, outbound to the ECS tasks only."
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = var.alb_internal ? [var.vpc_cidr] : ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = var.alb_internal ? [var.vpc_cidr] : ["0.0.0.0/0"]
  }

  egress {
    description = "To ECS tasks"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "custos-${var.environment}-alb-sg"
  }
}

resource "aws_security_group" "ecs_tasks" {
  name        = "custos-${var.environment}-ecs-tasks"
  description = "Custos ECS tasks. Inbound only from the ALB, on the app port."
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "App traffic from the ALB only"
    from_port       = var.container_port
    to_port         = var.container_port
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  tags = {
    Name = "custos-${var.environment}-ecs-tasks-sg"
  }
}

# Egress rules respect enable_egress. When true, the task can reach the public
# internet, which it needs to call a hosted generation model. When false, it
# gets no 0.0.0.0/0 egress at all, only what the VPC endpoints require, which
# is enforced by the endpoint security group below, not by this one.

resource "aws_vpc_security_group_egress_rule" "ecs_tasks_internet" {
  count             = var.enable_egress ? 1 : 0
  security_group_id = aws_security_group.ecs_tasks.id
  description       = "Outbound internet, needed to call the hosted generation model"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

resource "aws_vpc_security_group_egress_rule" "ecs_tasks_to_endpoints" {
  count                        = var.enable_egress ? 0 : 1
  security_group_id            = aws_security_group.ecs_tasks.id
  description                  = "Outbound to VPC interface endpoints only"
  referenced_security_group_id = aws_security_group.vpc_endpoints[0].id
  ip_protocol                  = "-1"
}

# Security group for the VPC interface endpoints, only created in no-egress
# mode. Accepts HTTPS from the ECS tasks security group, by id, for the same
# reason the ALB to task path above is scoped by id and not by CIDR.

resource "aws_security_group" "vpc_endpoints" {
  count       = var.enable_egress ? 0 : 1
  name        = "custos-${var.environment}-vpc-endpoints"
  description = "Custos VPC interface endpoints. Inbound HTTPS from ECS tasks only."
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "HTTPS from ECS tasks"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_tasks.id]
  }

  tags = {
    Name = "custos-${var.environment}-vpc-endpoints-sg"
  }
}
