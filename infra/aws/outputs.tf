output "cloudfront_url" {
  description = "Final MCP endpoint URL — use this in Claude's MCP configuration"
  value       = "https://${aws_cloudfront_distribution.app.domain_name}/mcp"
}

output "mcp_secret_header" {
  description = "Value for the X-MCP-Secret header that Claude must send"
  value       = random_password.mcp_secret.result
  sensitive   = true
}

output "elastic_ip" {
  description = "Static public IP of the EC2 instance"
  value       = aws_eip.app.public_ip
}

output "ecr_repository_url" {
  description = "ECR repository — push your Docker image here before applying"
  value       = aws_ecr_repository.app.repository_url
}

output "secret_arn" {
  description = "Secrets Manager ARN (contains all runtime credentials)"
  value       = aws_secretsmanager_secret.app.arn
}
