# ============================================================================
# Grupo 3 — Mirror de imágenes Docker a ECR
#
# Las EC2 de datos no tienen internet: QuestDB y MongoDB deben venir de ECR,
# no de Docker Hub. Antes esto era un paso previo de deploy.sh; aquí vive
# dentro del terraform apply y solo se re-ejecuta si cambia la versión.
#
# El login a ECR va en un null_resource propio, separado del pull/tag/push:
# mirror_questdb y mirror_mongodb corren en paralelo (sin depends_on entre
# ellos) y ambos hacen `docker login` al MISMO registro — si cada script
# intenta loguearse por su cuenta, el helper de credenciales de macOS
# (osxkeychain) choca con "already exists" cuando dos logins concurrentes
# escriben la misma entrada. Loguear una sola vez y que ambos dependan de
# eso elimina la carrera.
# ============================================================================

resource "null_resource" "ecr_login" {
  triggers = {
    registry = local.ecr_registry
  }

  provisioner "local-exec" {
    # docker logout antes: el helper de credenciales de macOS (osxkeychain/desktop)
    # choca con "The specified item already exists in the keychain" si ya queda
    # una entrada de un apply anterior — logout la limpia antes de escribir la nueva.
    command = "docker logout ${local.ecr_registry} >/dev/null 2>&1; aws ecr get-login-password --region ${var.aws_region} | docker login --username AWS --password-stdin ${local.ecr_registry}"
  }
}

resource "null_resource" "mirror_questdb" {
  triggers = {
    version = var.questdb_version
    repo    = aws_ecr_repository.questdb.name
  }

  provisioner "local-exec" {
    command = "${path.module}/../scripts/mirror_db_image.sh ${var.aws_region} ${data.aws_caller_identity.current.account_id} questdb/questdb:${var.questdb_version} ${aws_ecr_repository.questdb.name} ${var.questdb_version}"
  }

  depends_on = [null_resource.ecr_login]
}

resource "null_resource" "mirror_mongodb" {
  triggers = {
    version = var.mongodb_version
    repo    = aws_ecr_repository.mongodb.name
  }

  provisioner "local-exec" {
    command = "${path.module}/../scripts/mirror_db_image.sh ${var.aws_region} ${data.aws_caller_identity.current.account_id} mongo:${var.mongodb_version} ${aws_ecr_repository.mongodb.name} ${var.mongodb_version}"
  }

  depends_on = [null_resource.ecr_login]
}
