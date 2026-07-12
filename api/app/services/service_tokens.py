"""
Service Token generation, validation, revocation, rotation.

Cifrado: CSFLE (igual que key_material en encryption_keys)
Búsqueda: SHA256 hash del token (sin cifrar)
"""

import secrets
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

from ..core.config import database_name, service_tokens_collection_name
from ..core.csfle import encrypt_field, decrypt_field
from ..models.service_token import (
    ServiceTokenInDB,
    ServiceTokenCreateResponse,
    ServiceTokenResponse,
    ServiceTokenUsage,
    ServiceTokenRotation
)

logger = logging.getLogger(__name__)

service_tokens_coll = service_tokens_collection_name


def _token_doc_to_in_db(token_doc: dict) -> ServiceTokenInDB:
    """Convierte documento MongoDB a modelo; omite token_secret (Binary CSFLE)."""
    doc = dict(token_doc)
    doc.pop("token_secret", None)
    return ServiceTokenInDB(**doc)


class ServiceTokenGenerator:
    """Genera tokens seguros cifrados con CSFLE"""

    @staticmethod
    async def generate_token(
        db: AsyncIOMotorClient,
        project_id: ObjectId,
        owner_id: ObjectId,
        name: str,
        scopes: List[str],
        expires_in_days: int = 90,
        rate_limit: Optional[dict] = None,
        description: Optional[str] = None,
        rotated: bool = False,
        environment_id: Optional[ObjectId] = None
    ) -> ServiceTokenCreateResponse:
        """
        Genera nuevo token cifrado con CSFLE.

        Args:
            db: MongoDB client
            project_id: Proyecto dueño (REQUERIDO)
            owner_id: Usuario que crea
            name: Nombre del token
            scopes: Permisos
            expires_in_days: Expiración (default 90)
            rate_limit: Límites personalizados
            description: Desc opcional

        Returns:
            ServiceTokenCreateResponse con token_secret visible UNA VEZ
        """
        # 1. Generar token aleatorio
        token_prefix = "tok_"
        random_suffix = secrets.token_urlsafe(32)
        token_value = token_prefix + random_suffix

        # 2. Generar token_id único
        token_id = f"tok_{secrets.token_hex(8)}"

        # 3. Hash SHA256 (SIN cifrar, para búsquedas)
        token_hash = hashlib.sha256(token_value.encode()).hexdigest()

        # 4. CIFRAR token con CSFLE
        try:
            encrypted_token = encrypt_field(token_value)
        except Exception as e:
            logger.error(f"Error cifrando token: {e}")
            raise ValueError(f"Cannot encrypt token: {e}")

        # 5. Metadata
        now = datetime.utcnow()
        expires_at = now + timedelta(days=expires_in_days)

        # 6. Documento para guardar
        token_doc = {
            "token_id": token_id,
            "name": name,
            "description": description,
            "token_secret": encrypted_token,  # Binary CSFLE
            "token_hash": token_hash,
            "owner_id": owner_id,
            "project_id": project_id,  # REQUERIDO
            "scopes": scopes,
            "rate_limit": rate_limit or {
                "requests_per_minute": 60,
                "requests_per_hour": 3000,
                "requests_per_day": 50000
            },
            "created_at": now,
            "updated_at": now,
            "expires_at": expires_at,
            "last_used_at": None,
            "status": "active",
            "is_active": True,
            "request_count": 0,
            "rotated": rotated,
            "environment_id": environment_id,
            "metadata": {}
        }

        # 7. Guardar en BD
        try:
            result = await db[database_name][service_tokens_coll].insert_one(token_doc)
            logger.info(f"✅ Token creado: {token_id}")
        except Exception as e:
            logger.error(f"Error guardando token: {e}")
            raise

        # 8. Retornar (token_secret visible UNA VEZ)
        return ServiceTokenCreateResponse(
            id=str(result.inserted_id),
            token_id=token_id,
            token_secret=token_value,  # ← Token original (mostrado UNA VEZ)
            name=name,
            description=description,
            scopes=scopes,
            project_id=project_id,
            owner_id=owner_id,
            created_at=now,
            expires_at=expires_at,
            last_used_at=None,
            request_count=0,
            status="active",
            is_active=True,
            environment_id=environment_id,
            warning="Guarda este token en un lugar seguro. No podrás verlo nuevamente."
        )


