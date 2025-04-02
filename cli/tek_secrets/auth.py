import os

from dotenv.main import load_dotenv
from github import Github
from oauthcli import GitHubAuth, clean
from starlette.datastructures import Secret

from ._secrets import get_secret

load_dotenv(".env")
# Config  GitHub OAuth
client_id = get_secret("CLIENT_ID")
client_secret = get_secret("CLIENT_SECRET")
auth = GitHubAuth(
    client_id=client_id,
    client_secret=client_secret,
    scopes=["user"],
)
