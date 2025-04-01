from typing import Optional

import inquirer
import requests
import typer

from .auth import auth
from .config import API_URL


def _show_env_variables(project_id: str, slug: str):
    """
    Obtiene y muestra las variables de entorno de un proyecto específico en formato .env en la consola.
    """
    env_vars_api_url = f"{API_URL}/v1/projects/{project_id}/{slug}"
    headers = {
        "X-GitHub-Token": auth.session.token['access_token']
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


def _select_environment_slug_by_project_id(project_id: str) -> Optional[str]:
    """
        Despliega un menu de las entornos de un proyecto especifico en el que el usuario tiene permisos
        devuelve el slug del entorno
    """
    environments_api_url = f"{API_URL}/v1/projects/{project_id}/environments"
    headers = {
        "X-GitHub-Token": auth.session.token['access_token']
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


def _select_environment_id_by_project_id(project_id: str) -> Optional[str]:
    """
        Despliega un menu de las entornos de un proyecto especifico en el que el usuario tiene permisos
        devuelve el slug del entorno
    """
    environments_api_url = f"{API_URL}/v1/projects/{project_id}/environments"
    headers = {
        "X-GitHub-Token": auth.session.token['access_token']
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


def _select_project(organization_id: str) -> Optional[str]:
    """
    Despliega un menú de los proyectos de la organización especificada a los que pertenece el usuario autenticado.
    Devuelve el ID del proyecto seleccionado.
    """
    projects_api_url = f"{API_URL}/v1/organizations/{organization_id}/projects/me"
    headers = {
        "X-GitHub-Token": auth.session.token['access_token']
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


def _select_organization() -> Optional[str]:
    """
        Despliega un menu de las organizaciones que pertenece el usuario autenticado
        devuelve el id de la organizacion seleccionada
    """
    memberships_api_url = f"{API_URL}/v1/organizations/memberships/me"
    headers = {
        "X-GitHub-Token": auth.session.token['access_token']
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


def get_environment_details(project_id: str, slug: str):
    """
    Obtiene los detalles de un entorno específico de un proyecto.

    :param project_id: El ID del proyecto.
    :param slug: El slug del entorno dentro del proyecto.
    :return: Un diccionario con los detalles del entorno o None si hay un error.
    """
    if not auth.authorized:
        typer.echo("❌ No estás autenticado. Por favor, inicia sesión primero.")
        raise typer.Exit(code=1)

    api_url = f"{API_URL}/v1/projects/{project_id}/{slug}"
    headers = {
        "X-GitHub-Token": auth.session.token['access_token']
    }

    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()
        return response.json()  # Devuelve los detalles del entorno como diccionario
    except requests.RequestException as e:
        typer.echo(f"❌ Error al obtener los detalles del entorno: {str(e)}")
        return None
