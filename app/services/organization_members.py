from typing import List, Optional

from bson import ObjectId
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient

from ..core.config import database_name, organization_members_collection_name
from ..models.organization import Organization, OrganizationCreate, OrganizationInDB
from ..models.organization_member import (
    MembershipStatus,
    OrganizationMember,
    OrganizationMemberCreate,
    OrganizationMemberInDB,
    OrganizationMemberInResponse,
    OrganizationMemberUpdate,
    OrganizationRole,
)
from .organizations import create_organization_member, get_organization_by_id
from .users import get_or_create_user, get_user_by_username

collection_name = organization_members_collection_name


async def is_admin_for_organization(db: AsyncIOMotorClient, username: str, organization_id: str) -> bool:
    member = await get_organization_member_by_username_and_org(db, username, organization_id)

    return member is not None and member.role in ["admin", "owner"] and member.status == MembershipStatus.accepted


async def get_organization_member_by_id(conn: AsyncIOMotorClient, id: str) -> Optional[OrganizationMemberInResponse]:
    member = await conn[database_name][collection_name].find_one({"_id": ObjectId(id)})
    if member:
        user = await get_user_by_username(conn, member.username)
        organization = await get_organization_by_id(conn, member.organization_id)
        return OrganizationMemberInResponse(
            **member.model_dump(),
            user=user if user else None,
            organization=organization
        )
    return None


async def get_all_organization_members(conn: AsyncIOMotorClient) -> List[OrganizationMemberInResponse]:
    members = []
    async for member in conn[database_name][collection_name].find():
        user = await get_user_by_username(conn, member.username)
        organization = await get_organization_by_id(conn, member.organization_id)
        members.append(OrganizationMemberInResponse(
            **member.model_dump(),
            user=user if user else None,
            organization=organization
        ))
    return members


async def update_organization_member(conn: AsyncIOMotorClient, id: str, member: OrganizationMemberUpdate) -> Optional[OrganizationMemberInDB]:
    update_data = member.model_dump(exclude_unset=True)
    result = await conn[database_name][collection_name].update_one({"_id": ObjectId(id)}, {"$set": update_data})
    if result.modified_count == 1:
        updated_member = await conn[database_name][collection_name].find_one({"_id": ObjectId(id)})
        user = await get_user_by_username(conn, updated_member.username)
        organization = await get_organization_by_id(conn, updated_member.organization_id)
    return OrganizationMemberInResponse(
        **updated_member,
        user=user if user else None,
        organization=organization
    )


async def delete_organization_member(conn: AsyncIOMotorClient, id: str) -> bool:
    result = await conn[database_name][collection_name].delete_one({"_id": ObjectId(id)})
    return result.deleted_count == 1


async def create_invitation(conn: AsyncIOMotorClient, organization_id: str, username: str, role: str) -> OrganizationMemberInDB:
    # Crear una nueva invitación
    if role == OrganizationRole.owner:
        raise HTTPException(
            status_code=400, detail='Cannot create an membership invitation as owner')
    member = OrganizationMemberCreate(
        organization_id=organization_id,
        username=username,
        role=role,
        status=MembershipStatus.pending
    )
    return await create_organization_member(conn, member)


async def accept_invitation(conn: AsyncIOMotorClient, member_id: str) -> Optional[OrganizationMemberInResponse]:
    # Aceptar una invitación existente
    update_data = OrganizationMemberUpdate(status=MembershipStatus.accepted)
    return await update_organization_member(conn, member_id, update_data)


async def get_organization_member_by_username_and_org(conn: AsyncIOMotorClient, username: str, organization_id: str) -> Optional[OrganizationMemberInResponse]:
    # Obtener el miembro de una organización específica para un usuario
    member = await conn[database_name][collection_name].find_one({
        "organization_id": organization_id,
        "username": username
    })
    if member:
        user = await get_user_by_username(conn, username)
        organization = await get_organization_by_id(conn, organization_id)
        return OrganizationMemberInResponse(
            **member,
            user=user if user else None,
            organization=organization
        )
    return None


async def get_all_organization_memberships_by_username(conn: AsyncIOMotorClient, username: str) -> List[OrganizationMemberInResponse]:
    # Obtener el usuario por su nombre de usuario
    user = await get_user_by_username(conn, username)
    if not user:
        return []

    memberships = []
    async for member in conn[database_name][collection_name].find({"username": username}):
        organization = await get_organization_by_id(conn, member['organization_id'])
        memberships.append(
            OrganizationMemberInResponse(
                **member,
                user=user,
                organization=organization if organization else None
            )
        )
    return memberships


async def get_organization_member_with_details(conn: AsyncIOMotorClient, member_id: str) -> Optional[OrganizationMemberInResponse]:
    member = await get_organization_member_by_id(conn, member_id)
    if member:
        user = await get_user_by_username(conn, member.username)
        organization = await get_organization_by_id(conn, member.organization_id)
        return OrganizationMemberInResponse(
            **member.model_dump(),
            user=user if user else None,
            organization=organization
        )
    return None


async def get_all_organization_memberships(conn: AsyncIOMotorClient, organization_id: str) -> List[OrganizationMemberInResponse]:
    memberships = []
    async for member in conn[database_name][collection_name].find({"organization_id": organization_id}):
        user = await get_user_by_username(conn, member['username'])
        organization = await get_organization_by_id(conn, organization_id)
        memberships.append(
            OrganizationMemberInResponse(
                **member,
                user=user if user else None,
                organization=organization
            )
        )
    return memberships
