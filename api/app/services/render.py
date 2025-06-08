import httpx
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorClient

from .environment import get_render_info

from ..core.config import RENDER_API_URL

class RenderSyncResponse(BaseModel):
    code: str
    yam: bool
    status_code: int

def format_render_env_vars(env_dict: Dict[str, str]) -> List[Dict[str, str]]:
    return [{"key": k, "value": v} for k, v in env_dict.items()]


async def sync_to_render(
    conn: AsyncIOMotorClient,
    project_id: str,
    slug: str
) -> Optional[Dict[str, Any]]:
    """
    Sync environment variables to Render service for a given project.
    """
    # Step 1: Retrieve render metadata and secrets
    render_data = await get_render_info(conn, project_id, slug, sentSecrets=True)
    if not render_data:
        raise ValueError("Render data could not be retrieved.")

    service_id = render_data['render_server_id']
    token = render_data['render_token']
    secrets = render_data['secrets']

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
            return {
                "code": "success",
                "yam": True,
                "status_code": response.status_code,
            }

        except httpx.HTTPStatusError as exc:
            raise Exception(
                f"Render API returned error {exc.response.status_code}: {exc.response.text}"
            )
        except httpx.RequestError as exc:
            raise Exception(f"Render API request failed: {str(exc)}")