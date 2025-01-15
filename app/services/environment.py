import base64
import hashlib
from typing import Any, Dict, List, Optional

from bson import ObjectId
from cryptography.fernet import Fernet
from motor.motor_asyncio import AsyncIOMotorClient

from ..core.config import SECRET_KEY, database_name, environments_collection_name
from ..models.dbmodel import PyObjectId
from ..models.environment import EnvironmentCreate, EnvironmentInDB

collection_name = environments_collection_name

# Función auxiliar para cifrar un diccionario

# Generar una clave para el cifrado, en un entorno real, esta clave debería ser almacenada de manera segura
hash_object = hashlib.sha256(str(SECRET_KEY).encode())
key = base64.urlsafe_b64encode(hash_object.digest())
fernet = Fernet(key)


def encrypt_secrets(secrets: Dict[str, Any]) -> Dict[str, str]:
    return {k: fernet.encrypt(str(v).encode()).decode() for k, v in secrets.items()}

# Función auxiliar para descifrar un diccionario


def decrypt_secrets(encrypted_secrets: Dict[str, str]) -> Dict[str, Any]:
    return {k: fernet.decrypt(v.encode()).decode() for k, v in encrypted_secrets.items()}


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
        env['secrets'] = decrypt_secrets(env['secrets'])
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


async def update_environment(conn: AsyncIOMotorClient, id: str, environment: EnvironmentCreate) -> Optional[EnvironmentInDB]:
    # Cifrar los nuevos secretos antes de actualizar
    update_data = environment.model_dump()
    update_data['secrets'] = encrypt_secrets(update_data['secrets'])
    result = await conn[database_name][collection_name].update_one({"_id": ObjectId(id)}, {"$set": update_data})
    if result.modified_count == 1:
        updated_environment = await conn[database_name][collection_name].find_one({"_id": ObjectId(id)})
        # Descifrar los secretos para la respuesta
        updated_environment['secrets'] = decrypt_secrets(
            updated_environment['secrets'])
        return EnvironmentInDB(**updated_environment)
    return None


async def delete_environment(conn: AsyncIOMotorClient, id: str) -> bool:
    result = await conn[database_name][collection_name].delete_one({"_id": ObjectId(id)})
    return result.deleted_count == 1
