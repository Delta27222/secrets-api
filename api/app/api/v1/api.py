from fastapi import APIRouter

from .endpoints.auth import router as auth_router
from .endpoints.environments import router as environments_router
from .endpoints.membership import router as memberships_router
from .endpoints.organizations import router as organizations_router
from .endpoints.project_member import router as project_member_router
from .endpoints.projects import router as projects_router
from .endpoints.users import router as users_router
from .endpoints.render import router as render_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(organizations_router)
router.include_router(projects_router)
router.include_router(environments_router)
router.include_router(users_router)
router.include_router(memberships_router)
router.include_router(project_member_router)
router.include_router(render_router)
