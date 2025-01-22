from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, status

from ....core.auth import get_current_user
from ....core.utils import create_aliased_response
from ....db.mongodb import AsyncIOMotorClient, get_database
from ....models.environment import EnvironmentInDB, ManyEnvironmentsInResponse
from ....models.project import (
    ManyProjectsInResponse,
    Project,
    ProjectCreate,
    ProjectInDb,
    ProjectUpdate,
)
from ....models.project_member import ProjectMemberInDB, ProjectMemberInResponse
from ....models.user import UserInDB
from ....services.environment import (
    get_all_environments_by_project,
    get_environment_by_slug,
)
from ....services.organization_members import is_admin_for_organization
from ....services.project_members import (
    can_access_environment,
    get_project_member_by_user_id,
    get_project_members,
    is_project_admin,
)
from ....services.projects import (
    create_project,
    delete_project,
    get_all_projects,
    get_project_by_id,
    update_project,
)

router = APIRouter(tags=['projects'])


@router.post("/projects/", response_model=ProjectInDb, tags=["projects"], status_code=201)
async def create_new_project(
    project: ProjectCreate = Body(..., embed=True),
    db: AsyncIOMotorClient = Depends(get_database),
    current_user: UserInDB = Depends(
        get_current_user)
):
    if not await is_admin_for_organization(db, current_user.username, project.organization_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="No tienes permiso para crear proyectos en esta organización")

    dbproject = await create_project(db, project, project.organization_id, current_user.id)
    if not dbproject:
        raise HTTPException(
            status_code=400,
            detail="Failed to create project",
        )
    return dbproject


@router.get("/projects/{id}", response_model=ProjectInDb, tags=["projects"])
async def get_project(
    id: str = Path(..., min_length=1),
    db: AsyncIOMotorClient = Depends(get_database),
    current_user: UserInDB = Depends(
        get_current_user)
):
    dbproject = await get_project_by_id(db, id)
    if not await is_admin_for_organization(db, current_user.username, dbproject.organization_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="No tienes permiso para obtener el proyecto {id}")

    if not dbproject:
        raise HTTPException(
            status_code=404,
            detail=f"Project with id '{id}' not found",
        )
    return create_aliased_response(dbproject)


# View environments of project
# Only view name and slug
@router.get("/projects/{id}/environments", response_model=ManyEnvironmentsInResponse, tags=["environments"])
async def get_environments_by_project(
    id: str,
    limit: int = Query(20, gt=0),
    offset: int = Query(0, ge=0),
    db: AsyncIOMotorClient = Depends(get_database),
    current_user: UserInDB = Depends(
        get_current_user)
):
    dbproject = await get_project_by_id(db, id)
    if not dbproject:
        raise HTTPException(
            status_code=404,
            detail=f"Project with id '{id}' not found",
        )
    member = await get_project_member_by_user_id(db, id, current_user.id)
    if not member:
        raise HTTPException(status_code=status.HTTP_401_FORBIDDEN,
                            detail="No tienes permiso para ver los entornos de este proyecto, en esta organización")

    environments = await get_all_environments_by_project(db, id, limit, offset)
    return ManyEnvironmentsInResponse(environments=environments, environments_count=len(environments))


@router.get("/projects/{project_id}/members", response_model=List[ProjectMemberInResponse])
async def get_project_members_route(
    project_id: str,
    db: AsyncIOMotorClient = Depends(get_database),
    current_user: UserInDB = Depends(get_current_user)
) -> List[ProjectMemberInDB]:
    member = await get_project_member_by_user_id(db, project_id, current_user.id)
    if not member:
        raise HTTPException(status_code=status.HTTP_401_FORBIDDEN,
                            detail="No tienes permiso para ver los miembros")

    # if not await is_project_admin(db, project_id, current_user.id):
    #     raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
    #                         detail="No tienes permiso para ver los miembros")
    members = await get_project_members(db, project_id)
    return members


@router.get("/projects/{id}/{slug}", response_model=EnvironmentInDB, tags=["environments"])
async def get_environment_by_slug_route(
    slug: str = Path(..., min_length=1),
    id: str = Path(..., min_length=1),
    db: AsyncIOMotorClient = Depends(get_database),
    current_user: UserInDB = Depends(
        get_current_user)
):
    environment = await get_environment_by_slug(db, id, slug)

    if not environment:
        raise HTTPException(
            status_code=404, detail=f"Environment with slug '{slug}' in project {id} not found")

    can_read = await can_access_environment(db, environment.id, current_user.id)
    if not can_read:
        raise HTTPException(status_code=401, detail='User is not authorized')

    return environment


@router.put("/projects/{id}", response_model=Project, tags=["projects"])
async def update_project_route(
    id: str = Path(..., min_length=1),
    project: ProjectUpdate = Body(..., embed=True),
    db: AsyncIOMotorClient = Depends(get_database),
    current_user: UserInDB = Depends(
        get_current_user)
):
    dbproject = await get_project_by_id(db, id)
    if not dbproject:
        raise HTTPException(
            status_code=404,
            detail=f"Project with id '{id}' not found",
        )
    is_admin = await is_project_admin(db, dbproject.organization_id, current_user.id)
    if not is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="No tienes permiso para actualizar este proyecto")

    dbproject = await update_project(db, id, project)

    if not dbproject:
        raise HTTPException(
            status_code=404,
            detail=f"Project with id '{id}' not found or update failed",
        )
    return create_aliased_response(dbproject)


@router.delete("/projects/{id}", tags=["projects"], status_code=204)
async def delete_project_route(
    id: str = Path(..., min_length=1),
    db: AsyncIOMotorClient = Depends(get_database),
    current_user: UserInDB = Depends(
        get_current_user)
):
    dbproject = await get_project_by_id(db, id)
    if not dbproject:
        raise HTTPException(
            status_code=404,
            detail=f"Project with id '{id}' not found",
        )
    if not await is_admin_for_organization(db, current_user.username, dbproject.organization_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="No tienes permiso para eliminar un proyecto")

    if not await delete_project(db, id):
        raise HTTPException(
            status_code=404,
            detail=f"Project with id '{id}' not found",
        )
    return
