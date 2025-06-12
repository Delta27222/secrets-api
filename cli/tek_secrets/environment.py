import json
import os
from pathlib import Path
from typing import Annotated, Optional

import requests
import typer

from .core import auth
from .core.config import DEV_API_URL, PROD_API_URL
from .core.utils import (
    _get_env_variables_dict,
    _select_environment_id_by_project_id,
    _select_environment_slug_by_project_id,
    _select_organization,
    _select_project,
    _show_env_variables,
    get_environment_details,
    insert_environment_variables,
)

cli = typer.Typer()


def _parse_env_file(env_file_path: Path) -> dict:
    """
    Parse a .env file and convert it into a Python dictionary.

    Args:
        env_file_path (Path): Path to the .env file to be parsed

    Returns:
        dict: Dictionary containing key-value pairs from the .env file

    Notes:
        - Skips lines without '=' character
        - Removes surrounding quotes from values
        - Preserves everything after first '=' as the value
    """
    secrets = {}
    with env_file_path.open() as env_file:
        for line in env_file:
            if '=' in line:
                key, value = line.strip().split('=', 1)
                secrets[key] = value.strip('"')
    return secrets


@cli.command(name='get')
def get_env(
    organization_id: Optional[str] = typer.Option(
        None, "--org", "-o", help="Organization ID"),
    project_id: Optional[str] = typer.Option(
        None, "--project", "-p", help="Project ID"),
    env: Optional[str] = typer.Option(
        None, "--env", "-e", help="Project environment [dev, stg, prd, ...]"),
    output_env: Optional[Path] = typer.Option(
        None, "--output-env",
        help="Path to save the environment variables",
        file_okay=True,
        dir_okay=False,
        writable=True,
        resolve_path=True,
    ),
    dev: Optional[bool] = typer.Option(
        False, "--dev", "-d", help="Use Development environment"),
):
    """
    Retrieve secrets for a specific project environment.

    Args:
        organization_id (Optional[str]): Organization identifier
        project_id (Optional[str]): Project identifier
        env (Optional[str]): Target environment slug

    Behavior:
        - Requires authenticated session
        - If IDs not provided, interactively prompts for selection
        - Displays environment variables in readable format

    Raises:
        typer.Exit: If user is not authenticated
    """

    if dev:
        API_URL = DEV_API_URL
    else:
        API_URL = PROD_API_URL

    if not auth.is_authorized():
        typer.echo("❌ Not authenticated. Please login first.")
        raise typer.Exit(code=1)

    if not organization_id and not project_id:
        organization_id = _select_organization(dev=dev)

    if not project_id:
        project_id = _select_project(organization_id=organization_id, dev=dev)

    if not env:
        env = _select_environment_slug_by_project_id(
            project_id=project_id, dev=dev)

    env_vars = _get_env_variables_dict(project_id, env, dev=dev)

    typer.echo("🔍 Retrieved environment variables: \n")
    for key, value in env_vars.items():
        typer.echo(f"{key}={value}")

    typer.echo("")

    # Save to file if requested
    if output_env:
        try:
            with output_env.open('w') as f:
                for key, value in env_vars.items():
                    f.write(f"{key}={value}\n")
            typer.echo(f"✅ Environment variables saved to {output_env}")
        except IOError as e:
            typer.echo(f"❌ Error writing to {output_env}: {str(e)}")
            raise typer.Exit(code=1)


@cli.command(name='update')
def update_env(
    env_file: Annotated[Path,
                        typer.Option(
                            exists=True,
                            file_okay=True,
                            dir_okay=False,
                            writable=False,
                            readable=True,
                            resolve_path=True,
                            help="Path to .env file containing updated secrets"
                        )],
        env_slug: Optional[str] = typer.Option(
        None, "--env", "-e", help="Project environment slug [dev, stg, prd, ...]"),
        organization_id: Optional[str] = typer.Option(
            None, "--org", "-o", help="Organization ID"),
        project_id: Optional[str] = typer.Option(
            None, "--project", "-p", help="Project ID"),
        environment_id: Optional[str] = typer.Option(
            None, "--env-id", help="Environment ID (use when slug is not specified)"),
    dev: Optional[bool] = typer.Option(
        False, "--dev", "-d", help="Use Development environment"),
):
    """
    Update environment secrets using values from a .env file.

    Args:
        env_file (Path): Path to .env file containing updated secrets
        env_slug (Optional[str]): Environment identifier slug
        organization_id (Optional[str]): Organization identifier
        project_id (Optional[str]): Project identifier
        environment_id (Optional[str]): Direct environment ID

    Behavior:
        - Requires authenticated session
        - Parses provided .env file into key-value pairs
        - Updates specified environment with new secrets
        - Supports both interactive selection and direct ID specification

    Raises:
        typer.Exit: If authentication fails or update operation errors occur
    """
    if dev:
        API_URL = DEV_API_URL
    else:
        API_URL = PROD_API_URL

    if not auth.is_authorized():
        typer.echo("❌ Not authenticated. Please login first.")
        raise typer.Exit(code=1)

    if not organization_id and not project_id and not environment_id:
        organization_id = _select_organization(dev=dev)

    if not project_id and not environment_id:
        project_id = _select_project(organization_id=organization_id, dev=dev)

    if env_slug:
        environment = get_environment_details(project_id, env_slug, dev=dev)
        environment_id = environment['_id']
    if not environment_id:
        environment_id = _select_environment_id_by_project_id(
            project_id=project_id, dev=dev)

    # Convertir el archivo .env a un diccionario
    secrets_dict = _parse_env_file(env_file)

    # Construir el cuerpo de la petición
    body = {
        "environment": {
            "secrets": secrets_dict
        }
    }

    api_url = f"{API_URL}/v1/environments/{environment_id}"
    headers = {
        "X-GitHub-Token": auth.get_valid_token(),
        "Content-Type": "application/json"
    }

    try:
        response = requests.put(
            api_url, headers=headers, data=json.dumps(body))
        response.raise_for_status()
        typer.echo(f"✅ Environment successfully updated with new secrets.")
    except requests.RequestException as e:
        typer.echo(f"❌ Error updating environment: {str(e)}")
        raise typer.Exit(code=1)
