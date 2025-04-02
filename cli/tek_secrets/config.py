import os

from dotenv.main import load_dotenv

from ._secrets import get_secret

load_dotenv(".env")


API_URL = get_secret("API_URL")
