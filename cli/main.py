
import sys
import time
from itertools import cycle
from typing import Optional

import requests
import typer
from auth import auth
from environment import cli as env_commands
from projects import cli as projects_commands

APP_NAME = "tek_secrets"

cli = typer.Typer()
cli.add_typer(projects_commands, name='projects')
cli.add_typer(env_commands, name='env')


def loading_animation():
    spinner = cycle('|/-\\')
    for _ in range(10):
        typer.echo(f"\r⏳ Loading... {next(spinner)}", nl=False)
        time.sleep(0.1)
    typer.echo()


@cli.command()
def login():
    """Inicia sesión con GitHub y autentica contra la API de FastAPI."""
    try:
        global auth
        typer.echo("🔐 Flujo de autenticación con GitHub")
        loading_animation()

        auth = auth.auth_server()
        authorized = auth.authorized
        if authorized:
            typer.echo("🚀 User is authenticated")
            typer.echo(f"🔐 Token ${auth.session.token}")
        else:
            typer.echo("❌ Authentication flow failed")

        # Suponiendo que ya tienes el token de GitHub en auth.session.token después de auth.auth_server()
        github_token = auth.session.token['access_token'] if auth.session.token else "Nne"

        if not github_token:
            typer.echo("❌ No se obtuvo un token de GitHub")
            raise typer.Exit(code=1)

        # URL del endpoint de tu API FastAPI para autenticación con GitHub
        # Ajusta esta URL según tu configuración
        api_url = "http://localhost:8000/v1/auth/github"
        headers = {
            "X-GitHub-Token": github_token
        }

        response = requests.post(api_url, headers=headers)

        if response.status_code == 200:
            user_data = response.json()
            typer.echo(
                f"🚀 Usuario autenticado: Bienvenido, {user_data.get('username', 'Usuario')}!")
        else:
            typer.echo(
                f"❌ Error de autenticación: {response.status_code} - {response.text}")

    except Exception as e:
        typer.echo(f"❌ Error de autenticación: {e}")


@cli.command(name='user')
def get_user_info():
    """
    Obtiene y muestra la información del usuario actual.
    """
    if not hasattr(auth, 'session') or not auth.session.token:
        typer.echo("❌ No estás autenticado. Por favor, inicia sesión primero.")
        raise typer.Exit(code=1)

    # Ajusta la URL según tu configuración de FastAPI
    api_url = "http://localhost:8000/v1/auth/github"
    headers = {
        # Asumiendo que el token está en auth.session.token
        "X-GitHub-Token": auth.session.token['access_token']
    }

    try:
        response = requests.post(api_url, headers=headers)
        response.raise_for_status()  # Levanta una excepción si la petición no es exitosa

        user_data = response.json()
        typer.echo(f"ℹ️ Información del Usuario:")
        for key, value in user_data.items():
            typer.echo(f"* {key}: {value}")
    except requests.RequestException as e:
        typer.echo(f"❌ Error al obtener la información del usuario: {str(e)}")


@cli.command(name='logout')
def logout():
    """
    Cierra sesión eliminando el token de acceso guardado.
    """
    try:

        auth.logout()
        typer.echo("🔒 Has cerrado sesión exitosamente.")
    except Exception as e:
        typer.echo(f"❌ Error al cerrar sesión: {e}")


if __name__ == "__main__":
    cli()
