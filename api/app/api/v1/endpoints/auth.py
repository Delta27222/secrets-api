from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query

from ....core.config import GITHUB_ORG_NAME
from ....core.utils import create_aliased_response
from ....db.mongodb import AsyncIOMotorClient, get_database
from ....models.auth import TokenResponse
from ....models.user import UserInDB
from ....services import auth as auth_services
from ....services.github_org_validation import validate_user_in_github_org
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
        # Validate GitHub org membership before creating user
        if GITHUB_ORG_NAME:
            from github import Github
            gh = Github(github_token)
            gh_user = gh.get_user()

            is_member, message = await validate_user_in_github_org(
                github_token=github_token,
                org_name=GITHUB_ORG_NAME,
                github_username=gh_user.login
            )

            if not is_member:
                raise HTTPException(
                    status_code=403,
                    detail=f"No perteneces a la organización '{GITHUB_ORG_NAME}'. Contacta al administrador."
                )

        # Get or create user in DB
        user = await get_or_create_user(db, github_token)

        return create_aliased_response(user)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Authentication failed: {str(e)}")
