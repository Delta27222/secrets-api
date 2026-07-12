"""
Service Token authentication and authorization.

Valida service tokens (Bearer tok_...) y verifica scopes requeridos.
"""

from enum import Enum
from typing import List

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..db.mongodb import AsyncIOMotorClient, get_database
from ..models.service_token import ServiceTokenInDB
from ..services.service_tokens import ServiceTokenManager


class Scope(str, Enum):
    """Scopes disponibles para service tokens"""
    SECRETS_READ = "secrets:read"
    SECRETS_WRITE = "secrets:write"
    SECRETS_DELETE = "secrets:delete"
    ENVIRONMENTS_READ = "environments:read"
    ENVIRONMENTS_LIST = "environments:list"
    PROJECTS_READ = "projects:read"
    PROJECTS_LIST = "projects:list"
    ORG_READ = "org:read"
    # Scope de sistema: rotar llaves de encriptación (usado por Lambda Worker)
    KEYS_ROTATE = "keys:rotate"


service_token_bearer = HTTPBearer(
    scheme_name="ServiceToken",
    description="Service token: Bearer tok_...",
)


async def get_service_token_from_header(
    credentials: HTTPAuthorizationCredentials = Depends(service_token_bearer),
) -> str:
    """Extrae el token del header Authorization: Bearer tok_..."""
    return credentials.credentials


async def get_service_token(
    token_value: str = Depends(get_service_token_from_header),
    db: AsyncIOMotorClient = Depends(get_database)
) -> ServiceTokenInDB:
    """
    Valida que el service token sea válido y esté activo.

    Raises:
        HTTPException 401 si token inválido, expirado o revocado
    """
    try:
        token_data = await ServiceTokenManager.validate_token(db, token_value)
        return token_data
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error validating token: {str(e)}"
        )


def require_scope(*required_scopes: Scope):
    """
    Factory para crear dependencia que valida scopes requeridos.

    Uso:
        @router.get("/service/secrets")
        async def get_secrets(
            token: ServiceTokenInDB = Depends(require_scope(Scope.SECRETS_READ))
        ):
            ...
    """
    async def check_scope(
        token: ServiceTokenInDB = Depends(get_service_token)
    ) -> ServiceTokenInDB:
        token_scopes = set(token.scopes)
        required = {s.value for s in required_scopes}

        missing = required - token_scopes
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required scopes: {', '.join(missing)}"
            )

        return token

    return check_scope
