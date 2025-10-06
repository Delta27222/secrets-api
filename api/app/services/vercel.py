import httpx
from typing import Any, Dict, List, Optional
from motor.motor_asyncio import AsyncIOMotorClient

from app.models.environment import EnvironmentInDB, EnvironmentVercelData

from ..models.sync import SyncResponse, MismatchSecrets
from .environment import get_vercel_info, get_environment_by_slug
from ..core.config import environments_collection_name, VERCEL_API_URL
from ..core.logging import create_service_logger


collection_name = environments_collection_name

async def fetch_project_from_vercel(project_id: str, token: str) -> Optional[Dict[str, Any]]:
    """
    Fetch project details from Vercel using the project ID and token, to take the target from the first environment variable.
    """

    url = f"{VERCEL_API_URL}/{project_id}"
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient() as client:
        res = await client.get(url, headers=headers)

    if res.status_code == 404:
        return None
    res.raise_for_status()

    project_data = res.json()

    env = project_data.get("env")
    if not env or not isinstance(env, list) or len(env) == 0:
        return None

    target = env[0].get("target")
    if not target:
        return None

    return target

async def fetch_existing_vercel_envs(project_id: str, token: str) -> Dict[str, str]:
    url = f"{VERCEL_API_URL}/{project_id}/env"
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient() as client:
        res = await client.get(url, headers=headers)
        res.raise_for_status()
        data = res.json()
        return {env["key"]: env["id"] for env in data.get("envs", [])}


async def delete_vercel_env_var(project_id: str, env_id: str, token: str):
    url = f"{VERCEL_API_URL}/{project_id}/env/{env_id}"
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        res = await client.delete(url, headers=headers)
        res.raise_for_status()


def format_vercel_env_vars(env_dict: Dict[str, str], targets: List[str]) -> List[Dict[str, str]]:
    return [
        {
            "key": k,
            "value": v,
            "type": "encrypted",
            "target": targets
        }
        for k, v in env_dict.items()
    ] # type: ignore

async def sync_to_vercel(
    conn: AsyncIOMotorClient,
    project_id: str,
    slug: str,
    remove_missing: bool = False,
    target_name: str = ''
) -> Optional[SyncResponse]:
    """
    Sync environment variables to Vercel service for a given project.
    """
    # Step 1: Get environment document from database
    environment = await get_environment_by_slug(
        conn, project_id, slug
    )

    if environment is None:
        raise ValueError("Environment not found for the given project and slug.")

    # Step 2: Retrieve vercel metadata

    vercel_data = await get_vercel_info(conn, project_id, slug)

    if vercel_data is None:
        raise ValueError("Vercel data could not be retrieved.")

    return await _sync_to_vercel(
        target_id=environment.id,
        environment=environment,
        vercel_data=vercel_data,
        target_name=target_name,
        remove_missing=remove_missing
    )

@create_service_logger("vercel", "sync_to_vercel", "environment")
async def _sync_to_vercel(
    target_id: str,
    environment: EnvironmentInDB,
    vercel_data: EnvironmentVercelData,
    target_name: str,
    remove_missing: bool
) -> Optional[SyncResponse]:
    """
    Internal function to sync environment variables to Vercel service.
    This is a placeholder for the actual implementation.
    """
    proj_id = vercel_data.vercel_project_id
    token = vercel_data.vercel_token
    targets = [target_name]
    secrets = environment.secrets

    if not all([proj_id, token, targets, secrets]):
        raise ValueError("Incomplete Vercel credentials or secrets.")

    # Step 3: Synchronization
    url = f"{VERCEL_API_URL}/{proj_id}/env?upsert=true"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    payload = format_vercel_env_vars(secrets, targets) # type: ignore

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.post(url, json=payload, headers=headers)
            res.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise Exception(f"Vercel API error {exc.response.status_code}: {exc.response.text}")

    # Paso 3: Eliminar variables no sincronizadas
    if remove_missing:
        existing = await fetch_existing_vercel_envs(proj_id, token) # type: ignore
        missing_keys = set(existing.keys()) - set(secrets.keys())

        for key in missing_keys:
            await delete_vercel_env_var(proj_id, existing[key], token) # type: ignore

        return SyncResponse(
            code='success_removed_mismatched_secrets',
            environmentId=environment.id
        )
    else:
        return SyncResponse(
            code="success",
            environmentId=environment.id
        )

async def secrets_mismatch(
    conn: AsyncIOMotorClient,
    project_id: str,
    slug: str,
) -> Optional[MismatchSecrets]:
    """
    Check for mismatches between Vercel secrets and local environment variables.
    """
    # Step 1: Get environment document from database
    environment = await get_environment_by_slug(
        conn, project_id, slug
    )

    if environment is None:
        raise ValueError("Environment not found for the given project and slug.")

    # Step 2: Retrieve vercel metadata
    vercel_data = await get_vercel_info(conn, project_id, slug)

    if not vercel_data:
        raise ValueError("Vercel data could not be retrieved.")

    proj_id = vercel_data.vercel_project_id
    token = vercel_data.vercel_token
    secrets = environment.secrets

    if not proj_id or not token:
        raise ValueError("Vercel project ID or token is missing.")

    existing = await fetch_existing_vercel_envs(proj_id, token)
    missing_keys = set(existing.keys()) - set(secrets.keys())

    # Return a MismatchSecrets instance with the correct fields
    return MismatchSecrets(
        code='success',
        secretsMismatched=list(missing_keys)
    )

async def get_targets_from_project(
    conn: AsyncIOMotorClient,
    project_id: str,
    slug: str
) -> List[str]: # type: ignore
    """
    Retrieve the targets for a given Vercel project.
    """
    # Step 1: Get environment document from database
    environment = await get_environment_by_slug(
        conn, project_id, slug
    )

    if environment is None:
        raise ValueError("Environment not found for the given project and slug.")

    # Step 2: Retrieve vercel metadata
    vercel_data = await get_vercel_info(conn, project_id, slug)

    if not vercel_data:
        raise ValueError("Vercel data could not be retrieved.")

    vercel_project_id = vercel_data.vercel_project_id
    vercel_token = vercel_data.vercel_token
    if not vercel_project_id or not vercel_token:
        raise ValueError("Vercel project ID or token is missing.")

    # Step 3: fetch project from Vercel
    project_info = await fetch_project_from_vercel(vercel_project_id, vercel_token)
    if project_info is None:
        raise ValueError("Project not found in Vercel.")
    return project_info # type: ignore
