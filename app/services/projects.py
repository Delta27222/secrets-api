from typing import List, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

from ..core.config import database_name, projects_collection_name
from ..models.dbmodel import PyObjectId
from ..models.environment import EnvironmentCreate
from ..models.project import ProjectCreate, ProjectInDb, ProjectUpdate
from .environment import create_environment

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

    await create_environment(conn=conn, environment=dev_environment)
    await create_environment(conn=conn, environment=stg_environment)
    await create_environment(conn=conn, environment=prd_environment)
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
