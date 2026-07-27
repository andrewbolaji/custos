provider "aws" {
  region  = var.region
  profile = var.aws_profile

  # default_tags applies to every resource this module creates, without anyone
  # having to remember to tag each one by hand. That is what makes cost in this
  # account traceable back to this deployment months later, when nobody
  # remembers what "custos" was for.
  default_tags {
    tags = {
      Project     = "custos"
      Environment = var.environment
      ManagedBy   = "terraform"
      Owner       = var.owner_tag
    }
  }
}
