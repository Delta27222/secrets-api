# ============================================================================
# Grupo 4 — Certificado ACM (dominio propio)
#
# Wildcard, no dos SAN sueltos: cubre app./api. y cualquier subdominio
# futuro con una sola validacion DNS. El dominio vive en GoDaddy (no
# Route53), asi que Terraform NO puede crear el CNAME de validacion solo
# — queda como output (acm_validation_records) para pegar a mano en el
# panel de GoDaddy. aws_acm_certificate_validation se queda esperando
# hasta que ese CNAME propague y AWS valide el certificado.
#
# var.acm_certificate_arn (variable vieja, pre-dominio) sigue soportada
# como fallback manual si alguien prefiere pegar un ARN ya emitido en vez
# de dejar que Terraform gestione el cert — ver local.effective_cert_arn.
# ============================================================================

resource "aws_acm_certificate" "main" {
  count = var.domain_name != "" ? 1 : 0

  domain_name       = "*.${var.domain_name}"
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = { Name = "${var.project_name}-cert" }
}

resource "aws_acm_certificate_validation" "main" {
  count = var.domain_name != "" ? 1 : 0

  certificate_arn         = aws_acm_certificate.main[0].arn
  validation_record_fqdns = [for o in aws_acm_certificate.main[0].domain_validation_options : o.resource_record_name]

  timeouts {
    # 30m se quedaba corto esperando propagación de un CNAME pegado a mano
    # en GoDaddy (sin API, sin forma de saber cuándo el usuario lo agregó).
    create = "45m"
  }
}

locals {
  effective_cert_arn = var.domain_name != "" ? aws_acm_certificate_validation.main[0].certificate_arn : var.acm_certificate_arn

  # Para count/for_each — a diferencia de effective_cert_arn (el ARN en si,
  # que recien se conoce cuando el cert valida), esto es conocido desde
  # plan-time: depende solo de variables, no de un recurso que todavia no
  # existe. count/for_each no aceptan un valor "known after apply".
  want_https = var.domain_name != "" || var.acm_certificate_arn != ""
}
