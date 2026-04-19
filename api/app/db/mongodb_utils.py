import logging
import asyncio

from motor.motor_asyncio import AsyncIOMotorClient

from ..core.config import (
    MAX_CONNECTIONS_COUNT,
    MIN_CONNECTIONS_COUNT,
    MONGODB_URL,
    database_name,
    users_collection_name,
    organizations_collection_name,
    projects_collection_name,
    environments_collection_name,
    project_members_collection_name,
    organization_members_collection_name,
)
from .mongodb import db

logger = logging.getLogger(__name__)


async def connect_to_mongo():
    logger.info("Start DB connection...")
    db.client = AsyncIOMotorClient(str(MONGODB_URL),
                                   maxPoolSize=MAX_CONNECTIONS_COUNT,
                                   minPoolSize=MIN_CONNECTIONS_COUNT)
    logger.info("✅ DB connection created")


async def close_mongo_connection():
    logger.info("Closing DB connection...")
    db.client.close()
    logger.info("✅ DB Client connection closed")


async def create_indexes():
    """Crear índices en MongoDB para mejorar performance."""
    if not db.client:
        logger.debug("MongoDB no está disponible. Saltando creación de índices.")
        return

    try:
        # Timeout de 5 segundos para evitar bloquear el startup
        await asyncio.wait_for(_create_indexes_internal(), timeout=5.0)
        logger.info("Índices de MongoDB creados exitosamente")

    except asyncio.TimeoutError:
        logger.warning("Timeout creando índices (MongoDB tardó >5s). Continuando sin esperar...")
    except Exception as e:
        logger.warning(f"No se pudieron crear índices: {e}. Continuando sin índices...")


async def _create_indexes_internal():
    """Lógica interna de creación de índices."""
    db_instance = db.client[database_name]

    # Índices para usuarios
    await db_instance[users_collection_name].create_index("email", unique=True)
    await db_instance[users_collection_name].create_index("username")

    # Índices para miembros de organización
    await db_instance[organization_members_collection_name].create_index([("email", 1), ("organization_id", 1)], unique=True)
    await db_instance[organization_members_collection_name].create_index("organization_id")
    await db_instance[organization_members_collection_name].create_index("email")

    # Índices para miembros de proyecto
    await db_instance[project_members_collection_name].create_index([("project", 1), ("user", 1)], unique=True)
    await db_instance[project_members_collection_name].create_index("project")
    await db_instance[project_members_collection_name].create_index("user")

    # Índices para ambientes
    await db_instance[environments_collection_name].create_index("project_id")
    await db_instance[environments_collection_name].create_index([("project_id", 1), ("slug", 1)], unique=True)

    # Índices para proyectos
    await db_instance[projects_collection_name].create_index("organization_id")
