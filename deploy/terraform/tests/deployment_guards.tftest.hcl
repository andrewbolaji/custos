mock_provider "aws" {}

override_data {
  target = data.aws_caller_identity.current
  values = {
    account_id = "123456789012"
  }
}

override_data {
  target = data.aws_availability_zones.available
  values = {
    names = ["us-east-1a", "us-east-1b"]
  }
}

run "tls_with_certificate_plans" {
  command = plan

  variables {
    expected_account_id = "123456789012"
    acm_certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/test"
  }

  assert {
    condition = (
      aws_lb_listener.http.port == 443 &&
      aws_lb_listener.http.protocol == "HTTPS" &&
      alltrue([for rule in aws_security_group.alb.ingress : rule.from_port == 443])
    )
    error_message = "The default plan must expose only the HTTPS listener port."
  }
}

run "missing_certificate_is_refused" {
  command = plan

  variables {
    expected_account_id = "123456789012"
  }

  expect_failures = [terraform_data.egress_provider_guard]
}

run "plaintext_without_acknowledgement_is_refused" {
  command = plan

  variables {
    expected_account_id  = "123456789012"
    allow_plaintext_http = true
  }

  expect_failures = [terraform_data.egress_provider_guard]
}

run "explicit_plaintext_demo_plans" {
  command = plan

  variables {
    expected_account_id  = "123456789012"
    allow_plaintext_http = true
    i_accept_plaintext   = true
  }

  assert {
    condition = (
      aws_lb_listener.http.port == 80 &&
      aws_lb_listener.http.protocol == "HTTP" &&
      alltrue([for rule in aws_security_group.alb.ingress : rule.from_port == 80])
    )
    error_message = "The explicit plaintext plan must expose only port 80."
  }
}

run "multiple_tasks_are_refused" {
  command = plan

  variables {
    expected_account_id = "123456789012"
    acm_certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/test"
    desired_count       = 2
  }

  expect_failures = [var.desired_count]
}
