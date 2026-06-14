import logging
from typing import Any, Dict, List, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.logging import create_service_logger

from ..models.environment import EnvironmentCreate, EnvironmentInDB, EnvironmentUpdate, EnvironmentRenderUpdate, EnvironmentRenderData, EnvironmentVercelUpdate, EnvironmentVercelData
from ..core.config import database_name, environments_collection_name
from ..core.mongo_query import id_query_value
from .secret_encryption import (
    encrypt_secrets as _encrypt_secrets_with_key,
    decrypt_secrets as _decrypt_secrets_with_key,
)
from .encryption_keys import get_key_manager

logger = logging.getLogger(__name__)

collection_name = environments_collection_name


def plain_secrets(encrypted_secrets: Dict[str, str]) -> Dict[str, Any]:
    return {k: "********" for k, v in encrypted_secrets.items()}

async def create_environment(conn: AsyncIOMotorClient, environment: EnvironmentCreate) -> EnvironmentInDB:
    environment_dict = environment.model_dump()
    project_id = environment_dict.get('project_id')

    # Encrypt secrets with project-specific key
    if environment_dict.get('secrets'):
        encrypted, metadata = await _encrypt_secrets_with_key(conn, environment_dict['secrets'], project_id)
        environment_dict['secrets'] = encrypted
        environment_dict['secrets_encryption'] = metadata
    else:
        environment_dict['secrets_encryption'] = None

    result = await conn[database_name][collection_name].insert_one(environment_dict)
    new_environment = await conn[database_name][collection_name].find_one({"_id": result.inserted_id})

    # Decrypt for response
    if new_environment.get('secrets'):
        new_environment['secrets'] = await _decrypt_secrets_with_key(conn, new_environment)

    return EnvironmentInDB(**new_environment)


async def get_environment_by_id(conn: AsyncIOMotorClient, id: str) -> Optional[EnvironmentInDB]:
    environment = await conn[database_name][collection_name].find_one({"_id": ObjectId(id)})
    if environment:
        # Decrypt using the key that was used to encrypt (encrypted_with_key_id)
        if environment.get('secrets'):
            environment['secrets'] = await _decrypt_secrets_with_key(conn, environment)
        return EnvironmentInDB(**environment)
    return None

# async def get_environment_by_slug(conn: AsyncIOMotorClient, project_id: str, slug: str) -> Optional[EnvironmentInDB]:
#     environment = await conn[database_name][collection_name].find_one({"slug": slug, "project_id": project_id})
#     if environment:
#         # Descifrar los secretos antes de devolverlos
#         environment['secrets'] = decrypt_secrets(environment['secrets'])
#         return EnvironmentInDB(**environment)
#     return None


async def get_environment_by_slug(conn: AsyncIOMotorClient, project_id: str, slug: str) -> Optional[EnvironmentInDB]:
    environment = await conn[database_name][collection_name].find_one(
        {"slug": slug, "project_id": id_query_value(project_id)}
    )
    if environment:
        if environment.get('secrets'):
            environment['secrets'] = await _decrypt_secrets_with_key(conn, environment)
        return await _get_environment_by_slug(environment['_id'], environment)
    return None

@create_service_logger("environment", "get_secrets_by_environment", "environment")
async def _get_environment_by_slug(target_id: str, environment: EnvironmentInDB) -> Optional[EnvironmentInDB]:
    return EnvironmentInDB(**environment)


async def _decrypt_single_field(conn: AsyncIOMotorClient, project_id: str, encrypted_value: str) -> Optional[str]:
    """Decrypt a single field using the project's active key."""
    if not encrypted_value:
        return None
    try:
        manager = get_key_manager()
        fernet = await manager.get_active_key(conn, project_id)
        return fernet.decrypt(encrypted_value.encode()).decode()
    except Exception as e:
        logger.error(f"Error decrypting field: {e}")
        return None


