from fastapi import APIRouter

from .endpoints.auth import router as auth_router
from .endpoints.environments import router as environments_router
from .endpoints.membership import router as memberships_router
from .endpoints.organizations import router as organizations_router
from .endpoints.project_member import router as project_member_router
from .endpoints.projects import router as projects_router
from .endpoints.users import router as users_router
from .endpoints.render import router as render_router
from .endpoints.vercel import router as vercel_router
from .endpoints.logs import router as logs_router
from .endpoints.service_tokens import router as service_tokens_router
from .endpoints.service import router as service_router
from .endpoints.rotation import router as rotation_router
from .endpoints.system_tokens import router as system_tokens_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(organizations_router)
router.include_router(service_tokens_router)  # Incluir ANTES de projects para rutas específicas
router.include_router(service_router)  # Service endpoints (programmatic access)
router.include_router(rotation_router)  # Rotación interna (llamado por Lambda Worker)
router.include_router(system_tokens_router)  # Tokens de sistema (globales, admin)
router.include_router(projects_router)
router.include_router(environments_router)
router.include_router(users_router)
router.include_router(memberships_router)
router.include_router(project_member_router)
router.include_router(render_router)
router.include_router(vercel_router)
router.include_router(logs_router)
