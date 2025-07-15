from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, status
from ....core.auth import get_current_user
from ....db.mongodb import AsyncIOMotorClient, get_database
from ....models.user import UserInDB
from ....services.vercel import secrets_mismatch

from ....services.vercel import (
    sync_to_vercel,
    get_targets_from_project
)
from ....services.project_members import (
    is_project_admin,
)
from ....services.environment import (
    update_environment_vercel_target,
)

router = APIRouter(tags=['vercel'])

@router.post("/sync/vercel/{project_id}/{slug}/", tags=["vercel"])
async def sync_secrets_to_vercel(
    slug: str = Path(..., min_length=1),
    project_id: str = Path(..., min_length=1),
    remove_missing_secrets: bool = Query(
        False,
        description="Remove secrets from Vercel that are not in the database",
    ),
    target_name: str = Query(
        False,
        description="The target name to sync secrets for."
    ),
    db: AsyncIOMotorClient = Depends(get_database),
    current_user: UserInDB = Depends(
        get_current_user)
):
    has_admin_permission = await is_project_admin(db, project_id, current_user.id)
    if not has_admin_permission:
        raise HTTPException(
            status_code=401, detail="Not have permissions to sync the vercel of this environment")
    try:
        vercel_environment_info = await sync_to_vercel(db, project_id, slug, remove_missing_secrets, target_name)
        if not vercel_environment_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No Vercel environment found for the given project and slug."
            )

        updated_target = await update_environment_vercel_target(
            db, vercel_environment_info.environmentId, [target_name] # type: ignore
        )
        if not updated_target:
            raise HTTPException(
                status_code=404,
                detail="Target update failed"
            )
        return vercel_environment_info

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error syncing with Vercel: {str(e)}"
        )

@router.get("/vercel/{project_id}/{slug}/mismatches", tags=["vercel"])
async def get_vercel_mismatches(
    slug: str = Path(..., min_length=1),
    project_id: str = Path(..., min_length=1),
    db: AsyncIOMotorClient = Depends(get_database),
    current_user: UserInDB = Depends(get_current_user)
):
    has_admin_permission = await is_project_admin(db, project_id, current_user.id)
    if not has_admin_permission:
        raise HTTPException(
            status_code=401, detail="Not have permissions to view mismatches for this environment"
        )
    try:
        mismatches = await secrets_mismatch(db, project_id, slug)
        return {"mismatches": mismatches}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching mismatches from Vercel: {str(e)}"
        )

@router.get("/vercel/{project_id}/{slug}/targets", tags=["vercel"])
async def get_vercel_targets(
    slug: str = Path(..., min_length=1),
    project_id: str = Path(..., min_length=1),
    db: AsyncIOMotorClient = Depends(get_database),
    current_user: UserInDB = Depends(get_current_user)
):
    has_admin_permission = await is_project_admin(db, project_id, current_user.id)
    if not has_admin_permission:
        raise HTTPException(
            status_code=401, detail="Not have permissions to view targets for this environment"
        )
    try:
        targets = await get_targets_from_project(db, project_id, slug)
        return {"targets": targets}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching targets from Vercel: {str(e)}"
        )
