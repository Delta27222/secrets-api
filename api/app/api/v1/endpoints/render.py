from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, status
from ....core.auth import get_current_user
from ....db.mongodb import AsyncIOMotorClient, get_database
from ....models.user import UserInDB

from ....services.render import (
    sync_to_render,
)
from ....services.project_members import (
    can_update_environment,
    is_project_admin,
)

router = APIRouter(tags=['render'])

@router.post("/sync/render/{project_id}/{slug}/", tags=["render"])
async def sync_secrets_to_render(
    slug: str = Path(..., min_length=1),
    project_id: str = Path(..., min_length=1),
    db: AsyncIOMotorClient = Depends(get_database),
    current_user: UserInDB = Depends(
        get_current_user)
):
    has_admin_permission = await is_project_admin(db, project_id, current_user.id)
    if not has_admin_permission:
        raise HTTPException(
            status_code=401, detail="Not have permissions to sync the render of this environment")
    try:
        render_environment_info = await sync_to_render(db, project_id, slug)
        return render_environment_info
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error syncing with Render: {str(e)}"
        )