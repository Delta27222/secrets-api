from typing import List, Optional

from bson import ObjectId
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient

from ..core.config import (
    database_name,
    project_members_collection_name,
    projects_collection_name,
)
from ..models.dbmodel import PyObjectId
from ..models.environment import EnvironmentCreate
from ..models.project import ProjectCreate, ProjectInDb, ProjectUpdate
from ..models.project_member import ProjectMemberCreate, ProjectRole
from .environment import create_environment
from .organization_members import is_admin_for_organization
from .project_members import create_project_member
from .users import get_user_by_email

collection_name = projects_collection_name


async def create_project(conn: AsyncIOMotorClient, project: ProjectCreate, organization_id: PyObjectId, creator_user_id: str) -> ProjectInDb:
    project_dict = project.model_dump()
    project_dict["organization_id"] = organization_id
    result = await conn[database_name][collection_name].insert_one(project_dict)
    new_project = await conn[database_name][collection_name].find_one({"_id": result.inserted_id})
    new_project = ProjectInDb(**new_project)

    # Create the default environments
    dev_environment = EnvironmentCreate(
        project_id=new_project.id, name='Development', slug='dev')
    stg_environment = EnvironmentCreate(
        project_id=new_project.id, name='Staging', slug='stg')
    prd_environment = EnvironmentCreate(
        project_id=new_project.id, name='Production', slug='prd')

    admin_project_member = ProjectMemberCreate(
        project=new_project.id, user=creator_user_id, role=ProjectRole.admin)
    try:
        await create_project_member(conn, project_member=admin_project_member)
    except Exception as e:
        raise HTTPException(
            status_code=400, detail='Cannot create project member for new project'
        )

    try:
        await create_environment(conn=conn, environment=dev_environment)
        await create_environment(conn=conn, environment=stg_environment)
        await create_environment(conn=conn, environment=prd_environment)
    except Exception as e:
        raise HTTPException(
            status_code=400, detail='Environments creation result in error for new project'
        )

    return new_project


async def get_project_by_id(conn: AsyncIOMotorClient, id: str) -> Optional[ProjectInDb]:
    project = await conn[database_name][collection_name].find_one({"_id": ObjectId(id)})
    if project:
        # Si necesitas informacion de la organization, puede popularse aqui
        return ProjectInDb(**project)
    return None


async def get_all_projects(conn: AsyncIOMotorClient) -> List[ProjectInDb]:
    projects = []
    async for project in conn[database_name][collection_name].find():
        projects.append(ProjectInDb(**project))
    return projects


async def update_project(conn: AsyncIOMotorClient, id: str, project: ProjectUpdate) -> Optional[ProjectInDb]:
    result = await conn[database_name][collection_name].update_one({"_id": ObjectId(id)}, {"$set": project.model_dump()})
    updated_project = await conn[database_name][collection_name].find_one({"_id": ObjectId(id)})
    return ProjectInDb(**updated_project)


async def delete_project(conn: AsyncIOMotorClient, id: str) -> bool:
    result = await conn[database_name][collection_name].delete_one({"_id": ObjectId(id)})
    return result.deleted_count == 1


async def get_projects_for_user_in_organization(conn: AsyncIOMotorClient, email: str, organization_id: str) -> List[ProjectInDb]:
    is_admin = await is_admin_for_organization(conn, email, organization_id)
    user = await get_user_by_email(conn, email)
    if is_admin:

        projects = []
        async for project in conn[database_name][projects_collection_name].find({"organization_id": organization_id}):
            projects.append(ProjectInDb(**project))
        return projects
    else:
        org_projects: List[ProjectInDb] = []
        async for project in conn[database_name][projects_collection_name].find({"organization_id": organization_id}):
            org_projects.append(ProjectInDb(**project))

        user_project_memberships_projects = await conn.get_database(database_name).get_collection(project_members_collection_name).find(
            {
                "user": user.id,
                "project": {
                    "$in": [project.id for project in org_projects]
                }
            },
            {
                "_id": 0,
                "project": 1
            }
        ).to_list(length=None)
        project_ids = [
            data['project'] for data in user_project_memberships_projects]

        projects = []

        if project_ids:
            db_projects = await conn[database_name][projects_collection_name].find({"_id": {"$in": [ObjectId(pid) for pid in project_ids]}}).to_list(length=None)
            for project in db_projects:
                projects.append(ProjectInDb(**project))
        return projects
