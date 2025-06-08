import base64
import hashlib
import httpx
from pydantic import BaseModel
from typing import Any, Dict, List, Optional #COMO PODEMOS GUARDAR TODA ESTA INFO DE ENCRIPTACION Y DEMAS EN OTRO LADO PARA NO REPERTIRLA, LA TENGO EN
from cryptography.fernet import Fernet         #EL SERVICE SE ENVIRONMENT TAMBIEN
from motor.motor_asyncio import AsyncIOMotorClient

from ..core.config import database_name, environments_collection_name, SECRET_KEY, RENDER_API_URL

from .environment import get_render_info

from ..models.environment import EnvironmentRenderData


collection_name = environments_collection_name

hash_object = hashlib.sha256(str(SECRET_KEY).encode())
key = base64.urlsafe_b64encode(hash_object.digest())
fernet = Fernet(key)

def decrypt_secrets(encrypted_secrets: Dict[str, str]) -> Dict[str, Any]:
    return {k: fernet.decrypt(v.encode()).decode() for k, v in encrypted_secrets.items()}

def format_render_env_vars(env_dict: Dict[str, str]) -> List[Dict[str, str]]:
    return [{"key": k, "value": v} for k, v in env_dict.items()]

class RenderSyncResponse(BaseModel): #DONDE PUDIERA COLOCAR ESTA CLASE???? para no tenerla aca
    code: str
    yam: bool
    status_code: int

async def sync_to_render(
    conn: AsyncIOMotorClient,
    project_id: str,
    slug: str
) -> Optional[Dict[str, Any]]:
    """
    Sync environment variables to Render service for a given project.
    """
    # Step 1: Get environment document from database
    environment = await conn[database_name][collection_name].find_one({
        "slug": slug,
        "project_id": project_id
    })
    # Step 2: Retrieve render metadata
    render_data_raw = await get_render_info(conn, project_id, slug)

    if not render_data_raw:
        raise ValueError("Render data could not be retrieved.")

    render_data = EnvironmentRenderData(**render_data_raw)

    service_id = render_data.render_server_id
    token = render_data.render_token
    secrets = decrypt_secrets(environment['secrets'])

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