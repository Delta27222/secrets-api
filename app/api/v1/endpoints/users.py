from typing import List, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Path, Query

from ....core.utils import create_aliased_response
from ....db.mongodb import AsyncIOMotorClient, get_database
from ....models.user import UserInDB
from ....services.users import get_or_create_user

router = APIRouter(tags=['users'])


@router.post("/auth/github", response_model=UserInDB)
async def auth_github(
    github_token: str = Header(
        None, alias='X-GitHub-Token', description="El token de acceso de GitHub"),
    db: AsyncIOMotorClient = Depends(get_database)
):
    if not github_token:
        raise HTTPException(status_code=400, detail="GitHub token is required")

    try:

        # Get or create user in DB
        user = await get_or_create_user(db, github_token)

        return create_aliased_response(user)
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Authentication failed: {str(e)}")
