#!/bin/bash
# Empaqueta el Lambda Worker. Solo stdlib (urllib, json) → zip directo, sin Docker.
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

rm -f "$ROOT/terraform/lambda_worker.zip"
cd "$ROOT/lambda"
zip -j "$ROOT/terraform/lambda_worker.zip" rotation_worker.py

echo "✅ lambda_worker.zip creado (solo stdlib)"
unzip -l "$ROOT/terraform/lambda_worker.zip"
