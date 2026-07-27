resource "aws_ecr_repository" "custos" {
  name                 = "custos-${var.environment}"
  image_tag_mutability = "MUTABLE"
  force_delete         = true # so `terraform destroy` does not fail on a non-empty repo

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name = "custos-${var.environment}"
  }
}

resource "aws_ecr_lifecycle_policy" "custos" {
  repository = aws_ecr_repository.custos.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 10 images, expire the rest so storage does not grow forever"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}
