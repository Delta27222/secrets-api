import os

from dotenv.main import load_dotenv
from github import Github
from oauthcli import GitHubAuth, clean
from starlette.datastructures import Secret

load_dotenv(".env")
# Configuración para GitHub OAuth
client_id = Secret(os.getenv("CLIENT_ID"))
client_secret = Secret(os.getenv("CLIENT_SECRET"))
auth = GitHubAuth(
    client_id=client_id,
    client_secret=client_secret,
    scopes=["user"],
)
