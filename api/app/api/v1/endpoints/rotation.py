"""
Endpoint interno de rotación de llaves de encriptación.

Diseñado para ser llamado por el Lambda Worker (máquina-a-máquina).
Autenticación: header X-Rotation-Token (shared secret), NO OAuth de GitHub.

Flujo completo (usa CSFLE nativo de la API):
1. Genera nueva llave (pending) con metadata completa
2. Rota llave (pending → active, anterior → deprecated)
3. Por cada environment del proyecto:
   - Desencripta secretos con la llave vieja (vía metadata)
   - Re-encripta con la llave nueva (activa)
   - Actualiza secrets + secrets_encryption
4. Retorna resumen
"""

import os
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Path

from ....db.mongodb import AsyncIOMotorClient, get_database
from ....core.config import database_name, environments_collection_name
from ....services.encryption_keys import get_key_manager
from ....services.secret_encryption import encrypt_secrets, decrypt_secrets

logger = logging.getLogger(__name__)

router = APIRouter(tags=["rotation"])

# Shared secret entre Lambda y API (configurar en env vars de ambos)
ROTATION_API_TOKEN = os.getenv("ROTATION_API_TOKEN", "")


def _verify_token(x_rotation_token: str) -> None:
    """Verifica el shared secret. Lanza 401 si no coincide."""
    if not ROTATION_API_TOKEN:
        raise HTTPException(
            status_code=500,
            detail="ROTATION_API_TOKEN no configurado en el servidor",
        )
    if x_rotation_token != ROTATION_API_TOKEN:
        raise HTTPException(status_code=401, detail="Token de rotación inválido")


@router.post("/internal/projects/{project_id}/rotate-encryption", tags=["rotation"])
async def rotate_project_encryption(
    project_id: str = Path(..., min_length=1),
    x_rotation_token: str = Header(...),
    db: AsyncIOMotorClient = Depends(get_database),
):
    """
    Rota la llave de encriptación de un proyecto y re-encripta todos sus secretos.

    Llamado por el Lambda Worker con el header X-Rotation-Token.
    """
    _verify_token(x_rotation_token)

    start = datetime.utcnow()
    manager = get_key_manager()

    logger.info(f"🔄 Rotación solicitada para proyecto: {project_id}")

    # ====== 1. GENERAR NUEVA LLAVE ======
    new_key = await manager.generate_key(
        db,
        project_id,
        created_by="lambda-worker",
        reason="scheduled-rotation",
    )
    logger.info(f"✅ Llave generada: {new_key['key_id']}")

    # ====== 2. ROTAR LLAVE (pending → active) ======
    rotation = await manager.rotate_key(db, project_id, actor_id="lambda-worker")
    logger.info(f"✅ Llave rotada: {rotation['new_key_id']}")

    # ====== 3. RE-ENCRIPTAR SECRETOS DE CADA ENVIRONMENT ======
    conn_db = db[database_name]
    environments = await conn_db[environments_collection_name].find(
        {"project_id": project_id}
    ).to_list(None)

    logger.info(f"   Ambientes a procesar: {len(environments)}")

    processed = 0
    failed = 0
    errors = []

    for env in environments:
        try:
            # Desencriptar con la llave vieja (usa secrets_encryption.encrypted_with_key_id)
            decrypted = await decrypt_secrets(db, env)

            # Re-encriptar con la llave nueva activa
            encrypted, metadata = await encrypt_secrets(db, decrypted, project_id)

            # Actualizar environment: secrets + metadata
            await conn_db[environments_collection_name].update_one(
                {"_id": env["_id"]},
                {
                    "$set": {
                        "secrets": encrypted,
                        "secrets_encryption": metadata,
                        "updated_at": datetime.utcnow(),
                    }
                },
            )

            logger.info(f"   ✅ {env.get('name', env['_id'])}")
            processed += 1

        except Exception as e:
            logger.error(f"   ❌ {env.get('name', env['_id'])}: {e}")
            errors.append({"environment_id": str(env["_id"]), "error": str(e)})
            failed += 1

    duration = (datetime.utcnow() - start).total_seconds()

    result = {
        "status": "success" if failed == 0 else "partial",
        "project_id": project_id,
        "new_key_id": new_key["key_id"],
        "old_key_id": rotation.get("old_key_id"),
        "environments_processed": processed,
        "environments_failed": failed,
        "errors": errors,
        "duration_seconds": round(duration, 2),
        "timestamp": datetime.utcnow().isoformat(),
    }

    logger.info(f"✅ Rotación completa: {processed} OK, {failed} fallos, {duration:.2f}s")

    return result
