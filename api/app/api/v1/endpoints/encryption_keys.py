"""
Endpoints para Gestión de Llaves de Encriptación.

Endpoints:
- POST   /keys/generate      - Generar nueva llave
- POST   /keys/rotate        - Rotar llave actual
- GET    /keys/versions      - Listar todas las versiones
- GET    /keys/current       - Obtener llave activa (metadata)
- GET    /keys/audit-log     - Obtener auditoría desde QuestDB
- POST   /secrets/reencrypt  - Re-encriptar secretos con nueva llave
"""

import logging
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorClient

from ....core.config import database_name, encryption_keys_collection_name
from ....db.mongodb import db
from ....services.encryption_keys import get_key_manager
from ....models.encryption_key import EncryptionKeyResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def get_db() -> AsyncIOMotorClient:
    """Dependencia para obtener cliente MongoDB."""
    return db.client


# ============================================================================
# POST /keys/generate - Generar nueva llave
# ============================================================================

@router.post("/keys/generate", response_model=dict)
async def generate_encryption_key(
    project_id: Optional[str] = Query(None, description="ID del proyecto (None=global)"),
    db_client: AsyncIOMotorClient = Depends(get_db),
    actor_id: Optional[str] = Query(None, description="ID del usuario que genera la llave")
):
    """
    Genera una nueva versión de llave de encriptación.

    **Parámetros:**
    - `project_id`: ID del proyecto (None para global)
    - `actor_id`: ID del usuario que genera (para auditoría)

    **Respuesta:**
    ```json
    {
        "key_id": "key_global_20240115_002",
        "version": 2,
        "status": "pending",
        "created_at": "2024-01-15T10:30:00Z",
        "object_id": "65a4b8c9d1e2f3g4h5i6j7k8"
    }
    ```

    **Notas:**
    - La llave se genera en estado "pending"
    - Requiere rotación para activarla
    - Útil para setup inicial o antes de rotación programada
    """
    try:
        manager = get_key_manager()
        result = await manager.generate_key(
            conn=db_client,
            project_id=project_id,
            created_by=actor_id,
            reason="manual"
        )
        return result

    except Exception as e:
        logger.error(f"Error generando llave: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# POST /keys/rotate - Rotar llave
# ============================================================================

@router.post("/keys/rotate", response_model=dict)
async def rotate_encryption_key(
    project_id: Optional[str] = Query(None, description="ID del proyecto (None=global)"),
    db_client: AsyncIOMotorClient = Depends(get_db),
    actor_id: Optional[str] = Query(None, description="ID del usuario que ejecuta la rotación")
):
    """
    Rota la llave: activa nueva versión, depreca anterior.

    **Flujo:**
    1. Busca llave pending más reciente
    2. La marca como "active" e "is_primary"
    3. Marca anterior como "deprecated"
    4. Registra en auditoría QuestDB

    **Respuesta:**
    ```json
    {
        "old_key_id": "key_global_20240115_001",
        "new_key_id": "key_global_20240115_002",
        "status": "success",
        "rotated_at": "2024-01-15T10:30:00Z"
    }
    ```

    **Error si:**
    - No hay llave pending para rotar
    - Error de BD

    **Impacto:**
    - Los datos encriptados con la llave antigua siguen siendo válidos
    - Los nuevos datos se encriptarán con la nueva llave
    """
    try:
        manager = get_key_manager()
        result = await manager.rotate_key(
            conn=db_client,
            project_id=project_id,
            actor_id=actor_id
        )
        return result

    except ValueError as e:
        logger.warning(f"Validación: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error rotando llave: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# GET /keys/versions - Listar todas las versiones
# ============================================================================

@router.get("/keys/versions", response_model=List[dict])
async def list_key_versions(
    project_id: Optional[str] = Query(None, description="ID del proyecto (None=global)"),
    db_client: AsyncIOMotorClient = Depends(get_db)
):
    """
    Lista todas las versiones de llaves (ordenadas por versión descendente).

    **Respuesta:**
    ```json
    [
        {
            "_id": ObjectId("..."),
            "key_id": "key_global_20240115_002",
            "version": 2,
            "status": "active",
            "is_primary": true,
            "created_at": "2024-01-15T10:30:00Z",
            "activated_at": "2024-01-15T10:30:00Z",
            "expires_at": "2025-01-15T10:30:00Z",
            "algorithm": "Fernet",
            "key_size_bits": 256
        },
        {
            "key_id": "key_global_20240115_001",
            "version": 1,
            "status": "deprecated",
            "is_primary": false,
            ...
        }
    ]
    ```

    **Notas:**
    - No incluye `key_material` (secreto)
    - Útil para auditoría y debugging
    - Ordenado por versión descendente (más reciente primero)
    """
    try:
        manager = get_key_manager()
        keys = await manager.list_key_versions(
            conn=db_client,
            project_id=project_id
        )
        # Convertir ObjectId a string para JSON
        for key in keys:
            key["_id"] = str(key["_id"])
        return keys

    except Exception as e:
        logger.error(f"Error listando versiones: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# GET /keys/current - Obtener llave activa (sin material)
# ============================================================================

@router.get("/keys/current", response_model=dict)
async def get_current_key(
    project_id: Optional[str] = Query(None, description="ID del proyecto (None=global)"),
    db_client: AsyncIOMotorClient = Depends(get_db)
):
    """
    Obtiene metadata de la llave activa (sin material criptográfico).

    **Respuesta:**
    ```json
    {
        "key_id": "key_global_20240115_002",
        "version": 2,
        "status": "active",
        "is_primary": true,
        "algorithm": "Fernet",
        "key_size_bits": 256,
        "created_at": "2024-01-15T10:30:00Z",
        "activated_at": "2024-01-15T10:30:00Z",
        "expires_at": "2025-01-15T10:30:00Z"
    }
    ```

    **Usos:**
    - Verificar cuál es la llave actual
    - Checking de expiración
    - Información para dashboards

    **Seguridad:**
    - NO expone `key_material`
    - Safe para endpoints públicos
    """
    try:
        db_instance = db_client[database_name]
        key_doc = await db_instance[encryption_keys_collection_name].find_one(
            {"project_id": project_id, "is_primary": True},
            {"key_material": 0}  # Excluir material
        )

        if not key_doc:
            raise HTTPException(
                status_code=404,
                detail=f"No active key found for project {project_id}"
            )

        # Convertir ObjectId a string
        key_doc["_id"] = str(key_doc["_id"])
        return key_doc

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error obteniendo llave actual: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# GET /keys/audit-log - Obtener auditoría desde QuestDB
# ============================================================================

@router.get("/keys/audit-log", response_model=List[dict])
async def get_key_audit_log(
    project_id: Optional[str] = Query(None, description="ID del proyecto"),
    limit: int = Query(100, ge=1, le=1000, description="Máximo de registros"),
    offset: int = Query(0, ge=0, description="Número de registros a saltar"),
):
    """
    Obtiene log de auditoría de operaciones con llaves desde QuestDB.

    **Parámetros:**
    - `project_id`: Filtrar por proyecto (opcional)
    - `limit`: Máximo registros a retornar (default: 100)
    - `offset`: Paginación (default: 0)

    **Respuesta:**
    ```json
    [
        {
            "timestamp": "2024-01-15T10:30:00Z",
            "action": "KEY_ROTATED",
            "key_id": "key_global_20240115_002",
            "project_id": null,
            "actor_id": "user_123",
            "operation_result": "success",
            "details": {
                "old_key_id": "key_global_20240115_001",
                "new_key_id": "key_global_20240115_002",
                "version": 2
            }
        },
        {
            "timestamp": "2024-01-15T10:00:00Z",
            "action": "KEY_GENERATED",
            "key_id": "key_global_20240115_002",
            ...
        }
    ]
    ```

    **Acciones registradas:**
    - KEY_GENERATED: Nueva llave creada
    - KEY_ROTATED: Llave rotada
    - KEY_ACCESSED: Llave usada para encriptar/desencriptar
    - KEY_ROTATION_FAILED: Error durante rotación
    - KEY_GENERATION_FAILED: Error durante generación

    **Notas:**
    - Tiempo en UTC ISO 8601
    - Useful para auditoría de compliance
    - Queryable en QuestDB con SQL
    """
    try:
        import httpx
        import json
        import os

        EC2_INSTANCE_IP = os.getenv("EC2_INSTANCE_IP", "52.91.246.92")
        EC2_INSTANCE_PORT = os.getenv("EC2_INSTANCE_PORT", "9000")

        # Construir query SQL
        where_clause = f"WHERE project_id = '{project_id}'" if project_id else ""

        query = (
            f"SELECT timestamp, action, key_id, project_id, actor_id, "
            f"operation_result, details FROM encryption_key_audit "
            f"{where_clause} ORDER BY timestamp DESC "
            f"LIMIT {limit} OFFSET {offset}"
        )

        # Ejecutar en QuestDB
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"http://{EC2_INSTANCE_IP}:{EC2_INSTANCE_PORT}/exp",
                params={"query": query},
                timeout=10.0
            )

            if response.status_code != 200:
                logger.warning(f"QuestDB error: {response.text}")
                raise HTTPException(
                    status_code=503,
                    detail="Audit log service unavailable"
                )

            # QuestDB retorna CSV, parsear manualmente
            lines = response.text.strip().split("\n")
            if len(lines) < 2:
                return []

            results = []
            headers = lines[0].split(",")

            for line in lines[1:]:
                values = line.split(",")
                record = dict(zip(headers, values))

                # Parsear details JSON
                try:
                    record["details"] = json.loads(record.get("details", "{}"))
                except:
                    pass

                results.append(record)

            return results

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error obteniendo auditoría: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# POST /secrets/reencrypt - Re-encriptar secretos
# ============================================================================

@router.post("/secrets/reencrypt", response_model=dict)
async def reencrypt_secrets_batch(
    project_id: Optional[str] = Query(None, description="ID del proyecto"),
    dry_run: bool = Query(False, description="Simular sin modificar"),
    db_client: AsyncIOMotorClient = Depends(get_db),
):
    """
    Re-encripta secretos de ambientes con la nueva llave activa.

    **Flujo:**
    1. Encuentra todos los ambientes con secrets desactualizados
    2. Desencripta con llave anterior
    3. Re-encripta con llave actual
    4. Actualiza metadata
    5. Registra en auditoría

    **Parámetros:**
    - `project_id`: Filtrar ambientes por proyecto
    - `dry_run`: Si true, simula sin modificar datos

    **Respuesta:**
    ```json
    {
        "status": "success",
        "processed_count": 5,
        "skipped_count": 2,
        "errors": [],
        "duration_ms": 1234,
        "dry_run": false,
        "reencrypted_environments": [
            "env_id_1",
            "env_id_2"
        ]
    }
    ```

    **Casos:**
    1. Dry run: No modifica, solo reporta cuántos se procesarían
    2. Normal: Ejecuta re-encriptación y actualiza BD

    **Error scenarios:**
    - Llave antigua no disponible → saltar ambiente
    - Datos corruptos → registrar error, continuar
    - Nuevo ambiente sin metadata → saltar

    **Background job:**
    Este endpoint puede ser lento. Considerar ejecutar como background task.
    """
    try:
        from ....services.environment import decrypt_secrets, encrypt_secrets

        db_instance = db_client[database_name]
        manager = get_key_manager()

        now = datetime.utcnow()
        processed = 0
        skipped = 0
        errors = []
        reencrypted_envs = []

        # Obtener ambientes del proyecto
        query = {}
        if project_id:
            query["project_id"] = project_id

        environments = await db_instance["environments"].find(query).to_list(None)

        logger.info(f"🔄 Re-encriptando {len(environments)} ambientes...")

        for env in environments:
            try:
                # Verificar si necesita re-encriptación
                encryption_meta = env.get("secrets_encryption", {})
                old_key_id = encryption_meta.get("encrypted_with_key_id")

                # Obtener llave activa
                active_key = await manager.get_active_key(db_client, env.get("project_id"))

                # Desencriptar con versión anterior
                if old_key_id:
                    old_key = await manager.get_key_for_version(db_client, old_key_id)
                else:
                    # Fallback a llave activa si no hay metadata
                    old_key = active_key

                # Re-encriptar
                old_secrets = env.get("secrets", {})
                new_secrets = {}

                for key, encrypted_value in old_secrets.items():
                    try:
                        decrypted = old_key.decrypt(encrypted_value.encode()).decode()
                        new_secrets[key] = active_key.encrypt(decrypted.encode()).decode()
                    except Exception as e:
                        logger.warning(
                            f"⚠️  Error re-encriptando secret {key}: {e}"
                        )
                        errors.append({
                            "environment_id": str(env["_id"]),
                            "secret_key": key,
                            "error": str(e)
                        })

                if not dry_run and new_secrets:
                    # Actualizar en BD
                    await db_instance["environments"].update_one(
                        {"_id": env["_id"]},
                        {"$set": {
                            "secrets": new_secrets,
                            "secrets_encryption": {
                                "key_version": encryption_meta.get("key_version", 1) + 1,
                                "encrypted_with_key_id": await _get_active_key_id(
                                    db_client, env.get("project_id")
                                ),
                                "encrypted_at": now,
                                "requires_reencryption": False
                            }
                        }}
                    )

                    reencrypted_envs.append(str(env["_id"]))
                    logger.info(f"✅ Ambiente re-encriptado: {env['_id']}")

                processed += 1

            except Exception as e:
                logger.error(f"❌ Error en ambiente {env['_id']}: {e}")
                errors.append({
                    "environment_id": str(env["_id"]),
                    "error": str(e)
                })
                skipped += 1

        return {
            "status": "success",
            "processed_count": processed,
            "skipped_count": skipped,
            "errors": errors,
            "dry_run": dry_run,
            "reencrypted_environments": reencrypted_envs
        }

    except Exception as e:
        logger.error(f"Error en re-encriptación batch: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# GET /keys/scheduler-status - Estado del scheduler
# ============================================================================

@router.get("/keys/scheduler-status", response_model=dict)
async def get_scheduler_status():
    """
    Obtiene el estado del scheduler de rotación de llaves.

    **Respuesta:**
    ```json
    {
        "running": true,
        "jobs": [
            {
                "id": "rotate_encryption_keys",
                "name": "rotate_encryption_keys",
                "trigger": "cron[hour='0', minute='0']",
                "next_run_time": "2024-01-16T00:00:00"
            }
        ]
    }
    ```

    **Campos:**
    - `running`: Si el scheduler está activo
    - `jobs`: Lista de trabajos programados
    - `next_run_time`: Próxima ejecución del job

    **Notas:**
    - Job se ejecuta diariamente a las 00:00 UTC
    - Rotación solo ocurre si llave tiene >90 días
    """
    try:
        from ....core.scheduler import get_scheduler_status as get_status

        status = get_status()
        return status

    except Exception as e:
        logger.error(f"Error obteniendo estado del scheduler: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Helper Functions
# ============================================================================

async def _get_active_key_id(
    db_client: AsyncIOMotorClient,
    project_id: Optional[str] = None
) -> str:
    """Obtiene el key_id de la llave activa."""
    db_instance = db_client[database_name]
    active_key = await db_instance[encryption_keys_collection_name].find_one(
        {"project_id": project_id, "is_primary": True}
    )
    if not active_key:
        raise ValueError(f"No active key for project {project_id}")
    return active_key["key_id"]
