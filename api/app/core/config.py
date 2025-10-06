import os

from dotenv.main import load_dotenv
from starlette.datastructures import CommaSeparatedStrings, Secret

API_V1_STR = "/api"

JWT_TOKEN_PREFIX = "Token"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # one week

load_dotenv(".env")

MAX_CONNECTIONS_COUNT = int(os.getenv("MAX_CONNECTIONS_COUNT", 10))
MIN_CONNECTIONS_COUNT = int(os.getenv("MIN_CONNECTIONS_COUNT", 10))
SECRET_KEY = Secret(str(os.getenv("SECRET_KEY", "secret key for project")))
# Github
GITHUB_CLIENT_ID = Secret(
    str(os.getenv("GITHUB_CLIENT_ID", "Github Client ID")))
GITHUB_CLIENT_SECRET = Secret(
    str(os.getenv("GITHUB_CLIENT_SECRET", "Github Client Secret")))
GITHUB_CLIENT_ID_APP = Secret(
    str(os.getenv("GITHUB_CLIENT_ID_APP", "Github Client ID App")))
GITHUB_CLIENT_SECRET_APP = Secret(
    str(os.getenv("GITHUB_CLIENT_SECRET_APP", "Github Client Secret App")))

# Database
PROJECT_NAME = os.getenv("PROJECT_NAME", "Tek Secrets API")
ALLOWED_HOSTS = CommaSeparatedStrings(os.getenv("ALLOWED_HOSTS", ""))
MONGO_DB = os.getenv("MONGO_DB", "dev")
MONGODB_URL = os.getenv("MONGODB_URL", "MongoDB URL")  # deploying without docker-compose

# Deployments
RENDER_API_URL = os.getenv("RENDER_API_URL", " Render API URL")
VERCEL_API_URL = os.getenv("VERCEL_API_URL", " Vercel API URL")

# AWS SQS
SQS_QUEUE_URL = os.getenv("SQS_QUEUE_URL", " SQS Queue URL")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", " AWS Access Key ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", " AWS Secret Access Key")
AWS_REGION_NAME = os.getenv("AWS_REGION_NAME", "AWS Region Name")

# QuestDB Information Configuration for Logs
EC2_INSTANCE_IP = os.getenv("EC2_INSTANCE_IP", "EC2 Instance IP")
EC2_INSTANCE_PORT = int(os.getenv("EC2_INSTANCE_PORT", 9000))
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
