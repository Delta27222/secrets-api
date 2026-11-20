# ============================================================================
# Grupo 3 — EC2 MongoDB Replica Set (Primary + Secondary + Arbiter)
#
# Quórum de 3 votos: si falla una AZ completa, las otras dos siguen
# teniendo mayoría y el RS elige nuevo Primary automáticamente.
# El Arbiter vive en private-apps-b (no en subred de datos) a propósito:
# no almacena datos, solo vota.
# ============================================================================

# MongoDB exige --keyFile para autenticación interna entre nodos del RS
# cuando se usa --auth (no hay forma de que --auth sola alcance en un RS).
# Generado por Terraform: nada que pedirle al usuario ni que quede fuera
# del gitignore por accidente.
resource "random_password" "mongodb_keyfile" {
  length  = 500
  special = false
}

resource "aws_instance" "mongodb_primary" {
  ami                         = data.aws_ami.docker.id
  instance_type               = var.mongodb_instance_type
  availability_zone           = "${var.aws_region}a"
  subnet_id                   = aws_subnet.private_data_a.id
  private_ip                  = var.mongodb_primary_ip
  vpc_security_group_ids      = [aws_security_group.mongodb.id]
  associate_public_ip_address = false
  iam_instance_profile        = aws_iam_instance_profile.ec2_data.name

  user_data = base64encode(templatefile("${path.module}/../scripts/mongodb_primary_userdata.sh", {
    mongodb_version    = var.mongodb_version
    mongodb_admin_user = var.mongodb_admin_user
    mongodb_admin_pass = var.mongodb_admin_password
    mongodb_keyfile    = random_password.mongodb_keyfile.result
    replica_set_name   = var.mongodb_replica_set_name
    primary_ip         = var.mongodb_primary_ip
    secondary_ip       = var.mongodb_secondary_ip
    arbiter_ip         = var.mongodb_arbiter_ip
    ecr_registry       = local.ecr_registry
    ecr_repo_mongodb   = aws_ecr_repository.mongodb.name
    aws_region         = var.aws_region
  }))

  root_block_device {
    volume_size           = 20
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
  }

  tags = {
    Name         = "${var.project_name}-mongodb-primary"
    Role         = "mongodb-primary"
    BackupTarget = "true"
  }

  depends_on = [
    aws_vpc_endpoint.ecr_api,
    aws_vpc_endpoint.ecr_dkr,
    aws_vpc_endpoint.s3,
    aws_vpc_endpoint.ssm,
    aws_vpc_endpoint.ssmmessages,
    aws_vpc_endpoint.ec2messages,
    null_resource.mirror_mongodb,
  ]
}

resource "aws_ebs_volume" "mongodb_primary_data" {
  availability_zone = "${var.aws_region}a"
  size              = var.mongodb_data_volume_size
  type              = "gp3"
  encrypted         = true

  tags = {
    Name         = "${var.project_name}-mongodb-primary-data"
    BackupTarget = "true"
  }
}

resource "aws_volume_attachment" "mongodb_primary_data" {
  device_name = "/dev/xvdf"
  volume_id   = aws_ebs_volume.mongodb_primary_data.id
  instance_id = aws_instance.mongodb_primary.id
}

resource "aws_instance" "mongodb_secondary" {
  ami                         = data.aws_ami.docker.id
  instance_type               = var.mongodb_instance_type
  availability_zone           = "${var.aws_region}b"
  subnet_id                   = aws_subnet.private_data_b.id
  private_ip                  = var.mongodb_secondary_ip
  vpc_security_group_ids      = [aws_security_group.mongodb.id]
  associate_public_ip_address = false
  iam_instance_profile        = aws_iam_instance_profile.ec2_data.name

  user_data = base64encode(templatefile("${path.module}/../scripts/mongodb_secondary_userdata.sh", {
    mongodb_version  = var.mongodb_version
    mongodb_keyfile  = random_password.mongodb_keyfile.result
    replica_set_name = var.mongodb_replica_set_name
    ecr_registry     = local.ecr_registry
    ecr_repo_mongodb = aws_ecr_repository.mongodb.name
    aws_region       = var.aws_region
  }))

  root_block_device {
    volume_size           = 20
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
  }

  tags = {
    Name         = "${var.project_name}-mongodb-secondary"
    Role         = "mongodb-secondary"
    BackupTarget = "true"
  }

  depends_on = [
    aws_vpc_endpoint.ecr_api,
    aws_vpc_endpoint.ecr_dkr,
    aws_vpc_endpoint.s3,
    aws_vpc_endpoint.ssm,
    aws_vpc_endpoint.ssmmessages,
    aws_vpc_endpoint.ec2messages,
    null_resource.mirror_mongodb,
  ]
}

resource "aws_ebs_volume" "mongodb_secondary_data" {
  availability_zone = "${var.aws_region}b"
  size              = var.mongodb_data_volume_size
  type              = "gp3"
  encrypted         = true

  tags = {
    Name         = "${var.project_name}-mongodb-secondary-data"
    BackupTarget = "true"
  }
}

resource "aws_volume_attachment" "mongodb_secondary_data" {
  device_name = "/dev/xvdf"
  volume_id   = aws_ebs_volume.mongodb_secondary_data.id
  instance_id = aws_instance.mongodb_secondary.id
}

resource "aws_instance" "mongodb_arbiter" {
  ami                         = data.aws_ami.docker.id
  instance_type               = var.mongodb_arbiter_instance_type
  availability_zone           = "${var.aws_region}b"
  subnet_id                   = aws_subnet.private_b.id
  private_ip                  = var.mongodb_arbiter_ip
  vpc_security_group_ids      = [aws_security_group.mongodb.id]
  associate_public_ip_address = false
  iam_instance_profile        = aws_iam_instance_profile.ec2_data.name

  user_data = base64encode(templatefile("${path.module}/../scripts/mongodb_arbiter_userdata.sh", {
    mongodb_version  = var.mongodb_version
    mongodb_keyfile  = random_password.mongodb_keyfile.result
    replica_set_name = var.mongodb_replica_set_name
    ecr_registry     = local.ecr_registry
    ecr_repo_mongodb = aws_ecr_repository.mongodb.name
    aws_region       = var.aws_region
  }))

  root_block_device {
    volume_size           = 20
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
  }

  tags = {
    Name = "${var.project_name}-mongodb-arbiter"
    Role = "mongodb-arbiter"
  }

  depends_on = [
    aws_vpc_endpoint.ecr_api,
    aws_vpc_endpoint.ecr_dkr,
    aws_vpc_endpoint.s3,
    aws_vpc_endpoint.ssm,
    aws_vpc_endpoint.ssmmessages,
    aws_vpc_endpoint.ec2messages,
    null_resource.mirror_mongodb,
    # Debe arrancar después de primary y secondary para que rs.initiate()
    # del primary pueda incluirlo correctamente desde el principio.
    aws_instance.mongodb_primary,
    aws_instance.mongodb_secondary,
  ]
}
