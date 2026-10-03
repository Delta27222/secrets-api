# ============================================================================
# Grupo 2 — Seguridad (Security Groups + NACLs)
#
# Defensa en 2 capas:
#   1. NACL (stateless, nivel subred)   — perímetro
#   2. Security Group (stateful, nivel recurso) — control granular
#
# Reglas cross-SG viven como aws_security_group_rule aparte para evitar
# ciclos de dependencia entre los SGs que se referencian mutuamente.
# ============================================================================

data "aws_prefix_list" "s3" {
  name = "com.amazonaws.${var.aws_region}.s3"
}

# ---- Security Groups ----
#
# Sin bloques ingress/egress inline: TODAS las reglas viven como
# aws_security_group_rule aparte (ver abajo). Mezclar inline con reglas
# separadas para el mismo SG hace que el provider vea las reglas separadas
# como drift y trate de borrarlas en cada plan — justo lo que pasaba en el
# diseño original.

resource "aws_security_group" "alb" {
  name        = "${var.project_name}-sg-alb"
  description = "ALB: acepta HTTPS/HTTP desde internet, envia al puerto 8000 de ECS"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${var.project_name}-sg-alb" }
}

resource "aws_security_group" "ecs" {
  name        = "${var.project_name}-sg-ecs"
  description = "ECS tasks (api + front): acepta del ALB en :8000/:3000, Service Connect interno en :8000, sale a QuestDB, MongoDB y servicios AWS"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${var.project_name}-sg-ecs" }
}

resource "aws_security_group" "questdb" {
  name        = "${var.project_name}-sg-questdb"
  description = "QuestDB: :9000 desde ECS, :8812 desde Lambda. Solo acceso interno."
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${var.project_name}-sg-questdb" }
}

resource "aws_security_group" "mongodb" {
  name        = "${var.project_name}-sg-mongodb"
  description = "MongoDB RS: :27017 desde ECS, replicacion interna entre nodos. Sin acceso externo."
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${var.project_name}-sg-mongodb" }
}

resource "aws_security_group" "lambda" {
  name        = "${var.project_name}-sg-lambda"
  description = "Lambdas en VPC: salen a QuestDB PG-wire, MongoDB, SQS y API"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${var.project_name}-sg-lambda" }
}

resource "aws_security_group" "vpc_endpoints" {
  name        = "${var.project_name}-sg-endpoints"
  description = "VPC Interface Endpoints: acepta HTTPS desde ECS, Lambda y EC2 de datos"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${var.project_name}-sg-endpoints" }
}

# ---- Reglas propias de cada SG (antes inline, ahora separadas) ----

resource "aws_security_group_rule" "alb_ingress_https" {
  type              = "ingress"
  security_group_id = aws_security_group.alb.id
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  description       = "HTTPS desde internet"
}

resource "aws_security_group_rule" "alb_ingress_http" {
  type              = "ingress"
  security_group_id = aws_security_group.alb.id
  from_port         = 80
  to_port           = 80
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  description       = "HTTP desde internet (redirige a HTTPS)"
}

resource "aws_security_group_rule" "ecs_egress_internet" {
  type              = "egress"
  security_group_id = aws_security_group.ecs.id
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  description       = "Salida HTTPS hacia internet via NAT Gateway"
}

resource "aws_security_group_rule" "questdb_egress_vpc" {
  type              = "egress"
  security_group_id = aws_security_group.questdb.id
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = [var.vpc_cidr]
  description       = "Respuestas dentro de la VPC"
}

resource "aws_security_group_rule" "questdb_egress_s3" {
  type              = "egress"
  security_group_id = aws_security_group.questdb.id
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  prefix_list_ids   = [data.aws_prefix_list.s3.id]
  description       = "HTTPS a S3 via VPC Gateway Endpoint (capas de imagen ECR)"
}

resource "aws_security_group_rule" "mongodb_ingress_replication" {
  type              = "ingress"
  security_group_id = aws_security_group.mongodb.id
  from_port         = 27017
  to_port           = 27017
  protocol          = "tcp"
  self              = true
  description       = "Replicacion MongoDB entre nodos del RS (data-a, data-b, apps-b)"
}

resource "aws_security_group_rule" "mongodb_egress_vpc" {
  type              = "egress"
  security_group_id = aws_security_group.mongodb.id
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = [var.vpc_cidr]
  description       = "Salida dentro de la VPC (replicacion y respuestas)"
}

