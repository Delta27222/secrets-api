# ============================================================================
# Grupo 4 — Application Load Balancer
# Único punto de entrada desde internet. Sin dominio/cert (tesis): HTTP
# directo en :80. Con acm_certificate_arn: HTTPS en :443 + redirect 80->443.
# ============================================================================

resource "aws_lb" "main" {
  name               = "${var.project_name}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = [aws_subnet.public_a.id, aws_subnet.public_b.id]

  enable_deletion_protection = false

  tags = { Name = "${var.project_name}-alb" }

  # El ALB tiene IPs publicas mapeadas que bloquean el detach del IGW si se
  # destruyen en paralelo — debe irse antes.
  depends_on = [aws_internet_gateway.main]
}

resource "aws_lb_target_group" "api" {
  name        = "${var.project_name}-tg-api"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  health_check {
    enabled             = true
    path                = "/health"
    protocol            = "HTTP"
    port                = "traffic-port"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 10
    interval            = 30
    matcher             = "200"
  }

  deregistration_delay = 30

  tags = { Name = "${var.project_name}-tg-api" }
}

resource "aws_lb_target_group" "front" {
  name        = "${var.project_name}-tg-front"
  port        = 3000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  health_check {
    enabled             = true
    path                = "/"
    protocol            = "HTTP"
    port                = "traffic-port"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 10
    interval            = 30
    # Next.js puede responder con un redirect (ej. a /auth/signin) en la
    # raiz sin sesion — 200-399 evita falsos "unhealthy" por eso.
    matcher = "200-399"
  }

  deregistration_delay = 30

  tags = { Name = "${var.project_name}-tg-front" }
}

resource "aws_lb_listener" "https" {
  count = local.want_https ? 1 : 0

  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = local.effective_cert_arn

  # Sin reglas de host (ver mas abajo), el default sigue siendo la API —
  # asi ALB DNS name pelado (sin dominio) mantiene el comportamiento de
  # antes.
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  tags = { Name = "${var.project_name}-listener-https" }
}

# Host-based routing — solo tiene sentido con dominio propio configurado.
resource "aws_lb_listener_rule" "front_host" {
  count = var.domain_name != "" ? 1 : 0

  listener_arn = aws_lb_listener.https[0].arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.front.arn
  }

  condition {
    host_header {
      values = ["app.${var.domain_name}"]
    }
  }

  tags = { Name = "${var.project_name}-rule-front" }
}

resource "aws_lb_listener_rule" "api_host" {
  count = var.domain_name != "" ? 1 : 0

  listener_arn = aws_lb_listener.https[0].arn
  priority     = 20

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  condition {
    host_header {
      values = ["api.${var.domain_name}"]
    }
  }

  tags = { Name = "${var.project_name}-rule-api" }
}

resource "aws_lb_listener" "http_redirect" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = local.want_https ? "redirect" : "forward"

    dynamic "redirect" {
      for_each = local.want_https ? [1] : []
      content {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }

    dynamic "forward" {
      for_each = local.want_https ? [] : [1]
      content {
        target_group {
          arn = aws_lb_target_group.api.arn
        }
      }
    }
  }

  tags = { Name = "${var.project_name}-listener-http" }
}

resource "aws_cloudwatch_metric_alarm" "alb_5xx_errors" {
  alarm_name          = "${var.project_name}-alb-5xx-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HTTPCode_ELB_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Sum"
  threshold           = 10
  treat_missing_data  = "notBreaching"

  dimensions        = { LoadBalancer = aws_lb.main.arn_suffix }
  alarm_description = "Mas de 10 errores 5XX del ALB en 1 minuto"
  tags              = { Name = "${var.project_name}-alb-5xx-alarm" }
}
