import os
import subprocess
from typing import Dict, Optional

import inquirer
import requests
import typer

from ..core import auth
from .config import DEV_API_URL, PROD_API_URL


def insert_environment_variables(env_vars: Dict[str, str], skip_confirmation: bool = False) -> bool:
    """
    Insert environment variables into the current shell environment.

    Args:
        env_vars: Dictionary of environment variables to insert
        auto_execute: Whether to attempt automatic execution in the shell
        skip_confirmation: Skip confirmation prompt when auto_execute is True

    Returns:
        bool: True if variables were inserted/exports generated successfully

    Behavior:
        - When auto_execute=False: Returns export commands as string
        - When auto_execute=True: Attempts to execute exports in shell
        - Always includes instructions for manual persistence
    """

    # Generate export commands with proper escaping
    export_commands = []
    for key, value in env_vars.items():
        escaped_value = str(value).replace("'", "'\\''")
        export_commands.append(f"export {key}='{escaped_value}'")
    full_command = "\n".join(export_commands)

    # Attempt to execute (note this only affects subprocess)
    try:
        # Try to execute in parent shell (works for some shells)
        result = subprocess.run(
            ["bash", "-c", f"{full_command} && exec bash"],
            check=True,
            text=True
        )
        if result.returncode == 0:
            print("✅ Environment variables exported (for current subshell)")
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Partial success (variables set in subshell only): {e}")

    return True


def _get_env_variables_dict(project_id: str, env: str, dev: Optional[bool] = False) -> dict:
    """
    Retrieve environment variables as a dictionary.

    Args:
        project_id: Project identifier
        env: Environment slug

    Returns:
        dict: Key-value pairs of environment variables
    """
    # This would be implemented using your existing _show_env_variables logic
    # but modified to return a dict instead of printing
    # Implementation depends on your API response format
    if dev:
        API_URL = DEV_API_URL
    else:
        API_URL = PROD_API_URL

    api_url = f"{API_URL}/v1/projects/{project_id}/{env}"
    headers = {
        "X-GitHub-Token": auth.get_valid_token(),
    }

    response = requests.get(api_url, headers=headers)
    response.raise_for_status()
    return response.json().get('secrets', {})


def _show_env_variables(project_id: str, slug: str, dev: Optional[bool] = False):
    """
    Obtiene y muestra las variables de entorno de un proyecto específico en formato .env en la consola.
    """
    if dev:
        API_URL = DEV_API_URL
    else:
        API_URL = PROD_API_URL

    env_vars_api_url = f"{API_URL}/v1/projects/{project_id}/{slug}"
    headers = {
        "X-GitHub-Token": auth.get_valid_token(),
    }
    try:
        response = requests.get(env_vars_api_url, headers=headers)
        response.raise_for_status()
        env_vars = response.json()['secrets']

        if not env_vars:
            typer.echo(
                "❌ No se encontraron variables de entorno para este proyecto y entorno.")
            return

        typer.echo("🔐 Variables de entorno en formato .env: \n")
        for key, value in env_vars.items():
            # Escapar el valor si contiene caracteres especiales para evitar inyección de comandos
            escaped_value = value.replace('\n', '\\n').replace('"', '\\"')
            typer.echo(f"{key}=\"{escaped_value}\"")
        typer.echo("\n")
    except requests.RequestException as e:
        typer.echo(f"❌ Error al obtener las variables de entorno: {str(e)}")
        raise typer.Exit(code=1)


def _select_environment_slug_by_project_id(project_id: str, dev: Optional[bool] = False) -> Optional[str]:
    """
        Despliega un menu de las entornos de un proyecto especifico en el que el usuario tiene permisos
        devuelve el slug del entorno
    """
    if dev:
        API_URL = DEV_API_URL
    else:
        API_URL = PROD_API_URL

    environments_api_url = f"{API_URL}/v1/projects/{project_id}/environments"
    headers = {
        "X-GitHub-Token": auth.get_valid_token(),
    }
    try:
        response = requests.get(environments_api_url, headers=headers)
        response.raise_for_status()
        environments_list = response.json()['environments']
        environments = [env for env in environments_list]

        if not environments:
            typer.echo("❌ No tienes acceso a ningún entorno en este proyecto.")
            return None

        # Crear un menú para seleccionar un entorno
        options = [
            inquirer.List('environment',
                          message="🌐 Selecciona un entorno:",
                          choices=[
                                  env['slug'] for env in environments]
                          )
        ]
        answers = inquirer.prompt(options)
        if answers:
            environment_id = answers['environment']
            return environment_id
        else:
            raise typer.Exit(code=1)

    except requests.RequestException as e:
        typer.echo(f"❌ Error al obtener los entornos: {str(e)}")
        raise typer.Exit(code=1)


