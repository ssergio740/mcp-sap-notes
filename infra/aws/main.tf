terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# WAF WebACLs for CloudFront must live in us-east-1
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}

# ── Data sources ─────────────────────────────────────────────────────────────

data "aws_caller_identity" "current" {}

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# CloudFront managed prefix list — so EC2 only accepts traffic from CF edge nodes
data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

# ── Random secrets ────────────────────────────────────────────────────────────

# Header value that Claude must send; WAF blocks everyone else
resource "random_password" "mcp_secret" {
  length  = 40
  special = false
}

# Custom header CF adds when talking to EC2 origin (defence-in-depth)
resource "random_password" "origin_verify" {
  length  = 40
  special = false
}

# ── Elastic IP (allocated before EC2 so CloudFront can reference it) ──────────

resource "aws_eip" "app" {
  domain = "vpc"
  tags   = { Name = "${var.project_name}-eip", Project = var.project_name }
}

# ── IAM role for EC2 (read secrets + pull from ECR) ──────────────────────────

resource "aws_iam_role" "ec2" {
  name = "${var.project_name}-ec2-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "ec2" {
  name = "${var.project_name}-ec2-policy"
  role = aws_iam_role.ec2.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = [aws_secretsmanager_secret.app.arn]
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_instance_profile" "ec2" {
  name = "${var.project_name}-ec2-profile"
  role = aws_iam_role.ec2.name
}

# ── Security group ────────────────────────────────────────────────────────────

resource "aws_security_group" "ec2" {
  name        = "${var.project_name}-sg"
  description = "Allow only CloudFront edge nodes inbound on port 8090"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "MCP from CloudFront"
    from_port       = 8090
    to_port         = 8090
    protocol        = "tcp"
    prefix_list_ids = [data.aws_ec2_managed_prefix_list.cloudfront.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project_name}-sg", Project = var.project_name }
}

# ── EC2 instance (created after CloudFront so we can pass the CF domain) ──────

resource "aws_instance" "app" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.instance_type
  iam_instance_profile   = aws_iam_instance_profile.ec2.name
  vpc_security_group_ids = [aws_security_group.ec2.id]
  subnet_id              = tolist(data.aws_subnets.default.ids)[0]

  user_data = base64encode(templatefile("${path.module}/user_data.sh", {
    aws_region        = var.aws_region
    ecr_registry      = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"
    ecr_repo          = aws_ecr_repository.app.name
    secret_arn        = aws_secretsmanager_secret.app.arn
    cloudfront_domain = aws_cloudfront_distribution.app.domain_name
    origin_verify     = random_password.origin_verify.result
  }))

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
  }

  depends_on = [aws_cloudfront_distribution.app]

  tags = { Name = "${var.project_name}-ec2", Project = var.project_name }
}

# ── Associate Elastic IP with EC2 ─────────────────────────────────────────────

resource "aws_eip_association" "app" {
  instance_id   = aws_instance.app.id
  allocation_id = aws_eip.app.id
}
