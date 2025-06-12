"""
Projects Management Module

This module provides CLI commands for managing projects within the Tek Secrets system.
Includes functionality for listing projects, viewing project details, and managing project environments.
"""
from typing import Optional

import requests
import typer

from .core import auth
from .core.config import DEV_API_URL, PROD_API_URL
from .core.utils import (
    _select_environment_id_by_project_id,
    _select_environment_slug_by_project_id,
    _select_organization,
    _select_project,
)

cli = typer.Typer()


@cli.command(name='list')
def list_projects(
    organization_id: Optional[str] = typer.Option(
        None, "--org", "-o", help="Organization ID"),
    dev: Optional[bool] = typer.Option(
        False, "--dev", "-d", help="Use Development environment"),
):
    """
    List all projects for the authenticated user.

    Args:
        organization_id (Optional[str]): The organization ID to filter projects.
                                        If not provided, user will be prompted to select one.

    Behavior:
        - Requires authenticated session
        - If no organization_id provided, prompts user to select one
        - Makes API request to fetch projects
        - Displays projects in list format

    Raises:
        typer.Exit: If user is not authenticated or no projects found
    """

    if dev:
        API_URL = DEV_API_URL
    else:
        API_URL = PROD_API_URL

    if not auth.is_authorized():
        typer.echo("❌ No estás autenticado. Por favor, inicia sesión primero.")
        raise typer.Exit(code=1)

    if not organization_id:
        organization_id = _select_organization()

    # Ajusta la URL según tu configuración de FastAPI para listar proyectos
    api_url = f"{API_URL}/v1/organizations/{organization_id}/projects/me"

    headers = {
        "X-GitHub-Token": auth.get_valid_token()
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


@cli.command(name='show')
def show_project(
    project_id: Optional[str] = typer.Option(
        None, "--project", "-p", help="Project ID"),
    dev: Optional[bool] = typer.Option(
        False, "--dev", "-d", help="Use Development environment"),
):
    """
    Display detailed information about a specific project.

    Args:
        project_id (Optional[str]): The project ID to view details.
                                   If not provided, user will be prompted to select one.

    Behavior:
        - Requires authenticated session
        - If no project_id provided, prompts user to select one
        - Makes API request to fetch project details
        - Displays project information

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

    if not project_id:
        organization_id = _select_organization()
        project_id = _select_project(organization_id=organization_id)

    # Ajusta la URL según tu configuración de FastAPI para mostrar un proyecto
    api_url = f"{API_URL}/v1/projects/{project_id}"

    headers = {
        "X-GitHub-Token": auth.get_valid_token(),
    }

    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()
        project = response.json()
        typer.echo(f"ℹ️ Project information:")
        for key, value in project.items():
            typer.echo(f"* {key}: {value}")
    except requests.RequestException as e:
        typer.echo(f"❌ Error retrieving project: {str(e)}")
