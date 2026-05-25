import os

from dotenv.main import load_dotenv
from starlette.datastructures import CommaSeparatedStrings, Secret

API_V1_STR = "/api"

JWT_TOKEN_PREFIX = "Token"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # one week

load_dotenv(".env")

# CSFLE Master Key para encriptar/desencriptar los datos en la base de datos
MONGODB_CSFLE_MASTER_KEY = os.getenv("MONGODB_CSFLE_MASTER_KEY", "")

MAX_CONNECTIONS_COUNT = int(os.getenv("MAX_CONNECTIONS_COUNT", 10))
MIN_CONNECTIONS_COUNT = int(os.getenv("MIN_CONNECTIONS_COUNT", 10))
SECRET_KEY = Secret(str(os.getenv("SECRET_KEY", "")))

# Github
GITHUB_CLIENT_ID = Secret(
    str(os.getenv("GITHUB_CLIENT_ID", "")))
GITHUB_CLIENT_SECRET = Secret(
    str(os.getenv("GITHUB_CLIENT_SECRET", "")))

GITHUB_ORG_NAME = os.getenv("GITHUB_ORG_NAME", "")

# Database
PROJECT_NAME = os.getenv("PROJECT_NAME", "")
ALLOWED_HOSTS = CommaSeparatedStrings(os.getenv("ALLOWED_HOSTS", ""))
MONGO_DB = os.getenv("MONGO_DB", "")

MONGODB_URL = os.getenv("MONGODB_URL", "")

# Deployments
RENDER_API_URL = os.getenv("RENDER_API_URL", "")
VERCEL_API_URL = os.getenv("VERCEL_API_URL", "")

# AWS SQS
SQS_QUEUE_URL = os.getenv("SQS_QUEUE_URL", "")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
AWS_REGION_NAME = os.getenv("AWS_REGION_NAME", "")

# QuestDB Information Configuration for Logs
EC2_INSTANCE_IP = os.getenv("EC2_INSTANCE_IP", "")
EC2_INSTANCE_PORT = int(os.getenv("EC2_INSTANCE_PORT", ""))
EC2_INSTANCE_URL = os.getenv("EC2_INSTANCE_DB", f'http://{EC2_INSTANCE_IP}:{EC2_INSTANCE_PORT}')

if not MONGODB_URL:
    MONGO_HOST = os.getenv("MONGO_HOST", "localhost")
    MONGO_PORT = int(os.getenv("MONGO_PORT", 27017))
    MONGO_USER = os.getenv("MONGO_USER", "admin")
    MONGO_PASS = os.getenv("MONGO_PASSWORD", "markqiu")

    MONGODB_URL = f"mongodb://{MONGO_USER}:{MONGO_PASS}@{MONGO_HOST}:{MONGO_PORT}/{MONGO_DB}"
else:
    pass

database_name = MONGO_DB
users_collection_name = "users"
organizations_collection_name = "organizations"
projects_collection_name = "projects"
environments_collection_name = "environments"
project_members_collection_name = "project_members"
organization_members_collection_name = "organization_members"
encryption_keys_collection_name = "encryption_keys"
encryption_key_versions_collection_name = "encryption_key_versions"
