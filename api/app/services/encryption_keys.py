"""
Servicio de Gestión de Llaves de Encriptación.

Implementa el ciclo de vida completo:
- Generación automática de llaves
- Rotación programada
- Versionado de llaves
- Auditoría en QuestDB
"""

import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import httpx
import logging

from cryptography.fernet import Fernet
from motor.motor_asyncio import AsyncIOMotorClient

from ..core.config import (
    EC2_INSTANCE_IP,
    EC2_INSTANCE_PORT,
    database_name,
    encryption_keys_collection_name,
)
from ..core.csfle import encrypt_field, decrypt_field

logger = logging.getLogger(__name__)

class EncryptionKeyManager:
    """
    Gestor de ciclo de vida completo de llaves de encriptación.

    Responsabilidades:
    - Generar nuevas versiones de llaves
    - Rotar llaves (activar nueva, deprecar anterior)
    - Obtener llaves activas para encriptar
    - Obtener versiones específicas para desencriptar datos antiguos
    - Registrar auditoría en QuestDB
    """

    async def generate_key(
        self,
        conn: AsyncIOMotorClient,
        project_id: Optional[str] = None,
        created_by: Optional[str] = None,
        reason: str = "scheduled"
    ) -> Dict[str, Any]:
        """
        Genera una nueva versión de llave.

        Args:
            conn: Cliente MongoDB async
            project_id: ID del proyecto (None = global)
            created_by: ID del usuario que crea la llave
            reason: Razón de generación (scheduled, manual, compromised)

        Returns:
            Dict con key_id, version, status, created_at
        """
        try:
            db = conn[database_name]

            # Determinar versión
            last_version = await self._get_last_key_version(db, project_id)
            new_version = (last_version or 0) + 1

            # Generar llave Fernet (sin argumentos; la versión va en el documento)
            new_key = Fernet.generate_key()

            # Crear documento
            now = datetime.utcnow()
            key_id = f"key_{project_id or 'global'}_{now.strftime('%Y%m%d')}_{new_version:03d}"

            # Encriptar key_material con CSFLE antes de guardarlo
            encrypted_key_material = encrypt_field(new_key.decode())

            key_doc = {
                "key_id": key_id,
                "project_id": project_id,
                "version": new_version,
                "key_material": encrypted_key_material,
                "algorithm": "Fernet",
                "key_size_bits": 256,
                "status": "pending",
                "is_primary": False,
                "created_at": now,
                "activated_at": None,
                "rotated_at": None,
                "deactivated_at": None,
                "expires_at": now + timedelta(days=365),  # 1 año NIST
                "created_by": created_by,
                "rotation_reason": reason,
                "previous_key_id": await self._get_previous_key_id(db, project_id),
                "metadata": {
                    "environment": os.getenv("ENVIRONMENT", "production"),
                    "region": os.getenv("AWS_REGION", "us-east-1"),
                    "backup_location": None
                }
            }

            # Guardar en MongoDB
            result = await db[encryption_keys_collection_name].insert_one(key_doc)

            # Registrar en encryption_key_versions (historial)
            version_doc = {
                "key_id": key_id,
                "version_number": new_version,
                "created_at": now,
                "activated_at": None
            }
            await db["encryption_key_versions"].insert_one(version_doc)

            # Registrar auditoría
            await self._audit_log(
                action="KEY_GENERATED",
                key_id=key_id,
                project_id=project_id,
                actor_id=created_by,
                details={"version": new_version, "reason": reason}
            )

            logger.info(f"✅ Llave generada: {key_id} (v{new_version})")

            return {
                "key_id": key_id,
                "version": new_version,
                "status": "pending",
                "created_at": now,
                "object_id": str(result.inserted_id)
            }

        except Exception as e:
            logger.error(f"❌ Error generando llave: {e}")
            await self._audit_log(
                action="KEY_GENERATION_FAILED",
                key_id="",
                project_id=project_id,
                actor_id=created_by,
                details={"error": str(e)}
            )
            raise

    async def rotate_key(
        self,
        conn: AsyncIOMotorClient,
        project_id: Optional[str] = None,
        actor_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Rota la llave: marca nueva como activa, anterior como deprecated.

        Proceso:
        1. Encontrar llave pending más reciente
        2. Marcarla como active
        3. Marcar anterior como deprecated
        4. Registrar en auditoría

        Args:
            conn: Cliente MongoDB async
            project_id: ID del proyecto (None = global)
            actor_id: ID del usuario que ejecuta la rotación

        Returns:
            Dict con old_key_id, new_key_id, status

        Raises:
            ValueError: Si no hay llave pending para rotar
        """
        try:
            db = conn[database_name]

            # Obtener llave pending más reciente
            new_key = await db[encryption_keys_collection_name].find_one(
                {"project_id": project_id, "status": "pending"},
                sort=[("version", -1)]
            )

            if not new_key:
                raise ValueError(
                    f"No hay llave pending disponible para rotar (project_id: {project_id})"
                )

            # Obtener llave activa anterior
            old_key = await db[encryption_keys_collection_name].find_one(
                {"project_id": project_id, "is_primary": True}
            )

            now = datetime.utcnow()

            # Actualizar nueva llave como activa
            await db[encryption_keys_collection_name].update_one(
                {"_id": new_key["_id"]},
                {"$set": {
                    "status": "active",
                    "is_primary": True,
                    "activated_at": now
                }}
            )

            # Actualizar encryption_key_versions con activated_at
            await db["encryption_key_versions"].update_one(
                {"key_id": new_key["key_id"]},
                {"$set": {"activated_at": now}}
            )

            # Deprecar llave anterior
            if old_key:
                await db[encryption_keys_collection_name].update_one(
                    {"_id": old_key["_id"]},
                    {"$set": {
                        "status": "deprecated",
                        "is_primary": False,
                        "rotated_at": now
                    }}
                )

            # Registrar auditoría
            await self._audit_log(
                action="KEY_ROTATED",
                key_id=new_key["key_id"],
                project_id=project_id,
                actor_id=actor_id,
                details={
                    "old_key_id": old_key["key_id"] if old_key else None,
                    "new_key_id": new_key["key_id"],
                    "version": new_key["version"]
                }
            )

            old_key_id = old_key['key_id'] if old_key else "(primera llave)"
            logger.info(
                f"✅ Llave rotada: {old_key_id} → {new_key['key_id']}"
            )

            return {
                "old_key_id": old_key["key_id"] if old_key else None,
                "new_key_id": new_key["key_id"],
                "status": "success",
                "rotated_at": now
            }

        except Exception as e:
            logger.error(f"❌ Error durante rotación: {e}")
            await self._audit_log(
                action="KEY_ROTATION_FAILED",
                key_id="",
                project_id=project_id,
                actor_id=actor_id,
                details={"error": str(e)}
            )
            raise

    async def get_active_key(
        self,
        conn: AsyncIOMotorClient,
        project_id: Optional[str] = None
    ) -> Fernet:
        """
        Obtiene la llave Fernet activa para encriptar nuevos datos.

        Args:
            conn: Cliente MongoDB async
            project_id: ID del proyecto (None = global)

        Returns:
            Objeto Fernet para encriptación

        Raises:
            ValueError: Si no hay llave activa
        """
        db = conn[database_name]
        key_doc = await db[encryption_keys_collection_name].find_one(
            {"project_id": project_id, "is_primary": True}
        )

        if not key_doc:
            raise ValueError(
                f"❌ No hay llave activa para proyecto {project_id}"
            )

        # Desencriptar key_material con CSFLE
        raw_key_material = decrypt_field(key_doc["key_material"])
        return Fernet(raw_key_material.encode())

    async def get_key_for_version(
        self,
        conn: AsyncIOMotorClient,
        key_id: str
    ) -> Fernet:
        """
        Obtiene una llave específica por versión (para desencriptar datos antiguos).

        Permite desencriptar datos que fueron encriptados con versiones anteriores
        incluso si ya fueron rotadas y deprecadas.

        Args:
            conn: Cliente MongoDB async
            key_id: ID único de la llave

        Returns:
            Objeto Fernet para desencriptación

        Raises:
            ValueError: Si la llave no existe
        """
        db = conn[database_name]
        key_doc = await db[encryption_keys_collection_name].find_one({"key_id": key_id})

        if not key_doc:
            raise ValueError(f"❌ Llave {key_id} no encontrada")

        # Desencriptar key_material con CSFLE
        raw_key_material = decrypt_field(key_doc["key_material"])
        return Fernet(raw_key_material.encode())

    async def get_key_metadata(
        self,
        conn: AsyncIOMotorClient,
        key_id: str
    ) -> Dict[str, Any]:
        """
        Obtiene metadata de una llave sin exponer el material criptográfico.

        Args:
            conn: Cliente MongoDB async
            key_id: ID único de la llave

        Returns:
            Dict con metadata (sin key_material)
        """
        db = conn[database_name]
        key_doc = await db[encryption_keys_collection_name].find_one(
            {"key_id": key_id},
            {"key_material": 0}  # Excluir material criptográfico
        )

        if not key_doc:
            raise ValueError(f"❌ Llave {key_id} no encontrada")

        return key_doc

    async def list_key_versions(
        self,
        conn: AsyncIOMotorClient,
        project_id: Optional[str] = None
    ) -> list:
        """
        Lista todas las versiones de llaves de un proyecto.

        Args:
            conn: Cliente MongoDB async
            project_id: ID del proyecto (None = global)

        Returns:
            Lista de documentos de llaves (sin material)
        """
        db = conn[database_name]
        keys = await db[encryption_keys_collection_name].find(
            {"project_id": project_id},
            {"key_material": 0}
        ).sort("version", -1).to_list(None)

        return keys

    async def _get_last_key_version(
        self,
        db,
        project_id: Optional[str] = None
    ) -> Optional[int]:
        """Obtiene el número de versión más reciente."""
        last_key = await db[encryption_keys_collection_name].find_one(
            {"project_id": project_id},
            sort=[("version", -1)]
        )
        return last_key["version"] if last_key else None

    async def _get_previous_key_id(
        self,
        db,
        project_id: Optional[str] = None
    ) -> Optional[str]:
        """Obtiene el ID de la llave anterior para tracking."""
        previous = await db[encryption_keys_collection_name].find_one(
            {"project_id": project_id, "is_primary": True}
        )
        return previous["key_id"] if previous else None

    async def _audit_log(
        self,
        action: str,
        key_id: str,
        project_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        operation_result: str = "success"
    ) -> None:
        """
        Registra evento en QuestDB para auditoría.

        Args:
            action: Tipo de acción (KEY_GENERATED, KEY_ROTATED, etc)
            key_id: ID de la llave
            project_id: ID del proyecto
            actor_id: ID del usuario
            details: Metadata adicional
            operation_result: Resultado (success, failure, partial)
        """
        try:
            import json

            now = datetime.utcnow().isoformat() + "Z"
            details_str = json.dumps(details or {})
            # Escapar comillas para SQL
            details_str = details_str.replace("'", "''")

            # Construir query INSERT para QuestDB (8 columnas)
            query = (
                f"INSERT INTO encryption_key_audit VALUES("
                f"'{now}',"
                f"'{action}',"
                f"'{key_id}',"
                f"'{project_id if project_id else ''}',"
                f"'{actor_id if actor_id else ''}',"
                f"'api',"
                f"'{operation_result}',"
                f"'{details_str}'"
                f")"
            )

            # Enviar a QuestDB
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"http://{EC2_INSTANCE_IP}:{EC2_INSTANCE_PORT}/exec",
                    params={"query": query},
                    timeout=10.0
                )

                if response.status_code not in [200, 201]:
                    logger.warning(
                        f"⚠️  QuestDB auditoría retornó {response.status_code}: {response.text}"
                    )
                else:
                    logger.debug(f"✅ Auditoría registrada en QuestDB: {action}")

        except Exception as e:
            logger.error(f"❌ Error registrando auditoría: {e}")
            # No fallar todo si QuestDB falla - log pero continúa


# Singleton global
_key_manager_instance: Optional[EncryptionKeyManager] = None


def get_key_manager() -> EncryptionKeyManager:
    """Factory para obtener instancia del manager."""
    global _key_manager_instance
    if _key_manager_instance is None:
        _key_manager_instance = EncryptionKeyManager()
    return _key_manager_instance


# ============================================================================
# HELPERS PARA INICIALIZAR ENCRIPTACIÓN
# ============================================================================

async def initialize_project_encryption_key(
    conn: AsyncIOMotorClient,
    project_id: str,
    created_by: Optional[str] = None
) -> Dict[str, Any]:
    """
    Inicializa llave de encriptación para un proyecto.

    Llamar cuando se crea un nuevo proyecto para que los environments
    puedan ser creados exitosamente.

    Args:
        conn: Cliente MongoDB async
        project_id: ID del proyecto
        created_by: ID del usuario que crea el proyecto

    Returns:
        Dict con info de la llave creada

    Ejemplo:
        ```python
        await initialize_project_encryption_key(
            db_client,
            project_id=new_project.id,
            created_by=current_user.id
        )
        ```
    """
    try:
        manager = get_key_manager()

        # 1. Generar nueva llave (status: pending)
        key = await manager.generate_key(
            conn,
            project_id,
            created_by=created_by,
            reason="project_creation"
        )

        # 2. Activarla inmediatamente (pending → active)
        await manager.rotate_key(conn, project_id)

        logger.info(f"✅ Llave de encriptación creada para proyecto {project_id}")
        return key

    except Exception as e:
        logger.error(f"❌ Error inicializando key para proyecto {project_id}: {e}")
        raise
