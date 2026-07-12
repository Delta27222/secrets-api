"""
[DESACTIVADO] Scheduler en proceso para rotación de llaves (APScheduler).

⚠️  Este módulo quedó DESACTIVADO a propósito.

La rotación automática de llaves ahora la gestiona una arquitectura serverless
en AWS: EventBridge (cron) → Lambda Maestro → SQS → Lambda Worker → endpoint de
la API. Ver `sprint2/sprint2_desarrollo.md`, secciones 4.2.14–4.2.17.

Mantener este scheduler en proceso activo JUNTO al flujo de AWS provocaría
rotaciones duplicadas y condiciones de carrera sobre la misma llave. Por eso:

  - `start_scheduler()` es un no-op (nunca programa ni inicia nada).
  - Ya no se importa `apscheduler` (evita romper el build si no está instalado).

El módulo se conserva únicamente como referencia histórica del enfoque anterior
y para que el endpoint de estado siga respondiendo (indicando que está desactivado).
"""

import logging

logger = logging.getLogger(__name__)

_DEPRECATED_MSG = (
    "APScheduler desactivado. La rotación automática la gestiona AWS "
    "(EventBridge + Lambda + API). Ver sprint2 secciones 4.2.14–4.2.17."
)


def start_scheduler() -> None:
    """No-op. La rotación automática la gestiona AWS EventBridge + Lambda."""
    logger.info(f"⏭️  start_scheduler() ignorado — {_DEPRECATED_MSG}")


def stop_scheduler() -> None:
    """No-op. No hay scheduler en proceso que detener."""
    return None


async def trigger_rotation_job_manual(project_id: str = None) -> None:
    """
    No-op. La rotación se dispara vía el endpoint interno de la API,
    invocado por el Lambda Worker (o manualmente con un service token
    de scope `keys:rotate`).
    """
    logger.info(f"⏭️  trigger_rotation_job_manual() ignorado — {_DEPRECATED_MSG}")


def get_scheduler_status() -> dict:
    """Retorna el estado: desactivado (rotación gestionada por AWS)."""
    return {
        "running": False,
        "deprecated": True,
        "message": _DEPRECATED_MSG,
        "jobs": [],
    }
