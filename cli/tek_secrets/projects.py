from typing import Optional

import requests
import typer

from .auth import auth
from .utils import (
    _select_environment_id_by_project_id,
    _select_environment_slug_by_project_id,
    _select_organization,
    _select_project,
    _show_env_variables,
)

cli = typer.Typer()


@cli.command(name='list')
def list_projects(
    organization_id: Optional[str] = typer.Option(
        None, "--org", "-o", help="ID de la organización")
):
    """
    Lista los proyectos del usuario autenticado. Si no se especifica una organización, se solicita una.
    """
    if not auth.authorized:
        typer.echo("❌ No estás autenticado. Por favor, inicia sesión primero.")
        raise typer.Exit(code=1)

    if not organization_id:
        organization_id = _select_organization()

    # Ajusta la URL según tu configuración de FastAPI para listar proyectos
    api_url = f"http://localhost:8000/v1/organizations/{organization_id}/projects/me"

    headers = {
        "X-GitHub-Token": auth.session.token['access_token']
    }

    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()
        projects = response.json()
        if not projects:
            typer.echo("❌ No se encontraron proyectos.")
        else:
            typer.echo("✅ Proyectos encontrados:")
            for project in projects:
                typer.echo(
                    f"* {project.get('name', 'Sin nombre')}")
    except requests.RequestException as e:
        typer.echo(f"❌ Error al listar los proyectos: {str(e)}")
