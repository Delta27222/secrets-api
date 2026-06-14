from typing import List, Optional

from bson import ObjectId
from fastapi import HTTPException
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.logging import create_service_logger

from ..core.config import (
    database_name,
    project_members_collection_name,
    projects_collection_name,
)
from ..core.mongo_query import id_query_value
from ..models.dbmodel import PyObjectId
from ..models.environment import EnvironmentCreate
from ..models.project import ProjectCreate, ProjectInDb, ProjectUpdate
from ..models.project_member import ProjectMemberCreate, ProjectRole
from .environment import create_environment
from .encryption_keys import initialize_project_encryption_key
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

    # Initialize encryption key for the project before creating environments
    try:
        await initialize_project_encryption_key(conn, project_id=new_project.id, created_by=creator_user_id)
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f'Cannot initialize encryption key for new project: {e}'
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
    return await _delete_project(id, result)

@create_service_logger("project", "delete_project", "project")
async def _delete_project(target_id: str, result) -> bool:
    return result.deleted_count == 1

async def get_projects_for_user_in_organization(conn: AsyncIOMotorClient, email: str, organization_id: str) -> List[ProjectInDb]:
    org_filter = {"organization_id": id_query_value(organization_id)}

    # Obtener el estado de administrador y el usuario de forma concurrente
    is_admin, user = await asyncio.gather(
        is_admin_for_organization(conn, email, organization_id),
        get_user_by_email(conn, email)
    )

    if not user:
        return []

    if is_admin:
        # Si el usuario es administrador, obtenemos todos los proyectos de la organización en una sola consulta
        projects = await conn[database_name][projects_collection_name].find(org_filter).to_list(length=None)
        return [ProjectInDb(**project) for project in projects]

    # Si el usuario no es administrador, obtenemos los proyectos asociados al usuario en una sola consulta
    # Primero, obtenemos los proyectos de la organización
    org_projects = await conn[database_name][projects_collection_name].find(org_filter).to_list(length=None)

    if not org_projects:
        return []

    org_project_ids = [str(p["_id"]) for p in org_projects]

    # Obtenemos los proyectos en los que el usuario está involucrado
    user_project_memberships_projects = await conn.get_database(database_name).get_collection(project_members_collection_name).find(
        {
            "user": user.id,
            "project": {
                "$in": org_project_ids
            }
        },
        {
            "_id": 0,
            "project": 1
        }
    ).to_list(length=None)

    # Extraemos los project_ids en los que el usuario está asociado
    user_project_ids = [data['project'] for data in user_project_memberships_projects]

    # Si el usuario tiene proyectos asignados, obtenemos estos proyectos de la base de datos
    if user_project_ids:
        db_projects = await conn[database_name][projects_collection_name].find({"_id": {"$in": [ObjectId(pid) for pid in user_project_ids]}}).to_list(length=None)
        return [ProjectInDb(**project) for project in db_projects]

    return []
