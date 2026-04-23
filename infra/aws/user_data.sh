#!/bin/bash
set -euo pipefail

# ── Install Docker ────────────────────────────────────────────────────────────
dnf update -y
dnf install -y docker jq aws-cli
systemctl enable --now docker
usermod -aG docker ec2-user

# ── Authenticate to ECR and pull image ───────────────────────────────────────
ECR_REGISTRY="${ecr_registry}"
ECR_REPO="${ecr_repo}"
AWS_REGION="${aws_region}"
SECRET_ARN="${secret_arn}"
CLOUDFRONT_DOMAIN="${cloudfront_domain}"
ORIGIN_VERIFY="${origin_verify}"

aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$ECR_REGISTRY"

docker pull "$ECR_REGISTRY/$ECR_REPO:latest"

# ── Fetch secrets from Secrets Manager ───────────────────────────────────────
SECRET_JSON=$(aws secretsmanager get-secret-value \
  --region "$AWS_REGION" \
  --secret-id "$SECRET_ARN" \
  --query SecretString \
  --output text)

SAP_USERNAME=$(echo "$SECRET_JSON"          | jq -r '.SAP_USERNAME')
SAP_PASSWORD=$(echo "$SECRET_JSON"          | jq -r '.SAP_PASSWORD')
AZURE_TENANT_ID=$(echo "$SECRET_JSON"       | jq -r '.AZURE_TENANT_ID')
AZURE_CLIENT_ID=$(echo "$SECRET_JSON"       | jq -r '.AZURE_CLIENT_ID')
AZURE_CLIENT_SECRET=$(echo "$SECRET_JSON"   | jq -r '.AZURE_CLIENT_SECRET')
ALLOWED_EMAIL_DOMAINS=$(echo "$SECRET_JSON" | jq -r '.ALLOWED_EMAIL_DOMAINS')

# ── Write systemd unit so container survives reboots ─────────────────────────
cat > /etc/systemd/system/mcp-sap-notes.service <<EOF
[Unit]
Description=MCP SAP Notes HTTP server
After=docker.service
Requires=docker.service

[Service]
Restart=always
RestartSec=10
ExecStartPre=-/usr/bin/docker stop mcp-sap-notes
ExecStartPre=-/usr/bin/docker rm   mcp-sap-notes
ExecStart=/usr/bin/docker run --rm --name mcp-sap-notes \
  --shm-size=1g \
  -p 8090:8090 \
  -e HTTP_HOST=0.0.0.0 \
  -e HTTP_PORT=8090 \
  -e MCP_HTTP_PATH=/mcp \
  -e MCP_SERVER_URL=https://$CLOUDFRONT_DOMAIN/mcp \
  -e SAP_USERNAME="$SAP_USERNAME" \
  -e SAP_PASSWORD="$SAP_PASSWORD" \
  -e AZURE_TENANT_ID="$AZURE_TENANT_ID" \
  -e AZURE_CLIENT_ID="$AZURE_CLIENT_ID" \
  -e AZURE_CLIENT_SECRET="$AZURE_CLIENT_SECRET" \
  -e ALLOWED_EMAIL_DOMAINS="$ALLOWED_EMAIL_DOMAINS" \
  -e DOCKER_ENV=true \
  -e LOG_LEVEL=info \
  $ECR_REGISTRY/$ECR_REPO:latest
ExecStop=/usr/bin/docker stop mcp-sap-notes

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now mcp-sap-notes