async def get_render_info(conn: AsyncIOMotorClient, project_id: str, slug: str) -> Optional[EnvironmentRenderData]:
    """
    Retrieves the render information for a specific environment.
    """
    try:
        environment = await get_environment_by_slug(
            conn, project_id, slug
        )

        if environment is None:
            raise ValueError("Environment not found for the given project and slug.")

        result = {
            "environment_id": str(environment.id),
            "render_token": await _decrypt_single_field(conn, project_id, environment.render_token) if environment.render_token else None,
            "render_server_id": await _decrypt_single_field(conn, project_id, environment.render_server_id) if environment.render_server_id else None,
        }
        return EnvironmentRenderData(**result)

    except Exception as e:
        logger.error(f"Error retrieving or decrypting render info: {e}")
        return None

async def get_vercel_info(conn: AsyncIOMotorClient, project_id: str, slug: str) -> Optional[EnvironmentVercelData]:
    """
    Retrieves the vercel information for a specific environment.
    """
    try:
        environment = await get_environment_by_slug(
            conn, project_id, slug
        )

        if environment is None:
            raise ValueError("Environment not found for the given project and slug.")

        result = {
            "environment_id": str(environment.id),
            "vercel_token": await _decrypt_single_field(conn, project_id, environment.vercel_token) if environment.vercel_token else None,
            "vercel_project_id": await _decrypt_single_field(conn, project_id, environment.vercel_project_id) if environment.vercel_project_id else None,
            "vercel_target": environment.vercel_target if environment.vercel_target else None,
        }
        return EnvironmentVercelData(**result)

    except Exception as e:
        logger.error(f"Error retrieving or decrypting vercel info: {e}")
        return None

# All envs are not decrypted.
# To decrypt a env must be call by specific id
async def get_all_environments(
    conn: AsyncIOMotorClient,
    project_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
) -> List[EnvironmentInDB]:
    query = {}
    if project_id:
        query["project_id"] = id_query_value(project_id)

    environments = []
    async for env in conn[database_name][collection_name].find(query).skip(offset).limit(limit):
        env['secrets'] = plain_secrets(env.get('secrets') or {})
        # env['secrets'] = {}
        environments.append(EnvironmentInDB(**env))
    return environments

# Ejemplo de función específica para obtener entornos por proyecto


async def get_all_environments_by_project(
    conn: AsyncIOMotorClient,
    project_id: str,
    limit: int = 100,
    offset: int = 0
) -> List[EnvironmentInDB]:
    return await get_all_environments(conn, project_id, limit, offset)


# async def update_environment(conn: AsyncIOMotorClient, id: str, environment: EnvironmentCreate) -> Optional[EnvironmentInDB]:
#     result = await conn[database_name][collection_name].update_one({"_id": ObjectId(id)}, {"$set": environment.model_dump()})
#     if result.modified_count == 1:
#         updated_environment = await conn[database_name][collection_name].find_one({"_id": ObjectId(id)})
#         return EnvironmentInDB(**updated_environment)
#     return None

@create_service_logger("environment", "update_environment", "environment")
async def update_environment(conn: AsyncIOMotorClient, target_id: str, environment: EnvironmentUpdate) -> Optional[EnvironmentInDB]:
    update_data = environment.model_dump(exclude_unset=True)

    # Get project_id from existing document to find the right key
    existing = await conn[database_name][collection_name].find_one({"_id": ObjectId(target_id)})
    if not existing:
        return None
    project_id = existing.get('project_id')

    # Encrypt secrets with project-specific key
    if update_data.get('secrets'):
        encrypted, metadata = await _encrypt_secrets_with_key(conn, update_data['secrets'], project_id)
        update_data['secrets'] = encrypted
        update_data['secrets_encryption'] = metadata

    result = await conn[database_name][collection_name].update_one({"_id": ObjectId(target_id)}, {"$set": update_data})
    if result.modified_count == 1:
        updated_environment = await conn[database_name][collection_name].find_one({"_id": ObjectId(target_id)})
        if updated_environment and updated_environment.get('secrets'):
            updated_environment['secrets'] = await _decrypt_secrets_with_key(conn, updated_environment)
        return EnvironmentInDB(**updated_environment) if updated_environment else None
    return None

