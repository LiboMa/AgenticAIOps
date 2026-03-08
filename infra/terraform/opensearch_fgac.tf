# OpenSearch os2 Domain - FGAC Configuration
# This configures the existing os2 domain's Fine-Grained Access Control
# to use IAM role as master user instead of internal user database.

# Note: This is a config-only resource for an existing domain.
# The os2 domain itself was created outside Terraform.

resource "aws_opensearch_domain" "os2_fgac_config" {
  domain_name    = "os2"
  engine_version = "OpenSearch_2.17"

  advanced_security_options {
    enabled                        = true
    internal_user_database_enabled = false
    master_user_options {
      master_user_arn = "arn:aws:iam::533267047935:role/iam-mbot-role"
    }
  }

  # Note: Import existing domain before applying:
  # terraform import aws_opensearch_domain.os2_fgac_config os2
}
