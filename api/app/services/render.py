from typing import Dict, List, Optional

import httpx
from motor.motor_asyncio import AsyncIOMotorClient

from ..core.config import environments_collection_name, RENDER_API_URL

from ..models.environment import EnvironmentRenderData
from ..models.sync import SyncResponse

from .environment import get_render_info, get_environment_by_slug

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
    render_data_raw = await get_render_info(conn, project_id, slug)

    if not render_data_raw:
        raise ValueError("Render data could not be retrieved.")

    render_data = EnvironmentRenderData(**render_data_raw)

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
                yam=True,
                status_code=response.status_code,
            )

        except httpx.HTTPStatusError as exc:
            raise Exception(
                f"Render API returned error {exc.response.status_code}: {exc.response.text}"
            )
        except httpx.RequestError as exc:
            raise Exception(f"Render API request failed: {str(exc)}")