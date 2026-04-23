#!/usr/bin/env bash
# deploy.sh — Build image, push to ECR, apply Terraform, print final URL
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$SCRIPT_DIR/infra/aws"
AWS_REGION="${AWS_REGION:-us-east-1}"

# ── Helpers ───────────────────────────────────────────────────────────────────
bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
info()  { printf '  \033[34m→\033[0m %s\n' "$*"; }
ok()    { printf '  \033[32m✓\033[0m %s\n' "$*"; }
die()   { printf '\033[31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# ── Pre-flight checks ─────────────────────────────────────────────────────────
bold "Pre-flight checks"
command -v terraform >/dev/null || die "terraform not found — install from https://developer.hashicorp.com/terraform/downloads"
command -v docker    >/dev/null || die "docker not found"
command -v aws       >/dev/null || die "aws CLI not found"
aws sts get-caller-identity >/dev/null 2>&1 || die "AWS credentials not configured — run 'aws configure'"
ok "All tools present"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
info "AWS account: $ACCOUNT_ID  region: $AWS_REGION"

# ── Step 1: Terraform init + partial apply (ECR only) ────────────────────────
bold "Step 1 — Create ECR repository"
cd "$INFRA_DIR"

# Variables file prompt if tfvars missing
if [[ ! -f terraform.tfvars ]]; then
  cat <<MSG

  No terraform.tfvars found. Create $INFRA_DIR/terraform.tfvars with:

    aws_region            = "us-east-1"
    sap_username          = "your-suser@company.com"
    sap_password          = "your-password"
    azure_tenant_id       = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
    azure_client_id       = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
    azure_client_secret   = "your-azure-secret"
    allowed_email_domains = "company.com"

MSG
  die "terraform.tfvars required"
fi

terraform init -upgrade -input=false
terraform apply -target=aws_ecr_repository.app -auto-approve -input=false
ECR_URL=$(terraform output -raw ecr_repository_url)
ok "ECR: $ECR_URL"

# ── Step 2: Build & push Docker image ────────────────────────────────────────
bold "Step 2 — Build and push Docker image"
cd "$SCRIPT_DIR"

aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

docker build --platform linux/amd64 -t "$ECR_URL:latest" .
docker push "$ECR_URL:latest"
ok "Image pushed to ECR"

# ── Step 3: Apply remaining infrastructure ───────────────────────────────────
bold "Step 3 — Deploy full infrastructure (EIP → CloudFront → EC2)"
cd "$INFRA_DIR"
terraform apply -auto-approve -input=false
ok "Infrastructure deployed"

# ── Step 4: Print results ─────────────────────────────────────────────────────
bold "Deployment complete!"
CF_URL=$(terraform output -raw cloudfront_url)
MCP_SECRET=$(terraform output -raw mcp_secret_header)
ELASTIC_IP=$(terraform output -raw elastic_ip)

cat <<SUMMARY

  ┌─────────────────────────────────────────────────────────────────┐
  │  MCP Endpoint (add this to Claude):                             │
  │                                                                 │
  │  URL:    $CF_URL
  │                                                                 │
  │  Required header:                                               │
  │  X-MCP-Secret: $MCP_SECRET
  │                                                                 │
  │  EC2 Elastic IP:  $ELASTIC_IP                                   │
  └─────────────────────────────────────────────────────────────────┘

  Claude MCP configuration (claude_desktop_config.json):

  {
    "mcpServers": {
      "sap-notes": {
        "type": "http",
        "url": "$CF_URL",
        "headers": {
          "X-MCP-Secret": "$MCP_SECRET"
        }
      }
    }
  }

SUMMARY
