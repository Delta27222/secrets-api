# Función auxiliar para convertir documentos de MongoDB a modelos Pydantic
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

from ..core.config import database_name, organizations_collection_name
from ..models.organization import Organization, OrganizationCreate

collection_name = organizations_collection_name


async def create_organization(conn: AsyncIOMotorClient, organization: OrganizationCreate) -> Organization:
    doc = await conn[database_name][collection_name].insert_one(organization.dict())
    new_organization = await conn[database_name][collection_name].find_one({"_id": doc.inserted_id})
    return Organization(id=str(new_organization["_id"]), name=new_organization["name"], slug=new_organization["slug"])


async def get_organization_by_id(conn: AsyncIOMotorClient, id: str) -> Optional[Organization]:
    doc = await conn[database_name][collection_name].find_one({"_id": ObjectId(id)})
    if doc:
        return Organization(id=str(doc["_id"]), name=doc["name"], slug=doc["slug"])
    return None


async def get_all_organizations(conn: AsyncIOMotorClient, limit: int = 100, offset: int = 0) -> List[Organization]:
    organizations = []
    async for doc in conn[database_name][collection_name].find().skip(offset).limit(limit):
        organizations.append(Organization(
            id=str(doc["_id"]), name=doc["name"], slug=doc["slug"]))
    return organizations


async def update_organization(conn: AsyncIOMotorClient, id: str, organization: OrganizationCreate) -> Optional[Organization]:
    result = await conn[database_name][collection_name].update_one(
        {"_id": ObjectId(id)},
        {"$set": organization.model_dump()}
    )
    if result.modified_count > 0:
        updated_doc = await conn[database_name][collection_name].find_one({"_id": ObjectId(id)})
        return Organization(id=str(updated_doc["_id"]), name=updated_doc["name"], slug=updated_doc["slug"])
    return None


async def delete_organization(conn: AsyncIOMotorClient, id: str) -> bool:
    result = await conn[database_name][collection_name].delete_one({"_id": ObjectId(id)})
    return result.deleted_count > 0
