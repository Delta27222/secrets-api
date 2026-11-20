#!/bin/bash
# Invocado por Terraform (null_resource.mirror_*, local-exec).
# Descarga una imagen pública de Docker Hub y la sube al ECR del proyecto —
# las EC2 en subredes de datos no tienen internet, así que deben obtener
# la imagen desde ECR.
#
# Uso: mirror_db_image.sh <region> <account_id> <source_image> <ecr_repo> <tag>

set -euo pipefail

REGION="$1"
ACCOUNT_ID="$2"
SOURCE_IMAGE="$3"
ECR_REPO="$4"
TAG="$5"

ECR_REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
DEST_IMAGE="${ECR_REGISTRY}/${ECR_REPO}:${TAG}"

# El login a ECR corre una sola vez en null_resource.ecr_login (03-mirror.tf) —
# hacerlo aquí también provocaba una carrera en el keychain cuando este
# script corre en paralelo para dos imágenes distintas.

echo "[INFO] Descargando $SOURCE_IMAGE..."
docker pull --platform linux/amd64 "$SOURCE_IMAGE"

docker tag "$SOURCE_IMAGE" "$DEST_IMAGE"

echo "[INFO] Subiendo a $DEST_IMAGE..."
docker push "$DEST_IMAGE"

echo "[OK] Mirror completado: $DEST_IMAGE"
