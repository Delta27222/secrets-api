import os
from typing import List, Optional

import httpx
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Path, Query

from app.models.auth import TokenResponse
from app.models.user import UserInDB

from ....core.utils import create_aliased_response
from ....db.mongodb import AsyncIOMotorClient, get_database
from ....models.user import UserInDB
from ....services import auth as auth_services
from ....services.users import get_or_create_user

router = APIRouter(
    tags=['auth'],
    prefix='/auth'
)


@router.get("/github/token", response_model=TokenResponse)
async def get_github_token(
    code: str = Query(..., description="GitHub Auth Code"),
):

    # Intercambiar código por token
    try:
        data = await auth_services.get_github_token(code)
        if data == None:
            raise HTTPException(
                status_code=400,
                detail="Cannot get access token from Github"
            )
        return TokenResponse(
            access_token=data["access_token"],
            token_type=data.get("token_type", "bearer"),
            scope=data.get("scope", "")
        )

    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"GitHub error: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Server Intern error: {str(e)}"
        )


@router.post("/github", response_model=UserInDB)
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
