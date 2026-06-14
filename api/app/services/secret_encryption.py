"""
Servicio de Encriptación de Secretos.

Proporciona funciones para encriptar y desencriptar secretos
usando el EncryptionKeyManager para manejar versiones de llaves.
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

from motor.motor_asyncio import AsyncIOMotorClient

from ..core.config import database_name, encryption_keys_collection_name
from .encryption_keys import get_key_manager

logger = logging.getLogger(__name__)


async def encrypt_secrets(
    conn: AsyncIOMotorClient,
    secrets: Dict[str, Any],
    project_id: Optional[str] = None
) -> tuple:
    """
    Encripta un diccionario de secretos usando la llave ACTIVA.

    Args:
        conn: Cliente MongoDB async
        secrets: Diccionario de secretos {key: value}
        project_id: ID del proyecto (None = global)

    Returns:
        Tupla (encrypted_dict, encryption_metadata)
        - encrypted_dict: Secretos encriptados
        - encryption_metadata: Metadata sobre qué llave se usó

    Ejemplo:
        ```python
        encrypted, metadata = await encrypt_secrets(
            db_client,
            {"DB_PASS": "super-secret", "API_KEY": "key123"},
            project_id="proj_123"
        )

        # encrypted = {"DB_PASS": "gAAAAABl8h7s...", "API_KEY": "gAAAAABl8h7t..."}
        # metadata = {
        #     "key_version": 1,
        #     "encrypted_with_key_id": "key_proj_123_20240115_001",
        #     "encrypted_at": datetime,
        #     "requires_reencryption": False
        # }
        ```
    """
    try:
        manager = get_key_manager()

        # Obtener llave activa
        fernet = await manager.get_active_key(conn, project_id)

        # Obtener ID de la llave activa
        db = conn[database_name]
        active_key = await db[encryption_keys_collection_name].find_one(
            {"project_id": project_id, "is_primary": True}
        )

        if not active_key:
            raise ValueError(f"No active key for project {project_id}")

        now = datetime.utcnow()

        # Encriptar cada secreto
        encrypted = {}
        for key, value in secrets.items():
            if isinstance(value, str):
                encrypted[key] = fernet.encrypt(value.encode()).decode()
            elif value is None:
                encrypted[key] = None
            else:
                # Convertir a string y encriptar
                encrypted[key] = fernet.encrypt(str(value).encode()).decode()

        # Crear metadata
        encryption_metadata = {
            "key_version": active_key.get("version", 1),
            "encrypted_with_key_id": active_key["key_id"],
            "encrypted_at": now,
            "requires_reencryption": False
        }

        logger.debug(
            f"✅ Encriptados {len(encrypted)} secretos con llave {active_key['key_id']}"
        )

        return encrypted, encryption_metadata

    except Exception as e:
        logger.error(f"❌ Error encriptando secretos: {e}")
        raise


async def decrypt_secrets(
    conn: AsyncIOMotorClient,
    environment_doc: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Desencripta secretos de un documento de environment.

    **Lógica:**
    1. Buscar en metadata qué versión de llave se usó
    2. Si existe metadata: obtener esa versión específica
    3. Si NO existe metadata: usar llave activa (datos muy antiguos)
    4. Desencriptar cada secreto
    5. Si hay error: registrar pero no fallar todo

    Args:
        conn: Cliente MongoDB async
        environment_doc: Documento completo del environment de BD

    Returns:
        Diccionario desencriptado {key: value}

    Ejemplo:
        ```python
        env_doc = await db.environments.find_one({"_id": ObjectId("...")})
        decrypted = await decrypt_secrets(db_client, env_doc)
        # decrypted = {"DB_PASS": "super-secret", "API_KEY": "key123"}
        ```
    """
    try:
        manager = get_key_manager()

        # Obtener metadata de encriptación
        encryption_meta = environment_doc.get("secrets_encryption", {})
        key_id = encryption_meta.get("encrypted_with_key_id")

        # Obtener la llave correcta
        try:
            if key_id:
                # Usar versión específica
                fernet = await manager.get_key_for_version(conn, key_id)
                logger.debug(f"Usando llave específica: {key_id}")
            else:
                # Fallback: usar llave activa (datos antiguos)
                project_id = environment_doc.get("project_id")
                fernet = await manager.get_active_key(conn, project_id)
                logger.warning(
                    f"⚠️  No hay metadata de encriptación. "
                    f"Usando llave activa para {project_id}"
                )
        except Exception as e:
            logger.error(f"❌ No se puede obtener llave: {e}")
            raise ValueError(f"Cannot decrypt: {e}")

        # Desencriptar cada secreto
        encrypted_secrets = environment_doc.get("secrets", {})
        decrypted = {}

        for key, encrypted_value in encrypted_secrets.items():
            if encrypted_value is None:
                decrypted[key] = None
            else:
                try:
                    decrypted[key] = fernet.decrypt(encrypted_value.encode()).decode()
                except Exception as e:
                    logger.error(
                        f"❌ Error desencriptando secreto '{key}': {e}"
                    )
                    # No fallar todo si un secreto es inválido
                    decrypted[key] = f"[DECRYPTION_ERROR: {str(e)}]"

        logger.debug(f"✅ Desencriptados {len(decrypted)} secretos")
        return decrypted

    except Exception as e:
        logger.error(f"❌ Error en desencriptación general: {e}")
        raise


async def get_decryption_key_info(
    conn: AsyncIOMotorClient,
    environment_doc: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Obtiene información sobre qué llave se usó para desencriptar.

    **Útil para:**
    - Verificar si datos son recientes o antiguos
    - Planificar re-encriptación
    - Auditoría

    Args:
        conn: Cliente MongoDB async
        environment_doc: Documento del environment

    Returns:
        Dict con info de la llave (sin material)
    """
    try:
        manager = get_key_manager()

        encryption_meta = environment_doc.get("secrets_encryption", {})
        key_id = encryption_meta.get("encrypted_with_key_id")

        if not key_id:
            return {
                "encrypted_with_key_id": None,
                "note": "Environment uses default active key (legacy data)"
            }

        # Obtener metadata de la llave
        key_metadata = await manager.get_key_metadata(conn, key_id)

        return {
            "encrypted_with_key_id": key_id,
            "version": key_metadata.get("version"),
            "status": key_metadata.get("status"),
            "is_primary": key_metadata.get("is_primary"),
            "encrypted_at": encryption_meta.get("encrypted_at"),
            "requires_reencryption": encryption_meta.get("requires_reencryption", False),
            "expires_at": key_metadata.get("expires_at")
        }

    except Exception as e:
        logger.error(f"Error obteniendo info de llave: {e}")
        return {"error": str(e)}
