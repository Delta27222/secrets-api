# ============================================================================
# Grupo 3 — EC2 QuestDB
#
# Primary: private-data-a, IP fija. Standby: private-data-b, se deja STOPPED
# (DR de bajo costo — arranca + restaura snapshot en caso de fallo).
# ============================================================================

resource "aws_instance" "questdb" {
  ami                         = data.aws_ami.docker.id
  instance_type               = var.questdb_instance_type
  availability_zone           = "${var.aws_region}a"
  subnet_id                   = aws_subnet.private_data_a.id
  private_ip                  = var.questdb_primary_ip
  vpc_security_group_ids      = [aws_security_group.questdb.id]
  associate_public_ip_address = false
  iam_instance_profile        = aws_iam_instance_profile.ec2_data.name

  user_data = base64encode(templatefile("${path.module}/../scripts/questdb_userdata.sh", {
    questdb_version     = var.questdb_version
    questdb_pg_password = var.questdb_pg_password
    ecr_registry        = local.ecr_registry
    ecr_repo_questdb    = aws_ecr_repository.questdb.name
    aws_region          = var.aws_region
  }))

  root_block_device {
    volume_size           = 20
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
  }

  tags = {
    Name         = "${var.project_name}-questdb-primary"
    Role         = "questdb-primary"
    BackupTarget = "true"
  }

  depends_on = [
    aws_vpc_endpoint.ecr_api,
    aws_vpc_endpoint.ecr_dkr,
    aws_vpc_endpoint.s3,
    aws_vpc_endpoint.ssm,
    aws_vpc_endpoint.ssmmessages,
    aws_vpc_endpoint.ec2messages,
    null_resource.mirror_questdb,
  ]
}

resource "aws_ebs_volume" "questdb_data" {
  availability_zone = "${var.aws_region}a"
  size              = var.questdb_data_volume_size
  type              = "gp3"
  encrypted         = true

  tags = {
    Name         = "${var.project_name}-questdb-primary-data"
    BackupTarget = "true"
  }
}

resource "aws_volume_attachment" "questdb_data" {
  device_name = "/dev/xvdf"
  volume_id   = aws_ebs_volume.questdb_data.id
  instance_id = aws_instance.questdb.id
}

# ---- Standby (DR): igual configuración, se detiene tras el primer boot ----

resource "aws_instance" "questdb_standby" {
  ami                         = data.aws_ami.docker.id
  instance_type               = var.questdb_instance_type
  availability_zone           = "${var.aws_region}b"
  subnet_id                   = aws_subnet.private_data_b.id
  private_ip                  = var.questdb_standby_ip
  vpc_security_group_ids      = [aws_security_group.questdb.id]
  associate_public_ip_address = false
  iam_instance_profile        = aws_iam_instance_profile.ec2_data.name

  user_data = base64encode(templatefile("${path.module}/../scripts/questdb_userdata.sh", {
    questdb_version     = var.questdb_version
    questdb_pg_password = var.questdb_pg_password
    ecr_registry        = local.ecr_registry
    ecr_repo_questdb    = aws_ecr_repository.questdb.name
    aws_region          = var.aws_region
  }))

  root_block_device {
    volume_size           = 20
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
  }

  tags = {
    Name = "${var.project_name}-questdb-standby"
    Role = "questdb-standby"
  }

  depends_on = [
    aws_vpc_endpoint.ecr_api,
    aws_vpc_endpoint.ecr_dkr,
    aws_vpc_endpoint.s3,
    aws_vpc_endpoint.ssm,
    aws_vpc_endpoint.ssmmessages,
    aws_vpc_endpoint.ec2messages,
    null_resource.mirror_questdb,
  ]
}

resource "aws_ec2_instance_state" "questdb_standby" {
  instance_id = aws_instance.questdb_standby.id
  state       = "stopped"

  depends_on = [aws_instance.questdb_standby]
}

resource "aws_ebs_volume" "questdb_standby_data" {
  availability_zone = "${var.aws_region}b"
  size              = var.questdb_data_volume_size
  type              = "gp3"
  encrypted         = true

  tags = { Name = "${var.project_name}-questdb-standby-data" }
}

resource "aws_volume_attachment" "questdb_standby_data" {
  device_name  = "/dev/xvdf"
  volume_id    = aws_ebs_volume.questdb_standby_data.id
  instance_id  = aws_instance.questdb_standby.id
  force_detach = true

  # Sin esto Terraform intenta el attach mientras la instancia sigue en
  # transición (pending -> stopping) y AWS lo rechaza con IncorrectState.
  depends_on = [aws_ec2_instance_state.questdb_standby]
}
