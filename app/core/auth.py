
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from github import Github

from ..core.config import database_name, users_collection_name
from ..db.mongodb import AsyncIOMotorClient, get_database
from ..models.user import UserInDB
from ..services.users import get_user_by_username

collection_name = users_collection_name


async def get_current_user(token: Optional[str] = Header(
        None, alias='X-GitHub-Token', description="El token de acceso de GitHub"), db: AsyncIOMotorClient = Depends(get_database)):
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="No se proporcionó el token de autenticación")
    github = Github(token)
    # Get user info from github
    try:
        github_user = github.get_user()
        # Seek user in db
        user = await db[database_name][collection_name].find_one({"username": github_user.login})
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")
        return UserInDB(**user)
    except Exception as e:
        raise ValueError(f"Error al obtener datos del usuario de GitHub: {e}")
