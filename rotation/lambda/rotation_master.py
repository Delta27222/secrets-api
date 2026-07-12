"""
Lambda Maestro: Rotación + Reencriptación de Llaves.

Función: Obtiene todos los proyectos y envía cada uno a SQS para procesamiento.
Ejecutado por: EventBridge cron (00:00 UTC)
Timeout: 30 segundos
Memory: 256 MB

Flujo:
1. Conecta MongoDB
2. Revisa la edad de la última rotación de cada proyecto
   (secrets_encryption.encrypted_at más reciente entre sus environments)
3. Encola SOLO los proyectos cuya última rotación pasó ROTATION_INTERVAL_DAYS (90)
4. Retorna resumen (due, queued, skipped)

El cron corre a diario, pero la rotación real de cada proyecto ocurre cada
~90 días (cuando su llave cumple la edad). Configurable con ROTATION_INTERVAL_DAYS.

Logs: CloudWatch /aws/lambda/rotation_master
"""

import json
import os
import sys
import logging
import asyncio
from datetime import datetime, timedelta

import boto3
from motor.motor_asyncio import AsyncIOMotorClient

# Configurar logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS clients
sqs = boto3.client('sqs')

# Environment variables
MONGODB_URL = os.getenv('MONGODB_URL')
MONGO_DB = os.getenv('MONGO_DB', 'secrets-27222')
SQS_QUEUE_URL = os.getenv('SQS_QUEUE_URL')

# Cada cuántos días debe rotar una llave (NIST recomienda ≤ 1 año; aquí 90)
ROTATION_INTERVAL_DAYS = int(os.getenv('ROTATION_INTERVAL_DAYS', '90'))


def _parse_encrypted_at(value):
    """Normaliza secrets_encryption.encrypted_at a datetime (o None)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        # quitar tz para comparar con utcnow() (naive)
        return value.replace(tzinfo=None)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00')).replace(tzinfo=None)
        except Exception:
            return None
    return None


async def get_due_projects(mongo_client, interval_days):
    """
    Devuelve los proyectos que TOCA rotar: aquellos cuya última rotación
    (secrets_encryption.encrypted_at más reciente entre sus environments)
    ya pasó `interval_days` días. Los que nunca fueron rotados también entran.

    Returns: (due_project_ids, skipped_count)
    """
    db = mongo_client[MONGO_DB]
    now = datetime.utcnow()
    cutoff = now - timedelta(days=interval_days)

    projects = await db['projects'].find({}, {'_id': 1}).to_list(None)

    due = []
    skipped = 0

    for p in projects:
        pid = str(p['_id'])
        envs = await db['environments'].find(
            {'project_id': pid},
            {'secrets_encryption.encrypted_at': 1}
        ).to_list(None)

        # Sin environments → nada que re-encriptar
        if not envs:
            skipped += 1
            continue

        timestamps = []
        never_rotated = False
        for e in envs:
            ts = _parse_encrypted_at(
                (e.get('secrets_encryption') or {}).get('encrypted_at')
            )
            if ts is None:
                never_rotated = True
            else:
                timestamps.append(ts)

        # Toca si: alguna env nunca se rotó, o la última rotación ya venció
        if never_rotated or (timestamps and max(timestamps) <= cutoff):
            due.append(pid)
            edad = "nunca" if never_rotated else f"{(now - max(timestamps)).days}d"
            logger.info(f"   ⏰ {pid} → rota (última: {edad})")
        else:
            skipped += 1

    logger.info(
        f"✅ {len(projects)} proyectos · {len(due)} por rotar (≥{interval_days}d) · "
        f"{skipped} al día"
    )
    return due, skipped


def send_to_sqs(project_id):
    """Envía proyecto a SQS queue."""
    try:
        message = {
            'project_id': project_id,
            'action': 'rotate_and_reencrypt',
            'timestamp': datetime.utcnow().isoformat()
        }

        response = sqs.send_message(
            QueueUrl=SQS_QUEUE_URL,
            MessageBody=json.dumps(message)
        )

        logger.info(f"📤 Proyecto {project_id} enviado a SQS (MessageId: {response['MessageId']})")
        return True

    except Exception as e:
        logger.error(f"❌ Error enviando {project_id} a SQS: {e}")
        return False


async def process_all_projects():
    """Obtiene proyectos y los envía a SQS."""
    mongo_client = AsyncIOMotorClient(MONGODB_URL)

    try:
        logger.info(
            f"🔄 Chequeo de rotación (intervalo: {ROTATION_INTERVAL_DAYS} días)"
        )

        # 1. Obtener SOLO los proyectos que ya cumplieron el intervalo
        project_ids, skipped_count = await get_due_projects(
            mongo_client, ROTATION_INTERVAL_DAYS
        )

        if not project_ids:
            logger.info("✅ Ningún proyecto vencido hoy. Nada que rotar.")
            return {
                'status': 'success',
                'projects_queued': 0,
                'projects_skipped': skipped_count,
                'interval_days': ROTATION_INTERVAL_DAYS,
                'message': 'No projects due for rotation'
            }

        # 2. Enviar a SQS solo los vencidos
        queued_count = 0
        failed_count = 0

        for project_id in project_ids:
            if send_to_sqs(project_id):
                queued_count += 1
            else:
                failed_count += 1

        # 3. Resumen
        logger.info(
            f"✅ {queued_count} en queue, {failed_count} fallidos, "
            f"{skipped_count} al día"
        )

        return {
            'status': 'success',
            'interval_days': ROTATION_INTERVAL_DAYS,
            'projects_due': len(project_ids),
            'projects_queued': queued_count,
            'projects_failed': failed_count,
            'projects_skipped': skipped_count,
            'timestamp': datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error(f"❌ Error crítico: {e}", exc_info=True)
        return {
            'status': 'error',
            'message': str(e)
        }

    finally:
        mongo_client.close()


def lambda_handler(event, context):
    """Handler de Lambda."""
    logger.info(f"🚀 Inicio - EventBridge Cron")
    logger.info(f"Event: {json.dumps(event)}")

    try:
        result = asyncio.run(process_all_projects())
        return {
            'statusCode': 200,
            'body': json.dumps(result)
        }

    except Exception as e:
        logger.error(f"❌ Error en lambda_handler: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({
                'status': 'error',
                'message': str(e)
            })
        }
