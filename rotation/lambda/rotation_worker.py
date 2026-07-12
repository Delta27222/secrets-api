"""
Lambda Worker: Dispara rotación vía API (CSFLE-native).

Función: Consume mensajes de SQS y llama al endpoint de rotación de la API.
Ejecutado por: SQS trigger (asincrónico)
Timeout: 900 segundos (15 minutos)
Memory: 256 MB (ya no procesa localmente, solo HTTP)

Arquitectura:
  SQS (project_id) → Lambda Worker → HTTP POST → API en Render (con CSFLE)
  La API genera llave, rota y re-encripta TODOS los secretos usando su CSFLE nativo.

Por qué así:
  CSFLE requiere pymongocrypt (binario compilado) que NO corre en Lambda.
  La API en Render (Linux + Python 3.12) SÍ tiene pymongocrypt.
  Por eso el Lambda delega toda la lógica criptográfica a la API.

Variables de entorno:
  API_BASE_URL        - URL base de la API (ej: https://tek-secrets-api.onrender.com)
  ROTATION_API_TOKEN  - Service token de sistema (tok_...) con scope keys:rotate.
                        Se envía como header Authorization: Bearer tok_...

Logs: CloudWatch /aws/lambda/rotation_worker
Reintentos: SQS default (3 intentos), después → DLQ
"""

import json
import os
import logging
import urllib.request
import urllib.error

# Configurar logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
API_BASE_URL = os.getenv("API_BASE_URL", "").rstrip("/")
ROTATION_API_TOKEN = os.getenv("ROTATION_API_TOKEN", "")

# Timeout para la llamada HTTP (segundos). La rotación puede tardar con muchos secretos.
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "300"))


def rotate_project_via_api(project_id: str) -> dict:
    """
    Llama al endpoint de rotación de la API para un proyecto.

    Args:
        project_id: ID del proyecto a rotar

    Returns:
        Dict con el resultado que devuelve la API

    Raises:
        Exception: Si la API responde con error (para que SQS reintente)
    """
    if not API_BASE_URL:
        raise ValueError("API_BASE_URL no configurada en variables de entorno")
    if not ROTATION_API_TOKEN:
        raise ValueError("ROTATION_API_TOKEN no configurado en variables de entorno")

    url = f"{API_BASE_URL}/v1/internal/projects/{project_id}/rotate-encryption"

    req = urllib.request.Request(
        url,
        data=b"",  # POST sin body
        method="POST",
        headers={
            "Authorization": f"Bearer {ROTATION_API_TOKEN}",
            "Content-Type": "application/json",
        },
    )

    logger.info(f"📡 POST {url}")

    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            body = resp.read().decode()
            result = json.loads(body)
            logger.info(f"✅ API respondió {resp.status}: {json.dumps(result)}")
            return result

    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        logger.error(f"❌ API error HTTP {e.code}: {error_body}")
        raise Exception(f"API rotación falló (HTTP {e.code}): {error_body}")

    except urllib.error.URLError as e:
        logger.error(f"❌ Error de conexión con API: {e.reason}")
        raise Exception(f"No se pudo conectar a la API: {e.reason}")


def lambda_handler(event, context):
    """Handler de Lambda - consume SQS, llama a la API por cada proyecto."""
    logger.info("🚀 Inicio - SQS Event")
    logger.info(f"Records: {len(event.get('Records', []))}")

    for record in event["Records"]:
        try:
            message = json.loads(record["body"])
            project_id = message.get("project_id")

            if not project_id:
                logger.error("❌ project_id no encontrado en mensaje")
                continue

            logger.info(f"📨 Procesando proyecto: {project_id}")

            result = rotate_project_via_api(project_id)

            status = result.get("status", "unknown")
            processed = result.get("environments_processed", "?")
            failed = result.get("environments_failed", "?")
            logger.info(
                f"✅ Proyecto {project_id}: {status} "
                f"({processed} OK, {failed} fallos)"
            )

            # Si la API reportó fallos parciales, lanzar para que SQS reintente
            if status not in ("success",):
                raise Exception(f"Rotación no exitosa: {status}")

            logger.info("✅ Mensaje confirmado en SQS")

        except Exception as e:
            logger.error(f"❌ Error procesando record: {e}", exc_info=True)
            # Lanzar para que SQS reintente (y eventualmente → DLQ)
            raise

    return {
        "statusCode": 200,
        "body": json.dumps(
            {"status": "success", "records_processed": len(event["Records"])}
        ),
    }