#RENDER ACTIONS
async def _encrypt_single_fields(conn: AsyncIOMotorClient, project_id: str, data: dict) -> dict:
    """Encrypt individual string fields using the project's active key."""
    manager = get_key_manager()
    fernet = await manager.get_active_key(conn, project_id)
    encrypted = {}
    for k, v in data.items():
        if isinstance(v, str):
            encrypted[k] = fernet.encrypt(v.encode()).decode()
        else:
            encrypted[k] = v
    return encrypted


async def update_environment_render_fields(
    conn: AsyncIOMotorClient,
    id: str,
    render_data: EnvironmentRenderUpdate
) -> Optional[EnvironmentInDB]:
    """
    Updates or creates render-related fields for an environment.
    If a field is sent as None (null in JSON), it is ignored and not updated.
    """
    # Get project_id for key lookup
    existing = await conn[database_name][collection_name].find_one({"_id": ObjectId(id)})
    project_id = existing.get('project_id') if existing else None

    # Prepare the update payload, excluding unset fields
    update_payload = render_data.model_dump(exclude_unset=True)

    # Encrypt all values using project-specific key
    update_payload = await _encrypt_single_fields(conn, project_id, update_payload)

    set_fields: Dict[str, Any] = {
        k: v for k, v in update_payload.items() if v is not None
    }

    # If there are no fields to update, return the existing document
    if not set_fields:
        existing_env = await conn[database_name][collection_name].find_one({"_id": ObjectId(id)})
        return EnvironmentInDB(**existing_env) if existing_env else None

    mongo_update_operations = {"$set": set_fields}

    # Actualiza solo los campos render_*, sin cifrar
    result = await conn[database_name][collection_name].update_one(
        {"_id": ObjectId(id)},
        mongo_update_operations
    )

    # Update only the render_* fields, encrypting their values before saving
    if result.modified_count == 1:
        updated_environment = await conn[database_name][collection_name].find_one({"_id": ObjectId(id)})
        return EnvironmentInDB(**updated_environment) if updated_environment else None

    return None

#VERCEL ACTIONS

async def update_environment_vercel_fields(
    conn: AsyncIOMotorClient,
    id: str,
    vercel_data: EnvironmentVercelUpdate
) -> Optional[EnvironmentInDB]:
    """
    Updates or creates vercel-related fields for an environment.
    If a field is sent as None (null in JSON), it is ignored and not updated.
    """
    # Get project_id for key lookup
    existing = await conn[database_name][collection_name].find_one({"_id": ObjectId(id)})
    project_id = existing.get('project_id') if existing else None

    update_payload = vercel_data.model_dump(exclude_unset=True)

    # Encrypt all values using project-specific key
    update_payload = await _encrypt_single_fields(conn, project_id, update_payload)

    set_fields: Dict[str, Any] = {}

    # Only include fields that are not None for updating
    for field_name, value in update_payload.items():
        if value is not None:
            set_fields[field_name] = value

    mongo_update_operations: Dict[str, Dict[str, Any]] = {}
    if set_fields:
        mongo_update_operations["$set"] = set_fields

    # Always attempt the update if there are fields to set
    if mongo_update_operations:
        result = await conn[database_name][collection_name].update_one(
            {"_id": ObjectId(id)},
            mongo_update_operations
        )

    # Always retrieve the document after the update attempt, regardless of modified_count
    updated_environment_doc = await conn[database_name][collection_name].find_one({"_id": ObjectId(id)})

    if updated_environment_doc:
        updated_environment_doc['id'] = str(updated_environment_doc['_id'])
        return EnvironmentInDB(**updated_environment_doc)

    return None


async def update_environment_vercel_target(
    conn: AsyncIOMotorClient,
    id: str,
    vercel_target: List[str]
) -> bool:
    """
    Updates the vercel target for an environment.
    """

    updated_environment = await update_environment_vercel_fields(
        conn, id, EnvironmentVercelUpdate(vercel_target=vercel_target) # type: ignore
    )

    if updated_environment:
        return True
    return False

async def delete_environment(conn: AsyncIOMotorClient, id: str) -> bool:
    result = await conn[database_name][collection_name].delete_one({"_id": ObjectId(id)})
    return result.deleted_count == 1
