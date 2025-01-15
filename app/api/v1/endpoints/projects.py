from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query

from ....core.utils import create_aliased_response
from ....db.mongodb import AsyncIOMotorClient, get_database
from ....models.environment import ManyEnvironmentsInResponse
from ....models.project import (
    ManyProjectsInResponse,
    Project,
    ProjectCreate,
    ProjectInDb,
)
from ....services.environment import get_all_environments_by_project
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
):
    dbproject = await create_project(db, project, organization_id=project.organization_id)
    if not dbproject:
        raise HTTPException(
            status_code=400,
            detail="Failed to create project",
        )
    print(dbproject)
    return dbproject


@router.get("/projects/{id}", response_model=Project, tags=["projects"])
async def get_project(
    id: str = Path(..., min_length=1),
    db: AsyncIOMotorClient = Depends(get_database),
):
    dbproject = await get_project_by_id(db, id)
    if not dbproject:
        raise HTTPException(
            status_code=404,
            detail=f"Project with id '{id}' not found",
        )
    return create_aliased_response(Project(**dbproject))


@router.get("/projects/", response_model=ManyProjectsInResponse, tags=["projects"])
async def get_projects(
    limit: int = Query(20, gt=0),
    offset: int = Query(0, ge=0),
    db: AsyncIOMotorClient = Depends(get_database),
):
    dbprojects = await get_all_projects(db)
    return create_aliased_response(
        ManyProjectsInResponse(projects=dbprojects,
                               projects_count=len(dbprojects))
    )


@router.get("/projects/{id}/environments", response_model=ManyEnvironmentsInResponse, tags=["environments"])
async def get_environments_by_project(
    id: str,
    limit: int = Query(20, gt=0),
    offset: int = Query(0, ge=0),
    db: AsyncIOMotorClient = Depends(get_database),
):
    environments = await get_all_environments_by_project(db, id, limit, offset)
    return ManyEnvironmentsInResponse(environments=environments, environments_count=len(environments))


@router.put("/projects/{id}", response_model=Project, tags=["projects"])
async def update_project_route(
    id: str = Path(..., min_length=1),
    project: ProjectCreate = Body(..., embed=True),
    db: AsyncIOMotorClient = Depends(get_database),
):
    dbproject = await update_project(db, id, project)
    if not dbproject:
        raise HTTPException(
            status_code=404,
            detail=f"Project with id '{id}' not found or update failed",
        )
    return create_aliased_response(ProjectInDb(**dbproject))


@router.delete("/projects/{id}", tags=["projects"], status_code=204)
async def delete_project_route(
    id: str = Path(..., min_length=1),
    db: AsyncIOMotorClient = Depends(get_database),
):
    if not await delete_project(db, id):
        raise HTTPException(
            status_code=404,
            detail=f"Project with id '{id}' not found",
        )
    return
