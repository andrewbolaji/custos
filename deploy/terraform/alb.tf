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
  port              = var.allow_plaintext_http ? 80 : 443
  protocol          = var.allow_plaintext_http ? "HTTP" : "HTTPS"
  ssl_policy        = var.allow_plaintext_http ? null : "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.allow_plaintext_http ? null : var.acm_certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.custos.arn
  }
}
