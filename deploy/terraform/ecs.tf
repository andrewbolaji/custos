resource "aws_ecs_cluster" "main" {
  name = "custos-${var.environment}"

  tags = {
    Name = "custos-${var.environment}-cluster"
  }
}

# Two separate roles, deliberately not one.
#
# The execution role is used by the ECS agent itself, before the container
# starts, to pull the image from ECR and to read the secret so it can inject
# it into the container's environment. It never runs application code.
#
# The task role is assumed by the application code once it is running inside
# the container, for any AWS API calls the app itself makes at runtime. Custos
# currently makes none, so this role is intentionally empty of permissions.
#
# Keeping them separate means a compromise of the running application does
# not automatically grant it the execution role's ability to pull images or
# read secrets, and a future permission the app needs gets added to the task
# role without touching how the container is bootstrapped.

resource "aws_iam_role" "execution" {
  name = "custos-${var.environment}-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name = "custos-${var.environment}-execution-role"
  }
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_secret_read" {
  name = "custos-${var.environment}-secret-read"
  role = aws_iam_role.execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = [aws_secretsmanager_secret.llm_api_key.arn]
    }]
  })
}

resource "aws_iam_role" "task" {
  name = "custos-${var.environment}-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name = "custos-${var.environment}-task-role"
  }
}

resource "aws_ecs_task_definition" "custos" {
  family                   = "custos-${var.environment}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = "custos"
      image     = "${aws_ecr_repository.custos.repository_url}:latest"
      essential = true

      portMappings = [
        {
          containerPort = var.container_port
          protocol      = "tcp"
        }
      ]

      # Injected via the task definition secrets block, resolved by the ECS
      # agent at task start using the execution role above, so the key value
      # never appears as a plain environment variable in the task definition
      # itself or in `aws ecs describe-tasks` output.
      secrets = [
        {
          name      = "ANTHROPIC_API_KEY"
          valueFrom = aws_secretsmanager_secret.llm_api_key.arn
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.custos.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])

  tags = {
    Name = "custos-${var.environment}-task-def"
  }
}

resource "aws_ecs_service" "custos" {
  name            = "custos-${var.environment}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.custos.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = [aws_subnet.private_a.id, aws_subnet.private_b.id]
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.custos.arn
    container_name   = "custos"
    container_port   = var.container_port
  }

  depends_on = [aws_lb_listener.http]

  tags = {
    Name = "custos-${var.environment}-service"
  }
}
