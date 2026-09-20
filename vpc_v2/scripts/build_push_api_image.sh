#!/bin/bash
# Invocado por Terraform (null_resource.api_image, local-exec).
# Construye la imagen Docker de la API desde tek-secrets/api/ y la sube a ECR.
#
# Uso: build_push_api_image.sh <region> <account_id> <ecr_repo> <tag> <api_dir>

set -euo pipefail

REGION="$1"
ACCOUNT_ID="$2"
ECR_REPO="$3"
TAG="$4"
API_DIR="$5"

ECR_REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
IMAGE="${ECR_REGISTRY}/${ECR_REPO}:${TAG}"

echo "[INFO] Autenticando en ECR..."
aws ecr get-login-password --region "$REGION" | \
  docker login --username AWS --password-stdin "$ECR_REGISTRY"

echo "[INFO] Construyendo imagen desde $API_DIR..."
docker build --platform linux/amd64 -t "$IMAGE" "$API_DIR"

echo "[INFO] Subiendo $IMAGE..."
docker push "$IMAGE"

echo "[OK] Imagen de la API publicada: $IMAGE"
