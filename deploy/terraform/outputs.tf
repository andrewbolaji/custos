output "alb_dns_name" {
  description = "Public (or internal, if alb_internal is true) DNS name of the load balancer. Point a CNAME here for a custom domain."
  value       = aws_lb.custos.dns_name
}

output "ecr_repository_url" {
  description = "ECR repository URL to push the application image to before the ECS service can start."
  value       = aws_ecr_repository.custos.repository_url
}

output "ecs_cluster_name" {
  description = "Name of the ECS cluster, needed for CLI commands like `aws ecs update-service`."
  value       = aws_ecs_cluster.main.name
}

output "ecs_service_name" {
  description = "Name of the ECS service, needed for CLI commands like `aws ecs update-service`."
  value       = aws_ecs_service.custos.name
}

output "secret_arn" {
  description = "ARN of the Secrets Manager container the LLM API key must be put into, see secrets.tf for the exact command. Null in Bedrock mode: no such secret exists."
  value       = var.llm_provider == "bedrock" ? null : aws_secretsmanager_secret.llm_api_key[0].arn
}

output "vpc_id" {
  description = "ID of the VPC this deployment created."
  value       = aws_vpc.main.id
}

output "egress_enabled" {
  description = "Whether this deployment can reach the public internet (NAT gateway) or is air-gapped (VPC endpoints only). Reflects the enable_egress variable at apply time."
  value       = var.enable_egress
}