resource "aws_security_group_rule" "mongodb_egress_s3" {
  type              = "egress"
  security_group_id = aws_security_group.mongodb.id
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  prefix_list_ids   = [data.aws_prefix_list.s3.id]
  description       = "HTTPS a S3 via VPC Gateway Endpoint (capas de imagen ECR)"
}

resource "aws_security_group_rule" "lambda_egress_internet" {
  type              = "egress"
  security_group_id = aws_security_group.lambda.id
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  description       = "HTTPS hacia servicios AWS (SQS, VPC Endpoints) y API via NAT"
}

resource "aws_security_group_rule" "endpoints_ingress_cidrs" {
  type              = "ingress"
  security_group_id = aws_security_group.vpc_endpoints.id
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks = [
    var.subnet_private_data_a_cidr,
    var.subnet_private_data_b_cidr,
    var.subnet_private_a_cidr,
    var.subnet_private_b_cidr,
  ]
  description = "HTTPS desde EC2, ECS y Lambda en subredes de datos y apps"
}

resource "aws_security_group_rule" "endpoints_egress_vpc" {
  type              = "egress"
  security_group_id = aws_security_group.vpc_endpoints.id
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = [var.vpc_cidr]
}

# ---- Reglas cross-SG (separadas para evitar ciclos) ----

resource "aws_security_group_rule" "alb_egress_to_ecs" {
  type                     = "egress"
  security_group_id        = aws_security_group.alb.id
  from_port                = 8000
  to_port                  = 8000
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.ecs.id
  description              = "Health checks y trafico hacia contenedores ECS"
}

resource "aws_security_group_rule" "ecs_ingress_from_alb" {
  type                     = "ingress"
  security_group_id        = aws_security_group.ecs.id
  from_port                = 8000
  to_port                  = 8000
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.alb.id
  description              = "Trafico de la API desde el ALB"
}

resource "aws_security_group_rule" "alb_egress_to_front" {
  type                     = "egress"
  security_group_id        = aws_security_group.alb.id
  from_port                = 3000
  to_port                  = 3000
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.ecs.id
  description              = "Health checks y trafico hacia el front (Next.js)"
}

resource "aws_security_group_rule" "ecs_ingress_from_alb_front" {
  type                     = "ingress"
  security_group_id        = aws_security_group.ecs.id
  from_port                = 3000
  to_port                  = 3000
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.alb.id
  description              = "Trafico del front desde el ALB"
}

# Front y api comparten este SG (ambos son "ECS tasks en subred privada de
# apps"). Self-referencing en vez de una regla cross-SG: cualquier task del
# SG puede llamar a cualquier otra en :8000 — cubre front -> api via
# Service Connect sin exponer nada mas.
resource "aws_security_group_rule" "ecs_ingress_self_service_connect" {
  type              = "ingress"
  security_group_id = aws_security_group.ecs.id
  from_port         = 8000
  to_port           = 8000
  protocol          = "tcp"
  self              = true
  description       = "Service Connect: front a api, interno, sin pasar por el ALB"
}

# Contraparte de salida: sin esta regla el proxy de Service Connect del front
# no puede abrir conexion a la api (el egress del SG no es abierto) y el
# front recibe ECONNRESET en toda llamada a http://api:8000.
resource "aws_security_group_rule" "ecs_egress_self_service_connect" {
  type              = "egress"
  security_group_id = aws_security_group.ecs.id
  from_port         = 8000
  to_port           = 8000
  protocol          = "tcp"
  self              = true
  description       = "Service Connect: front a api, interno, sin pasar por el ALB"
}

resource "aws_security_group_rule" "ecs_egress_to_questdb" {
  type                     = "egress"
  security_group_id        = aws_security_group.ecs.id
  from_port                = 9000
  to_port                  = 9000
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.questdb.id
  description              = "Consultas REST a QuestDB (ingesta de logs de auditoria)"
}

resource "aws_security_group_rule" "questdb_ingress_from_ecs" {
  type                     = "ingress"
  security_group_id        = aws_security_group.questdb.id
  from_port                = 9000
  to_port                  = 9000
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.ecs.id
  description              = "QuestDB REST + consola web - SOLO desde contenedores ECS"
}

resource "aws_security_group_rule" "ecs_egress_to_mongodb" {
  type                     = "egress"
  security_group_id        = aws_security_group.ecs.id
  from_port                = 27017
  to_port                  = 27017
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.mongodb.id
  description              = "Conexion a MongoDB Replica Set (datos de la aplicacion)"
}

