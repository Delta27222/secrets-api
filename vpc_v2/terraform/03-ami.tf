# ============================================================================
# Grupo 3 — AMI con Docker preinstalado
#
# Las EC2 de datos no tienen internet, así que Docker debe venir ya
# instalado en la AMI. Antes esto era un script externo (build_ami.sh) que
# corría ANTES del terraform apply y escribía el AMI ID de vuelta en
# terraform.tfvars a mano — la típica fuente de "algo depende de algo que
# todavía se está creando". Aquí vive dentro del mismo apply: null_resource
# construye la AMI (si no existe) y un data source la relee después.
# ============================================================================

locals {
  docker_ami_name = "${var.project_name}-docker-ami"
}

resource "null_resource" "docker_ami_builder" {
  triggers = {
    ami_name = local.docker_ami_name
  }

  provisioner "local-exec" {
    command = "${path.module}/../scripts/build_docker_ami.sh ${var.aws_region} ${local.docker_ami_name} ${aws_subnet.public_a.id}"
  }

  depends_on = [aws_internet_gateway.main, aws_subnet.public_a]
}

data "aws_ami" "docker" {
  most_recent = true
  owners      = ["self"]

  filter {
    name   = "name"
    values = [local.docker_ami_name]
  }

  filter {
    name   = "state"
    values = ["available"]
  }

  depends_on = [null_resource.docker_ami_builder]
}
