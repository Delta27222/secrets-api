# ============================================================================
# Grupo 4 — Build + push de la imagen de la API
#
# Antes era el comando separado `deploy.sh image`. Aquí vive dentro del
# mismo terraform apply: el hash del código de tek-secrets/api/ dispara un
# rebuild solo cuando el código cambió, y el redeploy de ECS es automático
# — no hay que acordarse de correr nada aparte tras un cambio de código.
# ============================================================================

locals {
  api_dir = "${path.module}/../../api"
  api_source_hash = sha256(join("", [
    for f in fileset(local.api_dir, "**") : filesha256("${local.api_dir}/${f}")
    if !strcontains(f, "__pycache__") && !strcontains(f, ".venv")
  ]))
}

resource "null_resource" "api_image" {
  triggers = {
    source_hash = local.api_source_hash
    tag         = var.api_image_tag
  }

  provisioner "local-exec" {
    command = "${path.module}/../scripts/build_push_api_image.sh ${var.aws_region} ${data.aws_caller_identity.current.account_id} ${aws_ecr_repository.api.name} ${var.api_image_tag} ${local.api_dir}"
  }
}