resource "aws_security_group_rule" "mongodb_ingress_from_ecs" {
  type                     = "ingress"
  security_group_id        = aws_security_group.mongodb.id
  from_port                = 27017
  to_port                  = 27017
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.ecs.id
  description              = "Conexiones de la API (ECS) a MongoDB"
}

resource "aws_security_group_rule" "lambda_egress_to_questdb" {
  type                     = "egress"
  security_group_id        = aws_security_group.lambda.id
  from_port                = 8812
  to_port                  = 8812
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.questdb.id
  description              = "QuestDB Postgres-wire (ingesta de logs de auditoria)"
}

resource "aws_security_group_rule" "questdb_ingress_from_lambda" {
  type                     = "ingress"
  security_group_id        = aws_security_group.questdb.id
  from_port                = 8812
  to_port                  = 8812
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.lambda.id
  description              = "QuestDB Postgres-wire - SOLO desde Lambdas (ingesta de logs)"
}

resource "aws_security_group_rule" "lambda_egress_to_mongodb" {
  type                     = "egress"
  security_group_id        = aws_security_group.lambda.id
  from_port                = 27017
  to_port                  = 27017
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.mongodb.id
  description              = "MongoDB (rotation-master consulta llaves activas)"
}

resource "aws_security_group_rule" "mongodb_ingress_from_lambda" {
  type                     = "ingress"
  security_group_id        = aws_security_group.mongodb.id
  from_port                = 27017
  to_port                  = 27017
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.lambda.id
  description              = "Conexiones de la Lambda rotation-master a MongoDB"
}

resource "aws_security_group_rule" "endpoints_ingress_from_ecs" {
  type                     = "ingress"
  security_group_id        = aws_security_group.vpc_endpoints.id
  from_port                = 443
  to_port                  = 443
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.ecs.id
  description              = "HTTPS desde contenedores ECS"
}

resource "aws_security_group_rule" "endpoints_ingress_from_lambda" {
  type                     = "ingress"
  security_group_id        = aws_security_group.vpc_endpoints.id
  from_port                = 443
  to_port                  = 443
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.lambda.id
  description              = "HTTPS desde Lambdas en VPC"
}

# ============================================================================
# NACLs — listas de reglas como locals + dynamic block (evita ~50 recursos
# aws_network_acl_rule sueltos; una sola NACL por tier con sus reglas inline).
# ============================================================================

