import base64
import hashlib
from typing import Any, Dict, List, Optional

from bson import ObjectId
from cryptography.fernet import Fernet
from motor.motor_asyncio import AsyncIOMotorClient

from ..core.config import SECRET_KEY, database_name, environments_collection_name
from ..models.dbmodel import PyObjectId
from ..models.environment import EnvironmentCreate, EnvironmentInDB, EnvironmentUpdate, EnvironmentRenderUpdate, EnvironmentRenderData, EnvironmentVercelUpdate, EnvironmentVercelData

collection_name = environments_collection_name

# Función auxiliar para cifrar un diccionario

# Generar una clave para el cifrado, en un entorno real, esta clave debería ser almacenada de manera segura
hash_object = hashlib.sha256(str(SECRET_KEY).encode())
key = base64.urlsafe_b64encode(hash_object.digest())
fernet = Fernet(key)


def encrypt_secrets(data: dict) -> dict:
    encrypted = {}
    for key, value in data.items():
        if isinstance(value, str):
            encrypted[key] = fernet.encrypt(value.encode()).decode()
        else:
            encrypted[key] = value  # Keep as is for any other type
    return encrypted

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
            "render_token": decrypt_secret(environment.render_token) if environment.render_token else None,
            "render_server_id": decrypt_secret(environment.render_server_id) if environment.render_server_id else None,
        }
        return EnvironmentRenderData(**result)

    except Exception as e:
        print(f"❌ Error retrieving or decrypting render info: {e}")
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
            "vercel_token": decrypt_secret(environment.vercel_token) if environment.vercel_token else None,
            "vercel_project_id": decrypt_secret(environment.vercel_project_id) if environment.vercel_project_id else None,
            "vercel_target": environment.vercel_target if environment.vercel_target else None,
        }
        return EnvironmentVercelData(**result)

    except Exception as e:
        print(f"❌ Error retrieving or decrypting vercel info: {e}")
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
        if updated_environment and updated_environment.get('secrets') is not None:
            updated_environment['secrets'] = decrypt_secrets(
                updated_environment['secrets'])
        return EnvironmentInDB(**updated_environment) if updated_environment else None
    return None

#RENDER ACTIONS
async def update_environment_render_fields(
    conn: AsyncIOMotorClient,
    id: str,
    render_data: EnvironmentRenderUpdate
) -> Optional[EnvironmentInDB]:
    """
    Updates or creates render-related fields for an environment.
    If a field is sent as None (null in JSON), it is ignored and not updated.
    """
    # Prepare the update payload, excluding unset fields
    update_payload = render_data.model_dump(exclude_unset=True)

    # Encrypt all values in the dictionary using encrypt_secrets function
    update_payload = encrypt_secrets(update_payload)

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

    update_payload = vercel_data.model_dump(exclude_unset=True)

    # Encrypt all values in the dictionary using encrypt_secrets function
    update_payload = encrypt_secrets(update_payload)

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
    print(f"🚀 -> 2222 vercel_target: {vercel_target}")

    updated_environment = await update_environment_vercel_fields(
        conn, id, EnvironmentVercelUpdate(vercel_target=vercel_target) # type: ignore
    )
    print(f"🚀 -> 33333 updated_environment: {updated_environment}")
    if updated_environment:
        return True
    return False

async def delete_environment(conn: AsyncIOMotorClient, id: str) -> bool:
    result = await conn[database_name][collection_name].delete_one({"_id": ObjectId(id)})
    return result.deleted_count == 1
