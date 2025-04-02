import os

from dotenv.main import load_dotenv
from starlette.datastructures import Secret

load_dotenv(".env")


API_URL = os.getenv("API_URL", "Tek Secrets API")
CLIENT_ID = Secret(os.getenv("CLIENT_ID"))
GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
REDIRECT_URI = "http://localhost:8080"
