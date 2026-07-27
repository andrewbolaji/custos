variable "region" {
  description = "AWS region to deploy into. Changing this after the first apply moves nothing, it only affects new resources, so pick the final region up front. Affects data residency, see PREREQUISITES.md."
  type        = string
  default     = "us-east-1"
}

variable "aws_profile" {
  description = "Named AWS CLI profile whose credentials Terraform uses. Change this to point the entire deployment at a different set of credentials without editing any other file."
  type        = string
  default     = "custos-demo"
}

variable "expected_account_id" {
  description = "The 12 digit AWS account id this deployment is meant to run in. Required, no default on purpose, so a plan can never proceed against an unverified account. Compared against the caller identity in guard.tf, and the plan fails immediately if they do not match."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "expected_account_id must be exactly 12 digits, matching an AWS account id. A wrong value here would otherwise fail late, deep into resource creation, with a confusing error."
  }
}

variable "environment" {
  description = "Short environment name, used to namespace resource names such as the ECR repo, log group, and secret path. Changing it after the first apply creates a second, parallel set of resources rather than renaming the existing ones."
  type        = string
  default     = "demo"
}

variable "owner_tag" {
  description = "Value applied to the Owner tag on every resource, for cost and ownership tracing. Change this to whichever team or person is accountable for the AWS bill this deployment generates."
  type        = string
  default     = "aintellect"
}

variable "vpc_cidr" {
  description = "CIDR block for the new VPC. Must not overlap any network this account already peers with or connects to over VPN or Transit Gateway. Changing it after the first apply forces replacement of the VPC and everything inside it."
  type        = string
  default     = "10.40.0.0/16"

  validation {
    condition     = can(cidrhost(var.vpc_cidr, 0))
    error_message = "vpc_cidr must be a valid IPv4 CIDR block, for example 10.40.0.0/16. An invalid value here would otherwise fail late, when the VPC resource itself is created."
  }
}

variable "enable_egress" {
  description = "true builds a NAT gateway so the service can reach the public internet, which it needs to call a hosted generation model. false builds no NAT gateway and no default route out of the private subnets, instead relying on VPC endpoints, for an air-gapped deployment. See network.tf for the full cost and connectivity tradeoff."
  type        = bool
  default     = true
}

variable "alb_internal" {
  description = "false puts the load balancer on the public internet, reachable from 0.0.0.0/0. true makes it internal, reachable only from inside vpc_cidr, for deployments accessed over VPN or from a peered network only. Changing it after the first apply forces replacement of the load balancer."
  type        = bool
  default     = false
}

variable "container_port" {
  description = "TCP port the application container listens on inside the task. Must match the EXPOSE and CMD port in the Dockerfile, currently 8000, or the health check and target group will never see a healthy task."
  type        = number
  default     = 8000
}

variable "task_cpu" {
  description = "Fargate task CPU units, 1024 units equals 1 vCPU. Must be a value Fargate accepts for the chosen task_memory, see AWS Fargate task size documentation. Raising this increases the hourly Fargate bill."
  type        = number
  default     = 512
}

variable "task_memory" {
  description = "Fargate task memory in MiB. Must be a value Fargate accepts for the chosen task_cpu. The embedding model and any in-memory index need headroom, so this should not be dropped far below the default without testing."
  type        = number
  default     = 1024
}

variable "desired_count" {
  description = "Number of task instances the ECS service keeps running. Raising this increases availability and the Fargate bill in direct proportion. 0 stops the service without destroying it, useful for a low-cost pause between demos."
  type        = number
  default     = 1

  validation {
    condition     = var.desired_count >= 0
    error_message = "desired_count cannot be negative."
  }
}

variable "log_retention_days" {
  description = "How many days CloudWatch keeps application logs before deleting them. A log group with no retention setting at all keeps logs, and bills for their storage, forever. Raise this if the customer's data handling policy requires a longer audit trail."
  type        = number
  default     = 7
}
