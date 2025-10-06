import httpx
from typing import Dict, List, Optional
from motor.motor_asyncio import AsyncIOMotorClient

from ..models.environment import EnvironmentInDB, EnvironmentRenderData

from ..models.sync import SyncResponse
from ..core.logging import create_service_logger
from .environment import get_render_info, get_environment_by_slug
from ..core.config import environments_collection_name, RENDER_API_URL

collection_name = environments_collection_name

def format_render_env_vars(env_dict: Dict[str, str]) -> List[Dict[str, str]]:
    return [{"key": k, "value": v} for k, v in env_dict.items()]

async def sync_to_render(
    conn: AsyncIOMotorClient,
    project_id: str,
    slug: str
) -> Optional[SyncResponse]:
    """
    Sync environment variables to Render service for a given project.
    """
    # Step 1: Get environment document from database
    environment = await get_environment_by_slug(
        conn, project_id, slug
    )
    if environment is None:
        raise ValueError("Environment not found for the given project and slug.")

    # Step 2: Retrieve render metadata
    render_data = await get_render_info(conn, project_id, slug)

    if render_data is None:
        raise ValueError("Render data could not be retrieved.")

    # Step 3: Call internal function to sync to Render
    return await _sync_to_render(
        target_id=environment.id,
        environment=environment,
        render_data=render_data
    )

@create_service_logger("render", "sync_to_render", "environment")
async def _sync_to_render(
    target_id: str,
    environment: EnvironmentInDB,
    render_data: EnvironmentRenderData,
    ) -> Optional[SyncResponse]:
    """
    Internal function to sync environment variables to Render service.
    This is a placeholder for the actual implementation.
    """

    service_id = render_data.render_server_id
    token = render_data.render_token
    secrets = environment.secrets

    if not all([service_id, token, secrets]):
        raise ValueError("Incomplete render credentials or secrets.")

    # Step 2: Prepare request
    url = f"{RENDER_API_URL}/services/{service_id}/env-vars/"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    payload = format_render_env_vars(secrets)

    # Step 3: Make async request
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.put(url, json=payload, headers=headers)
            response.raise_for_status()
            return SyncResponse(
                code="success",
                environmentId=environment.id
            )

        except httpx.HTTPStatusError as exc:
            raise Exception(
                f"Render API returned error {exc.response.status_code}: {exc.response.text}"
            )
        except httpx.RequestError as exc:
            raise Exception(f"Render API request failed: {str(exc)}")
