resource "aws_lb" "custos" {
  name               = "custos-${var.environment}"
  internal           = var.alb_internal
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = [aws_subnet.public_a.id, aws_subnet.public_b.id]

  tags = {
    Name = "custos-${var.environment}-alb"
  }
}

resource "aws_lb_target_group" "custos" {
  name        = "custos-${var.environment}"
  port        = var.container_port
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  health_check {
    path                = "/api/health"
    protocol            = "HTTP"
    healthy_threshold   = 3
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 10
    matcher             = "200"
  }

  tags = {
    Name = "custos-${var.environment}-tg"
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.custos.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.custos.arn
  }
}

# HTTPS listener, commented out until a custom domain and ACM certificate
# exist. See PREREQUISITES.md, "Custom domain and TLS certificate" for what
# the customer needs to provide before this can be enabled.
#
# resource "aws_lb_listener" "https" {
#   load_balancer_arn = aws_lb.custos.arn
#   port              = 443
#   protocol          = "HTTPS"
#   ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
#   certificate_arn   = var.acm_certificate_arn
#
#   default_action {
#     type             = "forward"
#     target_group_arn = aws_lb_target_group.custos.arn
#   }
# }
