# Cost consequence of the choice below, priced at AWS list price, verify before
# quoting a customer:
#   enable_egress = true   one NAT gateway, about $0.045/hour plus data processing.
#   enable_egress = false  no NAT gateway, but four VPC interface/gateway endpoints,
#                          about $0.01/hour each for the interface endpoints.
# The no-egress path is not a premium option bought for security. It costs the
# same money, or slightly less, while removing the service's ability to reach
# the public internet at all. That said, enable_egress = false is CURRENTLY
# BLOCKED at plan time for every llm_provider -- see egress_provider_guard in
# guard.tf and deploy/PREREQUISITES.md -- because the Qdrant sidecar added to
# ecs.tf is pulled from Docker Hub and needs a route out. The count = 0/1
# toggles below still exist and describe what this network would look like if
# that gap is closed; they are not currently reachable in a successful plan.

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  az_a = data.aws_availability_zones.available.names[0]
  az_b = data.aws_availability_zones.available.names[1]
}

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "custos-${var.environment}-vpc"
  }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "custos-${var.environment}-igw"
  }
}

# --- Public subnets, one per AZ. The ALB lives here. ---

resource "aws_subnet" "public_a" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 4, 0)
  availability_zone       = local.az_a
  map_public_ip_on_launch = true

  tags = {
    Name = "custos-${var.environment}-public-a"
  }
}

resource "aws_subnet" "public_b" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 4, 1)
  availability_zone       = local.az_b
  map_public_ip_on_launch = true

  tags = {
    Name = "custos-${var.environment}-public-b"
  }
}

# --- Private subnets, one per AZ. ECS tasks live here, never a public IP. ---

resource "aws_subnet" "private_a" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 4, 2)
  availability_zone = local.az_a

  tags = {
    Name = "custos-${var.environment}-private-a"
  }
}

resource "aws_subnet" "private_b" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 4, 3)
  availability_zone = local.az_b

  tags = {
    Name = "custos-${var.environment}-private-b"
  }
}

# --- Public route table, always the same regardless of egress mode. ---

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "custos-${var.environment}-public-rt"
  }
}

resource "aws_route_table_association" "public_a" {
  subnet_id      = aws_subnet.public_a.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "public_b" {
  subnet_id      = aws_subnet.public_b.id
  route_table_id = aws_route_table.public.id
}

# --- Private route table. Content of its default route depends on enable_egress. ---

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "custos-${var.environment}-private-rt"
  }
}

resource "aws_route_table_association" "private_a" {
  subnet_id      = aws_subnet.private_a.id
  route_table_id = aws_route_table.private.id
}

resource "aws_route_table_association" "private_b" {
  subnet_id      = aws_subnet.private_b.id
  route_table_id = aws_route_table.private.id
}

# --- Egress path: NAT gateway, only created when enable_egress = true. ---

resource "aws_eip" "nat" {
  count  = var.enable_egress ? 1 : 0
  domain = "vpc"

  tags = {
    Name = "custos-${var.environment}-nat-eip"
  }
}

resource "aws_nat_gateway" "main" {
  count         = var.enable_egress ? 1 : 0
  allocation_id = aws_eip.nat[0].id
  subnet_id     = aws_subnet.public_a.id

  tags = {
    Name = "custos-${var.environment}-nat"
  }

  depends_on = [aws_internet_gateway.main]
}

resource "aws_route" "private_egress" {
  count                  = var.enable_egress ? 1 : 0
  route_table_id         = aws_route_table.private.id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.main[0].id
}

# --- No-egress path: VPC endpoints, only created when enable_egress = false. ---
# With no NAT gateway and no default route, the private subnets have zero path
# to the public internet. Everything the ECS service needs at runtime, pulling
# its image and writing logs and reading its secret, has to be reachable over
# these endpoints instead.

resource "aws_vpc_endpoint" "ecr_api" {
  count               = var.enable_egress ? 0 : 1
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.region}.ecr.api"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.private_a.id, aws_subnet.private_b.id]
  security_group_ids  = [aws_security_group.vpc_endpoints[0].id]
  private_dns_enabled = true

  tags = {
    Name = "custos-${var.environment}-ecr-api-endpoint"
  }
}

resource "aws_vpc_endpoint" "ecr_dkr" {
  count               = var.enable_egress ? 0 : 1
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.region}.ecr.dkr"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.private_a.id, aws_subnet.private_b.id]
  security_group_ids  = [aws_security_group.vpc_endpoints[0].id]
  private_dns_enabled = true

  tags = {
    Name = "custos-${var.environment}-ecr-dkr-endpoint"
  }
}

resource "aws_vpc_endpoint" "logs" {
  count               = var.enable_egress ? 0 : 1
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.region}.logs"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.private_a.id, aws_subnet.private_b.id]
  security_group_ids  = [aws_security_group.vpc_endpoints[0].id]
  private_dns_enabled = true

  tags = {
    Name = "custos-${var.environment}-logs-endpoint"
  }
}

# Only needed to read the LLM API key secret, so it is also skipped in
# Bedrock mode: that mode has no Secrets Manager secret at all (see
# secrets.tf), so an endpoint to reach it would be dead infrastructure.
resource "aws_vpc_endpoint" "secretsmanager" {
  count               = (var.enable_egress == false && var.llm_provider != "bedrock") ? 1 : 0
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.region}.secretsmanager"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.private_a.id, aws_subnet.private_b.id]
  security_group_ids  = [aws_security_group.vpc_endpoints[0].id]
  private_dns_enabled = true

  tags = {
    Name = "custos-${var.environment}-secretsmanager-endpoint"
  }
}

# bedrock-runtime is the inference API the application actually calls, not
# to be confused with the plain "bedrock" endpoint (model listing/management,
# control plane only). Needed whenever there is no NAT gateway, regardless of
# llm_provider, so switching llm_provider to "bedrock" later never requires
# re-planning the network.
resource "aws_vpc_endpoint" "bedrock_runtime" {
  count               = var.enable_egress ? 0 : 1
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.region}.bedrock-runtime"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.private_a.id, aws_subnet.private_b.id]
  security_group_ids  = [aws_security_group.vpc_endpoints[0].id]
  private_dns_enabled = true

  tags = {
    Name = "custos-${var.environment}-bedrock-runtime-endpoint"
  }
}

# The S3 gateway endpoint is not optional. ECR stores image layers in S3, so
# pulling the container image fails without it, even though the pull request
# itself goes to the ecr.dkr endpoint above. This is the gotcha that costs
# people an afternoon of "why is my task stuck in PENDING with no useful error."
resource "aws_vpc_endpoint" "s3" {
  count             = var.enable_egress ? 0 : 1
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]

  tags = {
    Name = "custos-${var.environment}-s3-endpoint"
  }
}
