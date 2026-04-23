# ── WAF (must be us-east-1 for CloudFront) ───────────────────────────────────

resource "aws_wafv2_web_acl" "app" {
  provider    = aws.us_east_1
  name        = "${var.project_name}-waf"
  description = "Allow only requests that carry the correct X-MCP-Secret header"
  scope       = "CLOUDFRONT"

  default_action {
    block {}
  }

  # Rule: pass through if X-MCP-Secret matches the generated token
  rule {
    name     = "AllowClaudeRequests"
    priority = 1

    action {
      allow {}
    }

    statement {
      byte_match_statement {
        field_to_match {
          single_header { name = "x-mcp-secret" }
        }
        positional_constraint = "EXACTLY"
        search_string         = random_password.mcp_secret.result
        text_transformation {
          priority = 0
          type     = "NONE"
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "AllowClaudeRequests"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${var.project_name}-waf"
    sampled_requests_enabled   = true
  }

  tags = { Project = var.project_name }
}

# ── CloudFront distribution ───────────────────────────────────────────────────

resource "aws_cloudfront_distribution" "app" {
  enabled     = true
  comment     = "mcp-sap-notes MCP endpoint"
  price_class = "PriceClass_100" # US + EU edge locations only
  web_acl_id  = aws_wafv2_web_acl.app.arn

  origin {
    # EC2 Elastic IP as origin (HTTP only between CF and EC2 inside AWS)
    domain_name = aws_eip.app.public_ip
    origin_id   = "ec2-mcp"

    custom_origin_config {
      http_port              = 8090
      https_port             = 443
      origin_protocol_policy = "http-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }

    # Defence-in-depth: EC2 verifies this header so it never serves without CF
    custom_header {
      name  = "X-Origin-Verify"
      value = random_password.origin_verify.result
    }
  }

  default_cache_behavior {
    target_origin_id       = "ec2-mcp"
    viewer_protocol_policy = "https-only"
    allowed_methods        = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods         = ["GET", "HEAD"]
    compress               = false

    # MCP is stateful/streaming — disable caching
    cache_policy_id          = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # CachingDisabled managed policy
    origin_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac" # AllViewerExceptHostHeader managed policy
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  tags = { Project = var.project_name }
}
