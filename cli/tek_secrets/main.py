
import sys
import time
import urllib
import webbrowser
from itertools import cycle
from typing import Optional

import requests
import typer

from tek_secrets.core.config import DEV_API_URL, PROD_API_URL

from .core import auth
from .core.auth import (
    REDIRECT_URI,
    exchange_code_for_token,
    get_github_auth_code,
    run_server,
)

# from .core.config import API_URL, CLIENT_ID, GITHUB_AUTH_URL
from .environment import cli as env_commands
from .projects import cli as projects_commands

APP_NAME = "tek_secrets"

app = typer.Typer()
app.add_typer(projects_commands, name='projects')
app.add_typer(env_commands, name='env')


def loading_animation():
    spinner = cycle('|/-\\')
    for _ in range(10):
        typer.echo(f"\r⏳ Loading... {next(spinner)}", nl=False)
        time.sleep(0.1)
    typer.echo()


@app.command()
def login(
    dev: Optional[bool] = typer.Option(
        False, "--dev", "-d", help="Use Development environment"),
):
    """
    Authenticate with GitHub and authorize against Tek Secrets

    This command:
    1. Initiates GitHub OAuth flow
    2. Retrieves GitHub access token
    3. Authenticates with the Tek Secrets API using the GitHub token
    4. Displays authentication status and user information

    Raises:
        typer.Exit: If GitHub token retrieval fails
    """
    if dev:
        API_URL = DEV_API_URL
    else:
        API_URL = PROD_API_URL

    try:
        typer.echo("🔐 Authentication Flow with GitHub")
        loading_animation()
        authorized = auth.is_authorized()
        if authorized:
            github_token = auth.get_valid_token()
        else:
            auth_code = get_github_auth_code()
            github_token = exchange_code_for_token(auth_code, dev=dev)

        if not github_token:
            typer.echo("❌ Failed to obtain GitHub token.")
            raise typer.Exit(code=1)

        # Validate organization membership via API
        api_url = f"{API_URL}/v1/auth/github"
        headers = {
            "X-GitHub-Token": github_token
        }

        response = requests.post(api_url, headers=headers)

        if response.status_code == 200:
            user_data = response.json()
            typer.echo(
                f"✅ User authenticated: Welcome, {user_data.get('username', 'User')}!")
        elif response.status_code == 403:
            auth.clear_stored_token()
            typer.echo(
                "❌ Access denied: you are not a member of the required organization.")
            raise typer.Exit(code=1)
        else:
            typer.echo(
                f"❌ Authentication error: {response.status_code} - {response.text}")

    except typer.Exit:
        raise
    except Exception as e:
        typer.echo(f"❌ Authentication error: {e}")


@app.command(name='user')
def get_user_info(dev: Optional[bool] = typer.Option(
        False, "--dev", "-d", help="Use Development environment"),):
    """
    Retrieve and display information about the currently authenticated user.

    Requires:
        - Active authentication session (user must be logged in)

    Outputs:
        - User information in key-value format
        - Error message if not authenticated or request fails

    """

    if dev:
        API_URL = DEV_API_URL
    else:
        API_URL = PROD_API_URL

    if not auth.is_authorized():
        typer.echo("❌ No estás autenticado. Por favor, inicia sesión primero.")
        raise typer.Exit(code=1)

    # Ajusta la URL según tu configuración de FastAPI
    api_url = f"{API_URL}/v1/auth/github"
    headers = {
        "X-GitHub-Token": auth.get_valid_token()
    }

    try:
        response = requests.post(api_url, headers=headers)
        response.raise_for_status()  # Levanta una excepción si la petición no es exitosa

        user_data = response.json()
        typer.echo(f"ℹ️ User Information:")
        for key, value in user_data.items():
            typer.echo(f"* {key}: {value}")
    except requests.RequestException as e:
        typer.echo(f"❌ Error retrieving user information: {str(e)}")


@app.command(name='logout')
def logout():
    """
    Terminate the current authenticated session.

    Clears the stored access token and ends the user session.
    """
    try:
        auth.clear_stored_token()
        typer.echo("🔒 Successfully logged out.")
    except Exception as e:
        typer.echo(f"❌ Logout error: {e}")
