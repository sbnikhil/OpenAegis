terraform {
  required_version = ">= 1.0"
  
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

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

resource "random_id" "suffix" {
  byte_length = 4
}

# S3 bucket for file quarantine
resource "aws_s3_bucket" "quarantine" {
  bucket = "openaegis-quarantine-${var.environment}-${random_id.suffix.hex}"
  
  tags = {
    Name        = "OpenAegis File Quarantine"
    Environment = var.environment
    Project     = "OpenAegis"
  }
}

resource "aws_s3_bucket_versioning" "quarantine" {
  bucket = aws_s3_bucket.quarantine.id
  
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "quarantine" {
  bucket = aws_s3_bucket.quarantine.id
  
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "quarantine" {
  bucket = aws_s3_bucket.quarantine.id
  
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "quarantine" {
  bucket = aws_s3_bucket.quarantine.id
  
  rule {
    id     = "delete_old_files"
    status = "Enabled"
    
    filter {}  # Add this empty filter block
    
    expiration {
      days = 30
    }
  }
}

# Secrets Manager for Anthropic API key
resource "aws_secretsmanager_secret" "anthropic_api_key" {
  name        = "openaegis/${var.environment}/anthropic_api_key"
  description = "Anthropic API key for OpenAegis"
  
  tags = {
    Name        = "OpenAegis Anthropic API Key"
    Environment = var.environment
    Project     = "OpenAegis"
  }
}

resource "aws_secretsmanager_secret_version" "anthropic_api_key" {
  secret_id     = aws_secretsmanager_secret.anthropic_api_key.id
  secret_string = jsonencode({
    api_key = "REPLACE_ME_WITH_YOUR_ACTUAL_KEY"
  })
  
  lifecycle {
    ignore_changes = [secret_string]
  }
}

# IAM role for Lambda
resource "aws_iam_role" "lambda_role" {
  name = "openaegis-lambda-role-${var.environment}"
  
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
  
  tags = {
    Name        = "OpenAegis Lambda Role"
    Environment = var.environment
  }
}

resource "aws_iam_role_policy" "lambda_policy" {
  name = "openaegis-lambda-policy"
  role = aws_iam_role.lambda_role.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.quarantine.arn,
          "${aws_s3_bucket.quarantine.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = aws_secretsmanager_secret.anthropic_api_key.arn
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      }
    ]
  })
}

# CloudWatch Log Group
resource "aws_cloudwatch_log_group" "app_logs" {
  name              = "/openaegis/${var.environment}/app"
  retention_in_days = 7
  
  tags = {
    Name        = "OpenAegis Application Logs"
    Environment = var.environment
  }
}

# ECR repository
resource "aws_ecr_repository" "app" {
  name                 = "openaegis-${var.environment}"
  image_tag_mutability = "MUTABLE"
  
  image_scanning_configuration {
    scan_on_push = true
  }
  
  tags = {
    Name        = "OpenAegis App Repository"
    Environment = var.environment
  }
}