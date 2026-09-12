
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from github import Github

from ..core.config import database_name, users_collection_name
from ..core.context import request_context
from ..db.mongodb import AsyncIOMotorClient, get_database
from ..models.user import UserInDB
from ..services.users import get_or_create_user, get_user_by_username

collection_name = users_collection_name


def _remember_user_in_scope(user) -> None:
    """
    Deja el id del usuario autenticado en el scope ASGI para que el middleware de
    logging pueda auditar QUIÉN provocó un error sin repetir la consulta a Mongo.

    Se toma el request del ContextVar en vez de recibirlo por parámetro: FastAPI
    solo reconoce una anotación `Request` pelada, y añadirla a la firma rompía las
    llamadas directas a get_current_user desde core/logging.py.
    """
    try:
        request_context.get().scope["tek_user_id"] = str(getattr(user, "id", "") or "")
    except LookupError:
        pass  # fuera de una petición HTTP: no hay scope donde escribir


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
        # user = await db[database_name][collection_name].find_one({"username": github_user.login})
        user = await get_or_create_user(db, token)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")
        _remember_user_in_scope(user)
        return user
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")
