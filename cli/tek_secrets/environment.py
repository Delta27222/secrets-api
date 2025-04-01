import json
from pathlib import Path
from typing import Annotated, Optional

import requests
import typer

from .auth import auth
from .config import API_URL
from .utils import (
    _select_environment_id_by_project_id,
    _select_environment_slug_by_project_id,
    _select_organization,
    _select_project,
    _show_env_variables,
    get_environment_details,
)

cli = typer.Typer()


def _parse_env_file(env_file_path: Path) -> dict:
    """
    Convierte un archivo .env en un diccionario Python.
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
        None, "--org", "-o", help="ID de la organización"),
    project_id: Optional[str] = typer.Option(
        None, "--project", "-p", help="ID del project"),
    env: Optional[str] = typer.Option(
        None, "--env", "-e", help="Entorno del project [dev, stg, prd, ...]")
):
    """
    Obtiene los secrets de un entoro especifico
    """
    if not auth.authorized:
        typer.echo("❌ No estás autenticado. Por favor, inicia sesión primero.")
        raise typer.Exit(code=1)

    if not organization_id and not project_id:
        organization_id = _select_organization()

    if not project_id:
        project_id = _select_project(organization_id=organization_id)

    if not env:
        env = _select_environment_slug_by_project_id(project_id=project_id)

    _show_env_variables(project_id, env)


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
                        ),
                        ],

        # env: str,
        env_slug: Optional[str] = typer.Option(
            None, "--env", "-e", help="Slug del Entorno del project. [dev, stg, prd, ...]"),

        organization_id: Optional[str] = typer.Option(
        None, "--org", "-o", help="ID de la organización"),
        project_id: Optional[str] = typer.Option(
            None, "--project", "-p", help="ID del project"),
        environment_id: Optional[str] = typer.Option(
            None, "--env-id", help="Id del Entorno del project. (usar en caso de que no indique slug)"),
):
    """
    Actualiza los secretos de un entorno específico usando el contenido de un archivo .env.
    """
    if not auth.authorized:
        typer.echo("❌ No estás autenticado. Por favor, inicia sesión primero.")
        raise typer.Exit(code=1)

    if not organization_id and not project_id and not environment_id:
        organization_id = _select_organization()

    if not project_id and not environment_id:
        project_id = _select_project(organization_id=organization_id)

    if env_slug:
        environment = get_environment_details(project_id, env_slug)
        environment_id = environment['_id']
    if not environment_id:
        environment_id = _select_environment_id_by_project_id(
            project_id=project_id)

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
        "X-GitHub-Token": auth.session.token['access_token'],
        "Content-Type": "application/json"
    }

    try:
        response = requests.put(
            api_url, headers=headers, data=json.dumps(body))
        response.raise_for_status()
        typer.echo(f"✅ Entorno actualizado con los nuevos secretos.")
    except requests.RequestException as e:
        typer.echo(f"❌ Error al actualizar el entorno: {str(e)}")
        raise typer.Exit(code=1)
