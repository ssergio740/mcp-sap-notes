resource "aws_secretsmanager_secret" "app" {
  name                    = "${var.project_name}/config"
  description             = "All runtime env vars for mcp-sap-notes"
  recovery_window_in_days = 0 # allow immediate deletion during dev; change to 7+ in prod

  tags = { Project = var.project_name }
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    SAP_USERNAME          = var.sap_username
    SAP_PASSWORD          = var.sap_password
    AZURE_TENANT_ID       = var.azure_tenant_id
    AZURE_CLIENT_ID       = var.azure_client_id
    AZURE_CLIENT_SECRET   = var.azure_client_secret
    ALLOWED_EMAIL_DOMAINS = var.allowed_email_domains
    MCP_SECRET_HEADER     = random_password.mcp_secret.result
    ORIGIN_VERIFY_SECRET  = random_password.origin_verify.result
  })

  # Secret is re-written whenever CloudFront domain is known (no-op after first apply)
  lifecycle {
    ignore_changes = [secret_string]
  }
}
