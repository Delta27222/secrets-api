#!/bin/bash
# Empaqueta el Lambda Maestro. Lleva 'motor' (binarios) → se compila con Docker
# usando la imagen de AWS Lambda para obtener binarios Linux x86_64 correctos.
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

docker run --rm \
  --entrypoint bash \
  -v "$ROOT/lambda":/var/task \
  -v "$ROOT/terraform":/output \
  public.ecr.aws/lambda/python:3.12 \
  -c "
    set -e
    mkdir -p /tmp/master
    pip install -q -t /tmp/master motor
    cp /var/task/rotation_master.py /tmp/master/
    cd /tmp/master
    python3 - <<'PYEOF'
import os, zipfile
with zipfile.ZipFile('/output/lambda_master.zip', 'w', zipfile.ZIP_DEFLATED) as z:
    for root, _, files in os.walk('.'):
        for f in files:
            z.write(os.path.join(root, f))
PYEOF
  "

echo "✅ lambda_master.zip creado (motor, binarios Linux)"
