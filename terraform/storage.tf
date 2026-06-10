locals {
  name = "${var.project}-${var.environment}"
}

data "aws_caller_identity" "current" {}

# ---------------------------------------------------------------- KMS

resource "aws_kms_key" "ade" {
  description             = "${local.name} encryption key (S3, DynamoDB, SNS, logs)"
  deletion_window_in_days = 14
  enable_key_rotation     = true
}

resource "aws_kms_alias" "ade" {
  name          = "alias/${local.name}"
  target_key_id = aws_kms_key.ade.key_id
}

# ---------------------------------------------------------------- S3

locals {
  buckets = toset(["data-lake", "artifacts", "docs"])
}

resource "aws_s3_bucket" "ade" {
  for_each = local.buckets
  bucket   = "${local.name}-${each.key}-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_versioning" "ade" {
  for_each = aws_s3_bucket.ade
  bucket   = each.value.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "ade" {
  for_each = aws_s3_bucket.ade
  bucket   = each.value.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.ade.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "ade" {
  for_each                = aws_s3_bucket.ade
  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "data_lake" {
  bucket = aws_s3_bucket.ade["data-lake"].id

  rule {
    id     = "quarantine-expiry"
    status = "Enabled"
    filter {
      prefix = "quarantine/"
    }
    expiration {
      days = 90
    }
  }

  rule {
    id     = "raw-to-infrequent-access"
    status = "Enabled"
    filter {
      prefix = "raw/"
    }
    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
    transition {
      days          = 120
      storage_class = "GLACIER_IR"
    }
  }
}

# ---------------------------------------------------------------- DynamoDB

resource "aws_dynamodb_table" "state" {
  name         = "${local.name}-state"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.ade.arn
  }
}
