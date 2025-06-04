import base64
import hashlib
from typing import Any, Dict, List, Optional

from bson import ObjectId
from cryptography.fernet import Fernet
from motor.motor_asyncio import AsyncIOMotorClient

from ..core.config import SECRET_KEY, database_name, environments_collection_name
from ..models.dbmodel import PyObjectId
from ..models.environment import EnvironmentCreate, EnvironmentInDB, EnvironmentUpdate, EnvironmentRenderUpdate, EnvironmentRenderData

collection_name = environments_collection_name

# Función auxiliar para cifrar un diccionario

# Generar una clave para el cifrado, en un entorno real, esta clave debería ser almacenada de manera segura
hash_object = hashlib.sha256(str(SECRET_KEY).encode())
key = base64.urlsafe_b64encode(hash_object.digest())
fernet = Fernet(key)


def encrypt_secrets(secrets: Dict[str, Any]) -> Dict[str, str]:
    return {k: fernet.encrypt(str(v).encode()).decode() for k, v in secrets.items()}

def encrypt_secret(value: str) -> str:
    return fernet.encrypt(value.encode()).decode()

# Función auxiliar para descifrar un diccionario

def decrypt_secrets(encrypted_secrets: Dict[str, str]) -> Dict[str, Any]:
    return {k: fernet.decrypt(v.encode()).decode() for k, v in encrypted_secrets.items()}

def decrypt_secret(encrypted_value: str) -> str:
    return fernet.decrypt(encrypted_value.encode()).decode()

def plain_secrets(encrypted_secrets: Dict[str, str]) -> Dict[str, Any]:
    return {k: "********" for k, v in encrypted_secrets.items()}


async def create_environment(conn: AsyncIOMotorClient, environment: EnvironmentCreate) -> EnvironmentInDB:
    environment_dict = environment.model_dump()
    environment_dict['secrets'] = encrypt_secrets(environment_dict['secrets'])
    result = await conn[database_name][collection_name].insert_one(environment_dict)
    new_environment = await conn[database_name][collection_name].find_one({"_id": result.inserted_id})
    new_environment['secrets'] = decrypt_secrets(new_environment['secrets'])
    return EnvironmentInDB(**new_environment)


async def get_environment_by_id(conn: AsyncIOMotorClient, id: str) -> Optional[EnvironmentInDB]:
    environment = await conn[database_name][collection_name].find_one({"_id": ObjectId(id)})
    if environment:
        # Descifrar los secretos antes de devolverlos
        environment['secrets'] = decrypt_secrets(environment['secrets'])
        return EnvironmentInDB(**environment)
    return None

async def get_environment_by_slug(conn: AsyncIOMotorClient, project_id: str, slug: str) -> Optional[EnvironmentInDB]:
    environment = await conn[database_name][collection_name].find_one({"slug": slug, "project_id": project_id})
    if environment:
        # Descifrar los secretos antes de devolverlos
        environment['secrets'] = decrypt_secrets(environment['secrets'])
        return EnvironmentInDB(**environment)
    return None

async def get_render_info(conn: AsyncIOMotorClient, project_id: str, slug: str, sentSecrets: bool) -> Optional[EnvironmentRenderData]:
    """
    Retrieves the render information for a specific environment.
    """
    try:
        environment = await conn[database_name][collection_name].find_one({
            "slug": slug,
            "project_id": project_id
        })

        if not environment:
            return None

        result = {
            "id": str(environment["_id"]),
            "render_token": decrypt_secret(environment["render_token"]) if environment.get("render_token") else None,
            "render_server_id": decrypt_secret(environment["render_server_id"]) if environment.get("render_server_id") else None,
        }

        if sentSecrets:
            result["secrets"] = decrypt_secrets(environment["secrets"]) if environment.get("secrets") else {}
        return result

    except Exception as e:
        print(f"❌ Error retrieving or decrypting render info: {e}")
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
        query["project_id"] = project_id

    environments = []
    async for env in conn[database_name][collection_name].find(query).skip(offset).limit(limit):
        env['secrets'] = plain_secrets(env['secrets'])
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


async def update_environment(conn: AsyncIOMotorClient, id: str, environment: EnvironmentCreate) -> Optional[EnvironmentInDB]:
    result = await conn[database_name][collection_name].update_one({"_id": ObjectId(id)}, {"$set": environment.model_dump()})
    if result.modified_count == 1:
        updated_environment = await conn[database_name][collection_name].find_one({"_id": ObjectId(id)})
        return EnvironmentInDB(**updated_environment)
    return None


async def update_environment(conn: AsyncIOMotorClient, id: str, environment: EnvironmentUpdate) -> Optional[EnvironmentInDB]:
    # Cifrar los nuevos secretos antes de actualizar
    update_data = environment.model_dump(exclude_unset=True)
    update_data['secrets'] = encrypt_secrets(update_data['secrets'])
    result = await conn[database_name][collection_name].update_one({"_id": ObjectId(id)}, {"$set": update_data})
    if result.modified_count == 1:
        updated_environment = await conn[database_name][collection_name].find_one({"_id": ObjectId(id)})
        # Descifrar los secretos para la respuesta
        updated_environment['secrets'] = decrypt_secrets(
            updated_environment['secrets'])
        return EnvironmentInDB(**updated_environment)
    return None

async def update_environment_render_fields(
    conn: AsyncIOMotorClient,
    id: str,
    render_data: EnvironmentRenderUpdate
) -> Optional[EnvironmentInDB]:
    """
    Updates or creates render-related fields for an environment.
    If a field is sent as None (null in JSON), it is ignored and not updated.
    """

    update_payload = render_data.model_dump(exclude_unset=True)

    # Encrypt all values in the dictionary using encrypt_secrets function
    update_payload = encrypt_secrets(update_payload)

    set_fields: Dict[str, Any] = {}

    # Only include fields that are not None for updating
    for field_name, value in update_payload.items():
        if value is not None:
            set_fields[field_name] = value

    # Prepare the MongoDB update operations
    mongo_update_operations: Dict[str, Dict[str, Any]] = {}
    if set_fields:
        mongo_update_operations["$set"] = set_fields

    # If there's nothing to update, return the existing document if it exists
    if not mongo_update_operations:
        existing_env = await conn[database_name][collection_name].find_one({"_id": ObjectId(id)})
        if existing_env:
            return EnvironmentInDB(**existing_env)
        return None  # No document found

    # Execute the update operation on MongoDB
    result = await conn[database_name][collection_name].update_one(
        {"_id": ObjectId(id)},  # Match the document by its ObjectId
        mongo_update_operations  # Apply $set operation
    )

    # If one document was modified, retrieve and return the updated version
    if result.modified_count == 1:
        updated_environment = await conn[database_name][collection_name].find_one({"_id": ObjectId(id)})
        if updated_environment:
            return EnvironmentInDB(**updated_environment)

    return None

async def delete_environment(conn: AsyncIOMotorClient, id: str) -> bool:
    result = await conn[database_name][collection_name].delete_one({"_id": ObjectId(id)})
    return result.deleted_count == 1
