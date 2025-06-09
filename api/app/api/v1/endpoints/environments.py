from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query

from ....core.auth import get_current_user
from ....core.utils import create_aliased_response
from ....db.mongodb import AsyncIOMotorClient, get_database
from ....models.environment import (
    EnvironmentCreate,
    EnvironmentInDB,
    EnvironmentUpdate,
    EnvironmentRenderUpdate,
    ManyEnvironmentsInResponse,
)
from ....models.user import UserInDB
from ....services.environment import (
    create_environment,
    delete_environment,
    get_all_environments,
    get_all_environments_by_project,
    get_environment_by_id,
    update_environment,
    update_environment_render_fields,
)
from ....services.project_members import (
    can_access_environment,
    can_update_environment,
    is_project_admin,
)

router = APIRouter(tags=['environments'])


@router.post("/environments/", response_model=EnvironmentInDB, tags=["environments"], status_code=201)
async def create_new_environment(
    environment: EnvironmentCreate = Body(..., embed=True),
    db: AsyncIOMotorClient = Depends(get_database),
    current_user: UserInDB = Depends(
        get_current_user)
):
    has_admin_permission = await is_project_admin(db, environment.project_id, current_user.id)
    if not has_admin_permission:
        raise HTTPException(
            status_code=401, detail="Not have permissions to create environment")

    new_environment = await create_environment(db, environment)
    if not new_environment:
        raise HTTPException(
            status_code=400, detail="Failed to create environment")
    return new_environment


@router.get("/environments/{id}", response_model=EnvironmentInDB, tags=["environments"])
async def get_environment(
    id: str = Path(..., min_length=1),
    db: AsyncIOMotorClient = Depends(get_database),
    current_user: UserInDB = Depends(
        get_current_user)
):
    can_read = await can_access_environment(db, id, current_user.id)
    if not can_read:
        raise HTTPException(status_code=401, detail='User is not authorized')

    environment = await get_environment_by_id(db, id)
    if not environment:
        raise HTTPException(
            status_code=404, detail=f"Environment with id '{id}' not found")
    return environment


@router.put("/environments/{id}", response_model=EnvironmentInDB, tags=["environments"])
async def update_environment_route(
    id: str = Path(..., min_length=1),
    environment: EnvironmentUpdate = Body(..., embed=True),
    db: AsyncIOMotorClient = Depends(get_database),
    current_user: UserInDB = Depends(
        get_current_user)
):
    can_update = await can_update_environment(db, id, current_user.id)
    if not can_update:
        raise HTTPException(
            status_code=401, detail="Not have permissions to update environment")

    updated_environment = await update_environment(db, id, environment)
    if not updated_environment:
        raise HTTPException(
            status_code=404, detail=f"Environment with id '{id}' not found or update failed")
    return updated_environment

@router.patch("/environments/{id}/render", response_model=EnvironmentInDB, tags=["environments"])
async def update_environment_render_route(
    id: str = Path(..., min_length=1),
    render_data: EnvironmentRenderUpdate = Body(..., embed=True),
    db: AsyncIOMotorClient = Depends(get_database),
    current_user: UserInDB = Depends(get_current_user)
):
    can_update = await can_update_environment(db, id, current_user.id)
    if not can_update:
        raise HTTPException(
            status_code=401, detail="Not have permissions to update environment render settings")

    # Llama a una nueva función de servicio o adapta la existente
    updated_environment = await update_environment_render_fields(db, id, render_data)
    if not updated_environment:
        raise HTTPException(
            status_code=404, detail=f"Environment with id '{id}' not found or render update failed")

    return updated_environment

@router.delete("/environments/{id}", tags=["environments"], status_code=204)
async def delete_environment_route(
    id: str = Path(..., min_length=1),
    db: AsyncIOMotorClient = Depends(get_database),
    current_user: UserInDB = Depends(
        get_current_user)
):

    environment = await get_environment_by_id(db, id)
    has_admin_permission = await is_project_admin(db, environment.project_id, current_user.id)
    if not has_admin_permission:
        raise HTTPException(
            status_code=401, detail="Not have permissions to create environment")

    if not await delete_environment(db, id):
        raise HTTPException(
            status_code=404, detail=f"Environment with id '{id}' not found")
    return