locals {
  nacl_public_ingress = [
    { rule_number = 100, protocol = "tcp", cidr_block = "0.0.0.0/0", from_port = 443, to_port = 443 },
    { rule_number = 110, protocol = "tcp", cidr_block = "0.0.0.0/0", from_port = 80, to_port = 80 },
    { rule_number = 120, protocol = "tcp", cidr_block = "0.0.0.0/0", from_port = 1024, to_port = 65535 },
  ]
  nacl_public_egress = [
    { rule_number = 100, protocol = "tcp", cidr_block = var.subnet_private_a_cidr, from_port = 8000, to_port = 8000 },
    { rule_number = 110, protocol = "tcp", cidr_block = var.subnet_private_b_cidr, from_port = 8000, to_port = 8000 },
    { rule_number = 120, protocol = "tcp", cidr_block = "0.0.0.0/0", from_port = 443, to_port = 443 },
    { rule_number = 130, protocol = "tcp", cidr_block = "0.0.0.0/0", from_port = 1024, to_port = 65535 },
    # ALB -> front (Next.js), mismo esquema que el 8000 de arriba pero 3000.
    { rule_number = 135, protocol = "tcp", cidr_block = var.subnet_private_a_cidr, from_port = 3000, to_port = 3000 },
    { rule_number = 136, protocol = "tcp", cidr_block = var.subnet_private_b_cidr, from_port = 3000, to_port = 3000 },
  ]

  nacl_private_apps_ingress = [
    { rule_number = 100, protocol = "tcp", cidr_block = var.subnet_public_a_cidr, from_port = 8000, to_port = 8000 },
    { rule_number = 110, protocol = "tcp", cidr_block = var.subnet_public_b_cidr, from_port = 8000, to_port = 8000 },
    { rule_number = 120, protocol = "tcp", cidr_block = var.subnet_private_data_a_cidr, from_port = 27017, to_port = 27017 },
    { rule_number = 130, protocol = "tcp", cidr_block = var.subnet_private_data_b_cidr, from_port = 27017, to_port = 27017 },
    { rule_number = 140, protocol = "tcp", cidr_block = "0.0.0.0/0", from_port = 1024, to_port = 65535 },
    { rule_number = 143, protocol = "tcp", cidr_block = var.subnet_private_data_a_cidr, from_port = 443, to_port = 443 },
    { rule_number = 144, protocol = "tcp", cidr_block = var.subnet_private_data_b_cidr, from_port = 443, to_port = 443 },
    # Los VPC Endpoints (ECR, SSM, etc.) tienen su ENI DENTRO de las subredes
    # de apps (una por AZ). Sin esta regla, nada en apps-a/apps-b puede
    # llegar al endpoint de su propia subred ni al de la otra AZ — ECS,
    # Lambda y el Arbiter de Mongo (en apps-b) se quedan sin ECR ni SSM.
    { rule_number = 145, protocol = "tcp", cidr_block = var.subnet_private_a_cidr, from_port = 443, to_port = 443 },
    { rule_number = 146, protocol = "tcp", cidr_block = var.subnet_private_b_cidr, from_port = 443, to_port = 443 },
    # ALB -> front (Next.js) en :3000.
    { rule_number = 150, protocol = "tcp", cidr_block = var.subnet_public_a_cidr, from_port = 3000, to_port = 3000 },
    { rule_number = 151, protocol = "tcp", cidr_block = var.subnet_public_b_cidr, from_port = 3000, to_port = 3000 },
    # Service Connect: front llama a api en :8000 sin pasar por el ALB.
    # Front y api viven en el mismo tier (private-apps), asi que la NACL
    # compartida necesita permitir el trafico entre sus propias subredes.
    { rule_number = 155, protocol = "tcp", cidr_block = var.subnet_private_a_cidr, from_port = 8000, to_port = 8000 },
    { rule_number = 156, protocol = "tcp", cidr_block = var.subnet_private_b_cidr, from_port = 8000, to_port = 8000 },
  ]
  nacl_private_apps_egress = [
    { rule_number = 100, protocol = "tcp", cidr_block = "0.0.0.0/0", from_port = 443, to_port = 443 },
    { rule_number = 110, protocol = "tcp", cidr_block = var.subnet_private_data_a_cidr, from_port = 9000, to_port = 9000 },
    { rule_number = 120, protocol = "tcp", cidr_block = var.subnet_private_data_a_cidr, from_port = 8812, to_port = 8812 },
    { rule_number = 130, protocol = "tcp", cidr_block = var.subnet_private_data_a_cidr, from_port = 27017, to_port = 27017 },
    { rule_number = 140, protocol = "tcp", cidr_block = var.subnet_private_data_b_cidr, from_port = 27017, to_port = 27017 },
    { rule_number = 150, protocol = "tcp", cidr_block = var.subnet_public_a_cidr, from_port = 1024, to_port = 65535 },
    { rule_number = 160, protocol = "tcp", cidr_block = var.subnet_public_b_cidr, from_port = 1024, to_port = 65535 },
    { rule_number = 165, protocol = "tcp", cidr_block = var.subnet_private_data_a_cidr, from_port = 1024, to_port = 65535 },
    { rule_number = 170, protocol = "tcp", cidr_block = var.subnet_private_data_b_cidr, from_port = 1024, to_port = 65535 },
    # Respuesta de los VPC Endpoints (ECR, SSM, etc. — ENI en apps-a/apps-b)
    # hacia quien los llamó DESDE la propia subred de apps (ECS, Lambda, el
    # Arbiter de Mongo). Sin esto, la respuesta HTTPS se cae en el deny-all
    # final aunque el ingress ya esté permitido — exactamente lo que hacía
    # fallar el pull de ECR y colgar los comandos SSM del Arbiter.
    { rule_number = 171, protocol = "tcp", cidr_block = var.subnet_private_a_cidr, from_port = 1024, to_port = 65535 },
    { rule_number = 172, protocol = "tcp", cidr_block = var.subnet_private_b_cidr, from_port = 1024, to_port = 65535 },
    # Service Connect: front necesita SALIR hacia api en :8000 (misma
    # razon que el ingress 155/156 de arriba — comparten NACL).
    { rule_number = 175, protocol = "tcp", cidr_block = var.subnet_private_a_cidr, from_port = 8000, to_port = 8000 },
    { rule_number = 176, protocol = "tcp", cidr_block = var.subnet_private_b_cidr, from_port = 8000, to_port = 8000 },
  ]

  nacl_private_data_ingress = [
    { rule_number = 100, protocol = "tcp", cidr_block = var.subnet_private_a_cidr, from_port = 9000, to_port = 9000 },
    { rule_number = 110, protocol = "tcp", cidr_block = var.subnet_private_b_cidr, from_port = 9000, to_port = 9000 },
    { rule_number = 120, protocol = "tcp", cidr_block = var.subnet_private_a_cidr, from_port = 8812, to_port = 8812 },
    { rule_number = 130, protocol = "tcp", cidr_block = var.subnet_private_b_cidr, from_port = 8812, to_port = 8812 },
    { rule_number = 140, protocol = "tcp", cidr_block = var.subnet_private_a_cidr, from_port = 27017, to_port = 27017 },
    { rule_number = 150, protocol = "tcp", cidr_block = var.subnet_private_b_cidr, from_port = 27017, to_port = 27017 },
    { rule_number = 160, protocol = "tcp", cidr_block = var.subnet_private_data_a_cidr, from_port = 27017, to_port = 27017 },
    { rule_number = 170, protocol = "tcp", cidr_block = var.subnet_private_data_b_cidr, from_port = 27017, to_port = 27017 },
    { rule_number = 175, protocol = "tcp", cidr_block = "0.0.0.0/0", from_port = 1024, to_port = 65535 },
    { rule_number = 180, protocol = "tcp", cidr_block = var.vpc_cidr, from_port = 1024, to_port = 65535 },
  ]
  nacl_private_data_egress = [
    { rule_number = 100, protocol = "tcp", cidr_block = "0.0.0.0/0", from_port = 443, to_port = 443 },
    { rule_number = 110, protocol = "tcp", cidr_block = var.vpc_cidr, from_port = 27017, to_port = 27017 },
    { rule_number = 120, protocol = "tcp", cidr_block = var.vpc_cidr, from_port = 1024, to_port = 65535 },
  ]
}