class ServiceTokenManager:
    """Valida, revoca, rota tokens de servicio"""

    @staticmethod
    async def validate_token(
        db: AsyncIOMotorClient,
        token_value: str,
        project_id: Optional[ObjectId] = None
    ) -> ServiceTokenInDB:
        """
        Valida token de servicio.

        Args:
            db: MongoDB client
            token_value: Token a validar (tok_...)
            project_id: Opcional, verificar que pertenece a proyecto

        Returns:
            ServiceTokenInDB si válido

        Raises:
            ValueError si token inválido, expirado, revocado
        """
        # 1. Calcular hash
        token_hash = hashlib.sha256(token_value.encode()).hexdigest()

        # 2. Buscar por hash (SIN descifrar token_secret)
        token_doc = await db[database_name][service_tokens_coll].find_one({
            "token_hash": token_hash,
            "is_active": True,
            "status": "active"
        })

        if not token_doc:
            logger.warning(f"Token inválido o revocado: {token_hash[:16]}...")
            raise ValueError("Token not found or revoked")

        # 3. Verificar expiración
        if token_doc.get("expires_at") < datetime.utcnow():
            logger.warning(f"Token expirado: {token_doc['token_id']}")
            raise ValueError("Token expired")

        # 4. Verificar proyecto si es requerido
        if project_id and token_doc["project_id"] != project_id:
            logger.warning(f"Token no pertenece a proyecto: {project_id}")
            raise ValueError("Token does not belong to this project")

        # 5. Actualizar último uso
        try:
            await db[database_name][service_tokens_coll].update_one(
                {"_id": token_doc["_id"]},
                {
                    "$set": {
                        "last_used_at": datetime.utcnow(),
                        "request_count": token_doc.get("request_count", 0) + 1
                    }
                }
            )
        except Exception as e:
            logger.error(f"Error actualizando uso del token: {e}")

        return _token_doc_to_in_db(token_doc)

    @staticmethod
    async def revoke_token(
        db: AsyncIOMotorClient,
        token_id: str,
        project_id: ObjectId,
        revoked_by: ObjectId,
        reason: str = "manual"
    ) -> None:
        """Revoca inmediatamente un token"""
        result = await db[database_name][service_tokens_coll].update_one(
            {
                "token_id": token_id,
                "project_id": project_id,
                "is_active": True
            },
            {
                "$set": {
                    "status": "revoked",
                    "is_active": False,
                    "revoked_at": datetime.utcnow(),
                    "revoked_by": revoked_by,
                    "revocation_reason": reason
                }
            }
        )

        if result.matched_count == 0:
            raise ValueError("Token not found or already revoked")

        logger.info(f"✅ Token revocado: {token_id}")

    @staticmethod
    async def rotate_token(
        db: AsyncIOMotorClient,
        token_id: str,
        project_id: ObjectId,
        rotated_by: ObjectId
    ) -> Tuple[str, str]:
        """
        Rota token: genera nuevo, marca antiguo para expiración.

        Returns:
            (token_id_nuevo, token_secret_nuevo)
        """
        # 1. Obtener token actual
        old_token = await db[database_name][service_tokens_coll].find_one({
            "token_id": token_id,
            "project_id": project_id,
            "is_active": True
        })

        if not old_token:
            raise ValueError("Token not found")

        # 2. Lógica nombre: si ya tiene "(rotated)", no agregar de nuevo
        old_name = old_token["name"]
        if "(rotated)" in old_name:
            new_name = old_name
            mark_rotated = True
        else:
            new_name = f"{old_name} (rotated)"
            mark_rotated = False

        # 3. Generar nuevo token con mismos permisos
        new_result = await ServiceTokenGenerator.generate_token(
            db=db,
            project_id=project_id,
            owner_id=old_token["owner_id"],
            name=new_name,
            scopes=old_token["scopes"],
            expires_in_days=90,
            rate_limit=old_token.get("rate_limit"),
            description=old_token.get("description"),
            rotated=mark_rotated,
            environment_id=old_token.get("environment_id")
        )

        # 4. Registrar rotación
        grace_until = datetime.utcnow() + timedelta(minutes=5)
        rotated_by_oid = ObjectId(rotated_by) if isinstance(rotated_by, str) else rotated_by

        rotation_doc = {
            "token_id": token_id,
            "old_token_hash": old_token["token_hash"],
            "new_token_hash": hashlib.sha256(new_result.token_secret.encode()).hexdigest(),
            "rotation_reason": "manual",
            "rotated_at": datetime.utcnow(),
            "rotated_by": rotated_by_oid,
            "grace_period_until": grace_until
        }

        await db[database_name]["service_token_rotations"].insert_one(rotation_doc)

        # 5. Revocar token antiguo inmediatamente
        await db[database_name][service_tokens_coll].update_one(
            {"_id": old_token["_id"]},
            {
                "$set": {
                    "status": "revoked",
                    "is_active": False,
                    "revoked_at": datetime.utcnow(),
                    "revoked_by": rotated_by_oid,
                    "revocation_reason": "rotated"
                }
            }
        )

        logger.info(f"✅ Token rotado: {token_id} → {new_result.token_id}")
        return new_result.token_id, new_result.token_secret

    @staticmethod
    async def list_tokens(
        db: AsyncIOMotorClient,
        project_id: ObjectId,
        limit: int = 100
    ) -> List[ServiceTokenResponse]:
        """Lista tokens activos de proyecto"""
        query = {
            "project_id": project_id,
            "is_active": True
        }

        tokens = await db[database_name][service_tokens_coll].find(query).sort(
            "created_at", -1
        ).limit(limit).to_list(None)

        return [ServiceTokenResponse(**t) for t in tokens]

    @staticmethod
    async def get_token_usage(
        db: AsyncIOMotorClient,
        token_id: str,
        project_id: ObjectId
    ) -> ServiceTokenUsage:
        """Obtiene estadísticas de uso"""
        token_doc = await db[database_name][service_tokens_coll].find_one({
            "token_id": token_id,
            "project_id": project_id
        })

        if not token_doc:
            raise ValueError("Token not found")

        return ServiceTokenUsage(
            request_count=token_doc.get("request_count", 0),
            last_used_at=token_doc.get("last_used_at"),
            last_used_by_ip=token_doc.get("last_used_by_ip"),
            requests_today=token_doc.get("request_count", 0),  # Simplificado
            requests_this_hour=0  # Simplificado
        )
