from typing import List, Optional

from bson import ObjectId
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient

from ..core.config import (
    database_name,
    organizations_collection_name,
    project_members_collection_name,
    projects_collection_name,
)
from ..models.project import ProjectInDb
from ..models.project_member import (
    ProjectMemberCreate,
    ProjectMemberInDB,
    ProjectMemberInResponse,
    ProjectMemberUpdate,
)
from .environment import get_environment_by_id
from .organization_members import is_admin_for_organization
from .organizations import get_organization_by_id
from .users import get_user_by_id

collection_name = project_members_collection_name


async def get_project_member_by_id(conn: AsyncIOMotorClient, id: str) -> ProjectMemberInDB:
    member = conn[database_name][project_members_collection_name].find_one({
        "_id": ObjectId(id)})
    if member:
        return ProjectMemberInDB(**member)
    return None


async def create_project_member(conn: AsyncIOMotorClient, project_member: ProjectMemberCreate) -> ProjectMemberInDB:
    project_member_dict = project_member.model_dump()
    user = await get_user_by_id(conn, project_member.user)
    if not user:
        raise HTTPException(
            status_code=404, detail=f"User with id '{project_member.user}' not found")

    result = await conn[database_name][collection_name].insert_one(project_member_dict)
    new_member = await conn[database_name][collection_name].find_one({"_id": result.inserted_id})
    return ProjectMemberInDB(**new_member)


async def update_project_member(conn: AsyncIOMotorClient, member_id: str, project_member: ProjectMemberUpdate) -> Optional[ProjectMemberInDB]:
    update_data = project_member.model_dump(exclude_unset=True)
    result = await conn[database_name][collection_name].update_one({"_id": ObjectId(member_id)}, {"$set": update_data})
    if result.modified_count == 1:
        updated_member = await conn[database_name][collection_name].find_one({"_id": ObjectId(member_id)})
        return ProjectMemberInDB(**updated_member)
    return None


async def get_project_member_by_user_id(conn: AsyncIOMotorClient, project_id: str, user_id: str) -> Optional[ProjectMemberInDB]:
    member = await conn[database_name][collection_name].find_one({"project": project_id, "user": user_id})
    print(member)
    if member:
        return ProjectMemberInDB(**member)
    return None


async def _get_project_by_id(conn: AsyncIOMotorClient, id: str) -> Optional[ProjectInDb]:
    project = await conn[database_name][projects_collection_name].find_one({"_id": ObjectId(id)})
    if project:
        # Si necesitas informacion de la organization, puede popularse aqui
        return ProjectInDb(**project)
    return None


# Returns boolean is project admin
# returns true if:
# user is org admin or owner
# user is project admin
async def is_project_admin(conn: AsyncIOMotorClient, project_id: str, user_id: str):
    project = await _get_project_by_id(conn, project_id)
    if not project:
        raise HTTPException(
            status_code=404, detail=f"Project with id '{project_id}' not found")

    organization = await get_organization_by_id(conn, project.organization_id)
    if not organization:
        raise HTTPException(
            status_code=404, detail=f"Organization with id '{project.organization_id}' not found")

    user_project_member = await get_project_member_by_user_id(conn, project_id, user_id)
    user = await get_user_by_id(conn, user_id)
    is_organization_admin = await is_admin_for_organization(conn, user.email, organization.id)
    return user_project_member is not None and (user_project_member.role in ["admin"] or is_organization_admin)


async def delete_project_member(conn: AsyncIOMotorClient, member_id: str) -> bool:
    result = await conn[database_name][collection_name].delete_one({"_id": ObjectId(member_id)})
    return result.deleted_count == 1


async def get_project_members(conn: AsyncIOMotorClient, project_id: str) -> List[ProjectMemberInResponse]:
    members = []
    data = conn[database_name][collection_name].find({"project": project_id})
    async for member in data:
        member['user'] = await get_user_by_id(conn, member['user'])
        member['project'] = await _get_project_by_id(conn, member['project'])
        members.append(ProjectMemberInResponse(**member))
    return members


async def get_project_member_by_environment_and_user(conn: AsyncIOMotorClient, environment_id: str, user_id: str):
    environment = await get_environment_by_id(conn, environment_id)
    if not environment:
        raise HTTPException(
            status_code=404, detail=f"Environment with id '{environment_id}' not found")

    project = await _get_project_by_id(conn, environment.project_id)
    if not project:
        raise HTTPException(
            status_code=404, detail=f"Project with id '{environment.project}' not found")

    user = await get_user_by_id(conn, user_id)
    if not user:
        raise HTTPException(
            status_code=404, detail=f"User with id '{user_id}' not found")

    project_member = await get_project_member_by_user_id(conn, project.id, user_id)
    return project_member


async def can_access_environment(conn: AsyncIOMotorClient, environment_id: str, user_id: str) -> bool:
    environment = await get_environment_by_id(conn, environment_id)
    if not environment:
        raise HTTPException(
            status_code=404, detail=f"Environment with id '{environment_id}' not found")

    project = await _get_project_by_id(conn, environment.project_id)
    if not project:
        raise HTTPException(
            status_code=404, detail=f"Project with id '{environment.project}' not found")

    user = await get_user_by_id(conn, user_id)
    if not user:
        raise HTTPException(
            status_code=404, detail=f"User with id '{user_id}' not found")

    # Verify if the user is admin for organization
    if await is_admin_for_organization(conn, user.email, project.organization_id):
        return True

    # Verify if user is project member
    project_member = await get_project_member_by_user_id(conn, project.id, user_id)
    if project_member:
        # All project member can read environment
        return project_member.role in ["admin", "collab", "viewer"]

    return False


async def can_update_environment(conn: AsyncIOMotorClient, environment_id: str, user_id: str) -> bool:
    environment = await get_environment_by_id(conn, environment_id)
    if not environment:
        raise HTTPException(
            status_code=404, detail=f"Environment with id '{environment_id}' not found")

    project = await _get_project_by_id(conn, environment.project_id)
    if not project:
        raise HTTPException(
            status_code=404, detail=f"Project with id '{environment.project}' not found")

    user = await get_user_by_id(conn, user_id)
    if not user:
        raise HTTPException(
            status_code=404, detail=f"User with id '{user_id}' not found")

    # Verify if the user is admin for organization
    if await is_admin_for_organization(conn, user.email, project.organization_id):
        return True

    # Verify if user is project member
    project_member = await get_project_member_by_user_id(conn, project.id, user_id)
    if project_member:
        # All project member can read environment
        return project_member.role in ["admin", "collab"]

    return False
