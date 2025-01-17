import os
import time
from itertools import cycle
from typing import Optional

import requests
import typer
from dotenv.main import load_dotenv
from github import Github
from oauthcli import GitHubAuth, clean
from starlette.datastructures import Secret

load_dotenv(".env")
cli = typer.Typer()

# Configuración para GitHub OAuth
client_id = Secret(os.getenv("CLIENT_ID"))
client_secret = Secret(os.getenv("CLIENT_SECRET"))


def loading_animation():
    spinner = cycle('|/-\\')
    for _ in range(10):
        typer.echo(f"\r⏳ Loading... {next(spinner)}", nl=False)
        time.sleep(0.1)
    typer.echo()


@cli.command()
def login():
    """Inicia sesión con GitHub para obtener un token de acceso."""
    try:
        # clean.main()
        typer.echo("🔐 Authentication flow with Github ")
        loading_animation()
        auth = GitHubAuth(
            client_id=client_id,
            client_secret=client_secret,
            scopes=["user"],
        )
        auth = auth.auth_server()
        authorized = auth.authorized
        if authorized:
            typer.echo("🚀 User is authenticated")
            typer.echo(f"🔐 Token ${auth.session.token}")
        else:
            typer.echo("❌ Authentication flow failed")

        response = auth.get("/user")
        if response.status_code == 200:
            user_data = response.json()
            typer.echo(f"Welcome, {user_data}!")
        else:
            typer.echo(
                f"Failed to fetch user data: {response.status_code}")
    except Exception as e:
        typer.echo(f"❌ Error de autenticación: {e}")


@cli.command()
def hello(name: str):
    print(f"Hello {name}")


@cli.command()
def goodbye(name: str, formal: bool = False):
    if formal:
        print(f"Goodbye Ms. {name}. Have a good day.")
    else:
        print(f"Bye {name}!")


if __name__ == "__main__":
    cli()
