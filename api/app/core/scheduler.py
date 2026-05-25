"""
Scheduler para tareas automáticas: Rotación de llaves.

Usa APScheduler para ejecutar rotaciones programadas sin bloquear la aplicación.
"""

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta

from ..core.config import database_name, encryption_keys_collection_name, projects_collection_name
from ..db.mongodb import db
from ..services.encryption_keys import get_key_manager

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def rotate_encryption_keys_job():
    """
    Job que ejecuta la rotación automática de llaves.

    **Lógica:**
    1. Para cada proyecto + global:
       a. Generar nueva llave
       b. Esperar validación (opcional: 24h)
       c. Rotar si todo está bien
    2. Registrar en auditoría

    **Frecuencia:** Cada 90 días (NIST recomendación)
    """
    try:
        logger.info("🔄 Iniciando rotación automática de llaves...")

        if not db.client:
            logger.error("❌ MongoDB no disponible")
            return

        manager = get_key_manager()
        project_ids = [None]  # Global (None = global, se puede extender para por-proyecto)

        # Obtener todos los proyectos si quieres rotar por proyecto
        try:
            db_instance = db.client[database_name]
            projects = await db_instance[projects_collection_name].find({}).to_list(None)
            project_ids.extend([str(p["_id"]) for p in projects])
        except Exception as e:
            logger.warning(f"⚠️  No se pudieron obtener proyectos: {e}")
            project_ids = [None]  # Fallback a solo global

        rotated_count = 0
        failed_count = 0

        for project_id in project_ids:
            try:
                db_instance = db.client[database_name]

                # Verificar si hay llave activa que necesita rotación
                active_key = await db_instance[encryption_keys_collection_name].find_one(
                    {"project_id": project_id, "is_primary": True}
                )

                if not active_key:
                    logger.warning(
                        f"⚠️  No hay llave activa para proyecto {project_id}"
                    )
                    continue

                # Verificar si la llave tiene > 90 días
                activated_at = active_key.get("activated_at", datetime.utcnow())
                days_old = (datetime.utcnow() - activated_at).days

                if days_old < 90:
                    logger.info(
                        f"⏭️  Llave de {project_id} tiene solo {days_old} días. "
                        f"Rotación en {90 - days_old} días."
                    )
                    continue

                logger.info(
                    f"📅 Llave de {project_id} tiene {days_old} días. "
                    f"Ejecutando rotación..."
                )

                # Paso 1: Generar nueva llave
                new_key = await manager.generate_key(
                    conn=db.client,
                    project_id=project_id,
                    created_by=None,  # Sistema
                    reason="scheduled"
                )
                logger.info(f"✅ Nueva llave generada: {new_key['key_id']}")

                # Paso 2: Rotar inmediatamente (o esperar 24h en producción)
                # Para testing, hacemos rotación inmediata
                rotation = await manager.rotate_key(
                    conn=db.client,
                    project_id=project_id,
                    actor_id=None  # Sistema
                )
                logger.info(f"✅ Rotación completada: {rotation['new_key_id']}")

                rotated_count += 1

            except Exception as e:
                logger.error(
                    f"❌ Error rotando llave de {project_id}: {e}"
                )
                failed_count += 1

        # Resumen
        logger.info(
            f"🏁 Rotación automática completada: "
            f"{rotated_count} exitosas, {failed_count} fallidas"
        )

    except Exception as e:
        logger.error(f"❌ Error crítico en scheduler: {e}")


def start_scheduler():
    """
    Inicia el scheduler con los jobs configurados.

    Se ejecuta en startup de la aplicación.
    """
    try:
        # Job de rotación: cada día a las 00:00 UTC
        scheduler.add_job(
            rotate_encryption_keys_job,
            trigger=CronTrigger(hour=0, minute=0),
            name="rotate_encryption_keys",
            id="rotate_encryption_keys",
            replace_existing=True,
            max_instances=1  # Solo una instancia a la vez
        )

        scheduler.start()
        logger.info("✅ Scheduler iniciado. Job de rotación configurado para 00:00 UTC")

    except Exception as e:
        logger.error(f"❌ Error iniciando scheduler: {e}")


def stop_scheduler():
    """
    Detiene el scheduler.

    Se ejecuta en shutdown de la aplicación.
    """
    try:
        if scheduler.running:
            scheduler.shutdown()
            logger.info("✅ Scheduler detenido")
    except Exception as e:
        logger.error(f"❌ Error deteniendo scheduler: {e}")


# Funciones auxiliares para testing/manual

async def trigger_rotation_job_manual(project_id: str = None):
    """Ejecuta rotación manualmente (útil para testing)."""
    logger.info(f"⚡ Ejecución manual de rotación para {project_id}...")
    await rotate_encryption_keys_job()


def get_scheduler_status() -> dict:
    """Retorna estado actual del scheduler."""
    return {
        "running": scheduler.running,
        "jobs": [
            {
                "id": job.id,
                "name": job.name,
                "trigger": str(job.trigger),
                "next_run_time": str(job.next_run_time)
            }
            for job in scheduler.get_jobs()
        ]
    }
