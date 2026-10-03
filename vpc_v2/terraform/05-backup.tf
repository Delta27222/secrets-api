# ============================================================================
# Grupo 5 — AWS Backup
#
# Snapshots EBS cada 6h, retencion 7 dias (28 puntos de recuperacion), para:
#   - QuestDB Primary (data-a)
#   - MongoDB Primary (data-a)
#   - MongoDB Secondary (data-b)
#
# QuestDB Standby y el Arbiter de Mongo NO se respaldan: el standby restaura
# desde el snapshot del primary en un failover, y el arbiter no tiene datos
# propios del RS. Seleccion por tag (BackupTarget=true) — cualquier volumen
# nuevo con ese tag se respalda automaticamente sin tocar este archivo.
# ============================================================================

resource "aws_backup_vault" "main" {
  name        = "${var.project_name}-backup-vault"
  kms_key_arn = null # null = clave administrada por AWS (aws/backup)

  tags = { Name = "${var.project_name}-backup-vault" }
}

resource "aws_backup_plan" "databases" {
  name = "${var.project_name}-db-backup-plan"

  rule {
    rule_name         = "every-6-hours-7-day-retention"
    target_vault_name = aws_backup_vault.main.name
    schedule          = "cron(0 0/6 * * ? *)"

    start_window      = 60
    completion_window = 180

    lifecycle {
      delete_after = var.backup_retention_days
    }
  }

  tags = { Name = "${var.project_name}-db-backup-plan" }
}

resource "aws_iam_role" "backup" {
  name = "${var.project_name}-backup-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "backup.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Name = "${var.project_name}-backup-role" }
}

resource "aws_iam_role_policy_attachment" "backup" {
  role       = aws_iam_role.backup.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForBackup"
}

resource "aws_iam_role_policy_attachment" "backup_restore" {
  role       = aws_iam_role.backup.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForRestores"
}

resource "aws_backup_selection" "databases" {
  name         = "${var.project_name}-db-backup-selection"
  plan_id      = aws_backup_plan.databases.id
  iam_role_arn = aws_iam_role.backup.arn

  selection_tag {
    type  = "STRINGEQUALS"
    key   = "BackupTarget"
    value = "true"
  }

  depends_on = [aws_iam_role_policy_attachment.backup]
}

resource "aws_cloudwatch_metric_alarm" "backup_failures" {
  alarm_name          = "${var.project_name}-backup-job-failed"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "NumberOfBackupJobsFailed"
  namespace           = "AWS/Backup"
  period              = 86400
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"

  dimensions = { BackupVaultName = aws_backup_vault.main.name }

  alarm_description = "Al menos un job de backup de bases de datos ha fallado en las ultimas 24 horas"
  tags              = { Name = "${var.project_name}-backup-alarm" }
}
