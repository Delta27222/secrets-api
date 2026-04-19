from typing import List, Optional

from bson import ObjectId
from fastapi import HTTPException
import asyncio
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
from .users import get_or_create_user, get_user_by_email

collection_name = organization_members_collection_name


async def is_admin_for_organization(db: AsyncIOMotorClient, email: str, organization_id: str) -> bool:
    member = await get_organization_member_by_email_and_org(db, email, organization_id)
    return member is not None and member.role in ["admin", "owner"] and member.status == MembershipStatus.accepted


async def get_organization_member_by_id(conn: AsyncIOMotorClient, id: str) -> Optional[OrganizationMemberInResponse]:
    member = await conn[database_name][collection_name].find_one({"_id": ObjectId(id)})
    if member:
        user = await get_user_by_email(conn, member['email'])
        organization = await get_organization_by_id(conn, member['organization_id'])
        return OrganizationMemberInResponse(
            **member,
            user=user if user else None,
            organization=organization
        )
    return None


async def get_all_organization_members(conn: AsyncIOMotorClient) -> List[OrganizationMemberInResponse]:
    members = []
    async for member in conn[database_name][collection_name].find():
        user = await get_user_by_email(conn, member['email'])
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
        user = await get_user_by_email(conn, updated_member['email'])
        organization = await get_organization_by_id(conn, updated_member['organization_id'])
    return OrganizationMemberInResponse(
        **updated_member,
        user=user if user else None,
        organization=organization
    )


async def delete_organization_member(conn: AsyncIOMotorClient, id: str) -> bool:
    result = await conn[database_name][collection_name].delete_one({"_id": ObjectId(id)})
    return result.deleted_count == 1


async def create_invitation(conn: AsyncIOMotorClient, organization_id: str, email: str, role: str) -> OrganizationMemberInDB:
    # Crear una nueva invitación
    if role == OrganizationRole.owner:
        raise HTTPException(
            status_code=400, detail='Cannot create an membership invitation as owner')
    member = OrganizationMemberCreate(
        organization_id=organization_id,
        email=email,
        role=role,
        status=MembershipStatus.pending
    )
    return await create_organization_member(conn, member)


async def accept_invitation(conn: AsyncIOMotorClient, member_id: str) -> Optional[OrganizationMemberInResponse]:
    # Aceptar una invitación existente
    update_data = OrganizationMemberUpdate(status=MembershipStatus.accepted)
    return await update_organization_member(conn, member_id, update_data)


async def get_organization_member_by_email_and_org(conn: AsyncIOMotorClient, email: str, organization_id: str) -> Optional[OrganizationMemberInResponse]:
    # Obtener el miembro de una organización específica para un usuario
    member = await conn[database_name][collection_name].find_one({
        "organization_id": organization_id,
        "email": email
    })
    if member:
        user = await get_user_by_email(conn, email)
        organization = await get_organization_by_id(conn, organization_id)
        return OrganizationMemberInResponse(
            **member,
            user=user if user else None,
            organization=organization
        )
    return None


async def get_all_organization_memberships_by_email(conn: AsyncIOMotorClient, email: str) -> List[OrganizationMemberInResponse]:
    # OPTIMIZACIÓN: usar patrón asyncio.gather como en get_all_organization_memberships
    user = await get_user_by_email(conn, email)
    if not user:
        return []

    members = await conn[database_name][collection_name].find({"email": email}).to_list(None)
    if not members:
        return []

    # Recopilar IDs de organizaciones únicas y traerlas en paralelo
    org_ids = list(set(m['organization_id'] for m in members))
    organizations_list = await asyncio.gather(
        *[get_organization_by_id(conn, oid) for oid in org_ids],
        return_exceptions=False
    )

    # Construir dict para lookup rápido
    org_dict = {str(o.id): o for o in organizations_list if o}

    # Mapear datos
    memberships = []
    for member in members:
        memberships.append(
            OrganizationMemberInResponse(
                **member,
                user=user,
                organization=org_dict.get(str(member['organization_id']))
            )
        )
    return memberships


async def get_organization_member_with_details(conn: AsyncIOMotorClient, member_id: str) -> Optional[OrganizationMemberInResponse]:
    # OPTIMIZACIÓN: get_organization_member_by_id ya carga user + org, no hacer double lookup
    return await get_organization_member_by_id(conn, member_id)


async def get_all_organization_memberships(conn: AsyncIOMotorClient, organization_id: str) -> List[OrganizationMemberInResponse]:
    memberships = []
    # Obtención de los miembros de la organización en una sola consulta
    members_cursor = conn[database_name][collection_name].find({"organization_id": organization_id})
    members = await members_cursor.to_list(length=None)  # Convertimos el cursor en una lista de miembros

    # Creamos una lista de tareas para obtener usuarios y organizaciones concurrentemente
    user_tasks = []
    organization_task = get_organization_by_id(conn, organization_id)  # Solo una consulta a la organización

    for member in members:
        user_tasks.append(get_user_by_email(conn, member['email']))

    # Ejecutamos todas las tareas concurrentemente
    users = await asyncio.gather(*user_tasks)  # Esperamos todas las tareas de usuarios

    # Obtenemos la organización (solo se necesita una vez)
    organization = await organization_task

    # Procesamos los miembros
    for member, user in zip(members, users):
        memberships.append(
            OrganizationMemberInResponse(
                **member,
                user=user if user else None,
                organization=organization
            )
        )
    return memberships