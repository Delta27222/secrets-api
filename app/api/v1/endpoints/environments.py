from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query

from ....core.utils import create_aliased_response
from ....db.mongodb import AsyncIOMotorClient, get_database
from ....models.environment import (
    EnvironmentCreate,
    EnvironmentInDB,
    EnvironmentUpdate,
    ManyEnvironmentsInResponse,
)
from ....services.environment import (
    create_environment,
    delete_environment,
    get_all_environments,
    get_all_environments_by_project,
    get_environment_by_id,
    update_environment,
)

router = APIRouter(tags=['environments'])


@router.post("/environments/", response_model=EnvironmentInDB, tags=["environments"], status_code=201)
async def create_new_environment(
    environment: EnvironmentCreate = Body(..., embed=True),
    db: AsyncIOMotorClient = Depends(get_database),
):
    new_environment = await create_environment(db, environment)
    if not new_environment:
        raise HTTPException(
            status_code=400, detail="Failed to create environment")
    return new_environment


@router.get("/environments/{id}", response_model=EnvironmentInDB, tags=["environments"])
async def get_environment(
    id: str = Path(..., min_length=1),
    db: AsyncIOMotorClient = Depends(get_database),
):
    environment = await get_environment_by_id(db, id)
    if not environment:
        raise HTTPException(
            status_code=404, detail=f"Environment with id '{id}' not found")
    return environment


@router.get("/environments/", response_model=ManyEnvironmentsInResponse, tags=["environments"])
async def get_all_environments_route(
    project_id: Optional[str] = Query(
        None, description="ID del proyecto para filtrar entornos"),
    limit: int = Query(20, gt=0),
    offset: int = Query(0, ge=0),
    db: AsyncIOMotorClient = Depends(get_database),
):
    environments = await get_all_environments(db, project_id, limit, offset)
    return ManyEnvironmentsInResponse(environments=environments, environments_count=len(environments))


@router.put("/environments/{id}", response_model=EnvironmentInDB, tags=["environments"])
async def update_environment_route(
    id: str = Path(..., min_length=1),
    environment: EnvironmentUpdate = Body(..., embed=True),
    db: AsyncIOMotorClient = Depends(get_database),
):
    updated_environment = await update_environment(db, id, environment)
    if not updated_environment:
        raise HTTPException(
            status_code=404, detail=f"Environment with id '{id}' not found or update failed")
    return updated_environment


@router.delete("/environments/{id}", tags=["environments"], status_code=204)
async def delete_environment_route(
    id: str = Path(..., min_length=1),
    db: AsyncIOMotorClient = Depends(get_database),
):
    if not await delete_environment(db, id):
        raise HTTPException(
            status_code=404, detail=f"Environment with id '{id}' not found")
    return
