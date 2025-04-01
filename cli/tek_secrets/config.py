import os

from dotenv.main import load_dotenv

load_dotenv(".env")


API_URL = os.getenv("API_URL", "Tek Secrets API")
