from fastapi import APIRouter

from .endpoints.environments import router as environments_router
from .endpoints.organizations import router as organizations_router
from .endpoints.projects import router as projects_router
from .endpoints.users import router as users_router

router = APIRouter()
router.include_router(organizations_router)
router.include_router(projects_router)
router.include_router(environments_router)
router.include_router(users_router)
