variable "aws_region" {
  description = "AWS region for all resources except WAF (WAF is always us-east-1)"
  default     = "us-east-1"
}

variable "project_name" {
  description = "Prefix for all resource names"
  default     = "mcp-sap-notes"
}

variable "instance_type" {
  description = "EC2 instance type (Playwright needs >= t3.medium)"
  default     = "t3.medium"
}

# SAP credentials
variable "sap_username" {
  description = "SAP S-user email"
  type        = string
  sensitive   = true
}

variable "sap_password" {
  description = "SAP S-user password"
  type        = string
  sensitive   = true
}

# Azure OAuth (required for HTTP mode)
variable "azure_tenant_id" {
  description = "Azure AD tenant ID"
  type        = string
  sensitive   = true
}

variable "azure_client_id" {
  description = "Azure app (client) ID"
  type        = string
  sensitive   = true
}

variable "azure_client_secret" {
  description = "Azure app client secret"
  type        = string
  sensitive   = true
}

variable "allowed_email_domains" {
  description = "Comma-separated email domains allowed to use the service (e.g. company.com)"
  type        = string
  default     = ""
}