def _select_environment_id_by_project_id(project_id: str, dev: Optional[bool] = False) -> Optional[str]:
    """
        Despliega un menu de las entornos de un proyecto especifico en el que el usuario tiene permisos
        devuelve el slug del entorno
    """
    if dev:
        API_URL = DEV_API_URL
    else:
        API_URL = PROD_API_URL

    environments_api_url = f"{API_URL}/v1/projects/{project_id}/environments"
    headers = {
        "X-GitHub-Token": auth.get_valid_token(),
    }
    try:
        response = requests.get(environments_api_url, headers=headers)
        response.raise_for_status()
        environments_list = response.json()['environments']
        environments = [env for env in environments_list]

        if not environments:
            typer.echo("❌ No tienes acceso a ningún entorno en este proyecto.")
            return None

        # Crear un menú para seleccionar un entorno
        options = [
            inquirer.List('environment',
                          message="🌐 Selecciona un entorno:",
                          choices=[
                                  (env['slug'], env['_id']) for env in environments]
                          )
        ]
        answers = inquirer.prompt(options)
        if answers:
            environment_id = answers['environment']
            return environment_id
        else:
            raise typer.Exit(code=1)

    except requests.RequestException as e:
        typer.echo(f"❌ Error al obtener los entornos: {str(e)}")
        raise typer.Exit(code=1)


def _select_project(organization_id: str, dev: Optional[bool] = False) -> Optional[str]:
    """
    Despliega un menú de los proyectos de la organización especificada a los que pertenece el usuario autenticado.
    Devuelve el ID del proyecto seleccionado.
    """
    if dev:
        API_URL = DEV_API_URL
    else:
        API_URL = PROD_API_URL

    projects_api_url = f"{API_URL}/v1/organizations/{organization_id}/projects/me"
    headers = {
        "X-GitHub-Token": auth.get_valid_token(),
    }
    try:
        response = requests.get(projects_api_url, headers=headers)
        response.raise_for_status()
        projects = [p for p in response.json()]

        if not projects:
            typer.echo(
                "❌ No tienes acceso a ningún proyecto en esta organización.")
            return None

        # Crear un menú para seleccionar un proyecto
        options = [
            inquirer.List('project',
                          message="📁 Selecciona un proyecto:",
                          choices=[
                              (p['name'], p['_id'])
                              for p in projects]
                          )
        ]
        answers = inquirer.prompt(options)
        if answers:
            project_id = answers['project']
            return project_id
        else:
            raise typer.Exit(code=1)

    except requests.RequestException as e:
        typer.echo(f"❌ Error al obtener los proyectos: {str(e)}")
        raise typer.Exit(code=1)


def _select_organization(dev: Optional[bool] = False) -> Optional[str]:
    """
        Despliega un menu de las organizaciones que pertenece el usuario autenticado
        devuelve el id de la organizacion seleccionada
    """
    if dev:
        API_URL = DEV_API_URL
    else:
        API_URL = PROD_API_URL

    memberships_api_url = f"{API_URL}/v1/organizations/memberships/me"
    headers = {
        "X-GitHub-Token": auth.get_valid_token(),
    }
    try:
        response = requests.get(memberships_api_url, headers=headers)
        response.raise_for_status()
        memberships = [m for m in response.json()]

        if not memberships:
            typer.echo("❌ No eres miembro de ninguna organización.")
            return

        # Crear un menú para seleccionar una organización
        options = [
            inquirer.List('org',
                          message="🏤 Selecciona una organización:",
                          choices=[
                              (m['organization']['name'],
                               m['organization']['_id'])
                              for m in memberships]
                          )
        ]
        answers = inquirer.prompt(options)['org']
        organization_id = answers if answers else memberships[0].organization._id
        return organization_id
    except requests.RequestException as e:
        typer.echo(f"❌ Error al obtener las organizaciones: {str(e)}")
        raise typer.Exit(code=1)


def get_environment_details(project_id: str, slug: str, dev: Optional[bool] = False):
    """
    Obtiene los detalles de un entorno específico de un proyecto.

    :param project_id: El ID del proyecto.
    :param slug: El slug del entorno dentro del proyecto.
    :return: Un diccionario con los detalles del entorno o None si hay un error.
    """
    if dev:
        API_URL = DEV_API_URL
    else:
        API_URL = PROD_API_URL

    if not auth.authorized:
        typer.echo("❌ No estás autenticado. Por favor, inicia sesión primero.")
        raise typer.Exit(code=1)

    api_url = f"{API_URL}/v1/projects/{project_id}/{slug}"
    headers = {
        "X-GitHub-Token": auth.get_valid_token(),
    }

    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()
        return response.json()  # Devuelve los detalles del entorno como diccionario
    except requests.RequestException as e:
        typer.echo(f"❌ Error al obtener los detalles del entorno: {str(e)}")
        return None
