#!/bin/bash
# ============================================================================
# Empaqueta el Lambda consumidor (SQS -> QuestDB) en un zip para Terraform.
# pg8000 es Python puro (sin binarios nativos) -> pip install --target sirve
# en cualquier plataforma, sin Docker.
# ============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/lambda/consumer"
BUILD="$ROOT/lambda/consumer/build"
ZIP="$ROOT/terraform/lambda_consumer.zip"

echo "🧹 Limpiando build previo..."
rm -rf "$BUILD" "$ZIP"
mkdir -p "$BUILD"

echo "📦 Instalando dependencias (pg8000)..."
pip install -r "$SRC/requirements.txt" --target "$BUILD" --quiet

echo "📄 Copiando handler..."
cp "$SRC/handler.py" "$BUILD/"

echo "🗜️  Empaquetando zip..."
cd "$BUILD"
zip -r -q "$ZIP" .

echo "✅ lambda_consumer.zip creado"
unzip -l "$ZIP" | tail -5