resource "aws_network_acl" "public" {
  vpc_id     = aws_vpc.main.id
  subnet_ids = [aws_subnet.public_a.id, aws_subnet.public_b.id]

  dynamic "ingress" {
    for_each = local.nacl_public_ingress
    content {
      rule_no    = ingress.value.rule_number
      protocol   = ingress.value.protocol
      action     = "allow"
      cidr_block = ingress.value.cidr_block
      from_port  = ingress.value.from_port
      to_port    = ingress.value.to_port
    }
  }

  dynamic "egress" {
    for_each = local.nacl_public_egress
    content {
      rule_no    = egress.value.rule_number
      protocol   = egress.value.protocol
      action     = "allow"
      cidr_block = egress.value.cidr_block
      from_port  = egress.value.from_port
      to_port    = egress.value.to_port
    }
  }

  tags = { Name = "${var.project_name}-nacl-public" }
}

resource "aws_network_acl" "private_apps" {
  vpc_id     = aws_vpc.main.id
  subnet_ids = [aws_subnet.private_a.id, aws_subnet.private_b.id]

  dynamic "ingress" {
    for_each = local.nacl_private_apps_ingress
    content {
      rule_no    = ingress.value.rule_number
      protocol   = ingress.value.protocol
      action     = "allow"
      cidr_block = ingress.value.cidr_block
      from_port  = ingress.value.from_port
      to_port    = ingress.value.to_port
    }
  }

  dynamic "egress" {
    for_each = local.nacl_private_apps_egress
    content {
      rule_no    = egress.value.rule_number
      protocol   = egress.value.protocol
      action     = "allow"
      cidr_block = egress.value.cidr_block
      from_port  = egress.value.from_port
      to_port    = egress.value.to_port
    }
  }

  tags = { Name = "${var.project_name}-nacl-private-apps" }
}

resource "aws_network_acl" "private_data" {
  vpc_id     = aws_vpc.main.id
  subnet_ids = [aws_subnet.private_data_a.id, aws_subnet.private_data_b.id]

  dynamic "ingress" {
    for_each = local.nacl_private_data_ingress
    content {
      rule_no    = ingress.value.rule_number
      protocol   = ingress.value.protocol
      action     = "allow"
      cidr_block = ingress.value.cidr_block
      from_port  = ingress.value.from_port
      to_port    = ingress.value.to_port
    }
  }

  dynamic "egress" {
    for_each = local.nacl_private_data_egress
    content {
      rule_no    = egress.value.rule_number
      protocol   = egress.value.protocol
      action     = "allow"
      cidr_block = egress.value.cidr_block
      from_port  = egress.value.from_port
      to_port    = egress.value.to_port
    }
  }

  tags = { Name = "${var.project_name}-nacl-private-data" }
}
