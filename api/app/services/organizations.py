from typing import List, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

from ..core.config import (
    database_name,
    organization_members_collection_name,
    organizations_collection_name,
    project_members_collection_name,
    projects_collection_name,
)
from ..models.organization import Organization, OrganizationCreate, OrganizationInDB
from ..models.organization_member import (
    MembershipStatus,
    OrganizationMemberCreate,
    OrganizationMemberInDB,
    OrganizationMemberInResponse,
    OrganizationRole,
)
from ..models.project import ProjectInDb
from .users import get_user_by_email

collection_name = organizations_collection_name


async def create_organization_member(conn: AsyncIOMotorClient, member: OrganizationMemberCreate) -> OrganizationMemberInDB:
    member_dict = member.model_dump()
    result = await conn[database_name][organization_members_collection_name].insert_one(member_dict)
    new_member = await conn[database_name][organization_members_collection_name].find_one({"_id": result.inserted_id})
    user = await get_user_by_email(conn, member.email)
    organization = await get_organization_by_id(conn, member.organization_id)
    return OrganizationMemberInResponse(
        **new_member,
        user=user if user else None,
        organization=organization
    )


async def create_organization(conn: AsyncIOMotorClient, organization: OrganizationCreate, owner_email: str) -> OrganizationInDB:
    doc = await conn[database_name][collection_name].insert_one(organization.model_dump())
    new_organization = await conn[database_name][collection_name].find_one({"_id": doc.inserted_id})
    organization_created = OrganizationInDB(**new_organization)
    # Create owner membership for organization
    membership_data = OrganizationMemberCreate(
        organization_id=organization_created.id,
        email=owner_email,
        role=OrganizationRole.owner,
        status=MembershipStatus.accepted
    )
    await create_organization_member(conn, membership_data)
    return organization_created


async def get_organization_by_id(conn: AsyncIOMotorClient, id: str) -> Optional[OrganizationInDB]:
    doc = await conn[database_name][collection_name].find_one({"_id": ObjectId(id)})
    if doc:
        return OrganizationInDB(**doc)
    return None


async def get_all_organizations(conn: AsyncIOMotorClient, limit: int = 100, offset: int = 0) -> List[OrganizationInDB]:
    organizations = []
    async for doc in conn[database_name][collection_name].find().skip(offset).limit(limit):
        organizations.append(OrganizationInDB(**doc))
    return organizations


async def update_organization(conn: AsyncIOMotorClient, id: str, organization: OrganizationCreate) -> Optional[OrganizationInDB]:
    result = await conn[database_name][collection_name].update_one(
        {"_id": ObjectId(id)},
        {"$set": organization.model_dump()}
    )
    updated_doc = await conn[database_name][collection_name].find_one({"_id": ObjectId(id)})
    return OrganizationInDB(**updated_doc)
    # if result.modified_count > 0:
    # return None


async def delete_organization(conn: AsyncIOMotorClient, id: str) -> bool:
    result = await conn.get_database(database_name).get_collection(collection_name).delete_one({"_id": ObjectId(id)})
    result_members = await conn.get_database(database_name).get_collection(organization_members_collection_name).delete_many({"organization_id": id})
    result_projects = await conn.get_database(database_name).get_collection(projects_collection_name).delete_many({"organization_id": id})
    result_project_members = await conn.get_database(database_name).get_collection(project_members_collection_name).delete_many({"organization_id": id})
    return result.deleted_count > 0
