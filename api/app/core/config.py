import os

from dotenv.main import load_dotenv
from starlette.datastructures import CommaSeparatedStrings, Secret

API_V1_STR = "/api"

JWT_TOKEN_PREFIX = "Token"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # one week

load_dotenv(".env")

# Encryption
MONGODB_CSFLE_MASTER_KEY = os.getenv("MONGODB_CSFLE_MASTER_KEY", "")

# Connections
MAX_CONNECTIONS_COUNT = int(os.getenv("MAX_CONNECTIONS_COUNT", 10))
MIN_CONNECTIONS_COUNT = int(os.getenv("MIN_CONNECTIONS_COUNT", 10))
SECRET_KEY = Secret(str(os.getenv("SECRET_KEY", "")))

# GitHub
GITHUB_CLIENT_ID = Secret(str(os.getenv("GITHUB_CLIENT_ID", "")))
GITHUB_CLIENT_SECRET = Secret(str(os.getenv("GITHUB_CLIENT_SECRET", "")))
GITHUB_ORG_NAME = os.getenv("GITHUB_ORG_NAME", "")

# Database
PROJECT_NAME = os.getenv("PROJECT_NAME", "Tek Secrets API")
ALLOWED_HOSTS = CommaSeparatedStrings(os.getenv("ALLOWED_HOSTS", ""))
MONGO_DB = os.getenv("MONGO_DB", "secrets-27222")
MONGODB_URL = os.getenv("MONGODB_URL", "")

# Deployments
RENDER_API_URL = os.getenv("RENDER_API_URL", "https://api.render.com/v1")
VERCEL_API_URL = os.getenv("VERCEL_API_URL", "https://api.vercel.com/v10/projects")

# AWS SQS
SQS_QUEUE_URL = os.getenv("SQS_QUEUE_URL", "")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
AWS_REGION_NAME = os.getenv("AWS_REGION_NAME", "us-east-1")

# QuestDB
EC2_INSTANCE_IP = os.getenv("EC2_INSTANCE_IP", "")
EC2_INSTANCE_PORT = int(os.getenv("EC2_INSTANCE_PORT", 9000))

# Autodescubrimiento de la IP de QuestDB desde AWS.
# Si EC2_INSTANCE_IP NO está definida, se busca la instancia EC2 con
# tag Name = QUESTDB_INSTANCE_NAME (creada por el módulo Terraform de logs)
# y se toma su IP pública. Si EC2_INSTANCE_IP está definida, esa tiene prioridad.
QUESTDB_INSTANCE_NAME = os.getenv("QUESTDB_INSTANCE_NAME", "tek-secrets-questdb")


def _discover_questdb_ip() -> str:
    """Devuelve la IP pública de la instancia EC2 de QuestDB (o '' si falla)."""
    try:
        import logging
        import boto3
        from botocore.config import Config as _BotoConfig

        ec2 = boto3.client(
            "ec2",
            region_name=AWS_REGION_NAME,
            config=_BotoConfig(connect_timeout=5, read_timeout=5, retries={"max_attempts": 1}),
        )
        resp = ec2.describe_instances(
            Filters=[
                {"Name": "tag:Name", "Values": [QUESTDB_INSTANCE_NAME]},
                {"Name": "instance-state-name", "Values": ["running"]},
            ]
        )
        for reservation in resp.get("Reservations", []):
            for inst in reservation.get("Instances", []):
                ip = inst.get("PublicIpAddress")
                if ip:
                    logging.getLogger(__name__).info(
                        f"QuestDB autodescubierta en AWS: {ip} (tag Name={QUESTDB_INSTANCE_NAME})"
                    )
                    return ip
        logging.getLogger(__name__).warning(
            f"No se encontró instancia EC2 running con tag Name={QUESTDB_INSTANCE_NAME}"
        )
        return ""
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            f"No se pudo autodescubrir la IP de QuestDB desde AWS: {e}"
        )
        return ""


if not EC2_INSTANCE_IP:
    EC2_INSTANCE_IP = _discover_questdb_ip()

EC2_INSTANCE_URL = os.getenv("EC2_INSTANCE_DB", f'http://{EC2_INSTANCE_IP}:{EC2_INSTANCE_PORT}')

if not MONGODB_URL:
    MONGO_HOST = os.getenv("MONGO_HOST", "localhost")
    MONGO_PORT = int(os.getenv("MONGO_PORT", 27017))
    MONGO_USER = os.getenv("MONGO_USER", "")
    MONGO_PASS = os.getenv("MONGO_PASSWORD", "")
    MONGODB_URL = f"mongodb://{MONGO_USER}:{MONGO_PASS}@{MONGO_HOST}:{MONGO_PORT}/{MONGO_DB}"

database_name = MONGO_DB
users_collection_name = "users"
organizations_collection_name = "organizations"
projects_collection_name = "projects"
environments_collection_name = "environments"
project_members_collection_name = "project_members"
organization_members_collection_name = "organization_members"
encryption_keys_collection_name = "encryption_keys"
encryption_key_versions_collection_name = "encryption_key_versions"
service_tokens_collection_name = "service_tokens"
service_token_rotations_collection_name = "service_token_rotations"
token_permissions_collection_name = "token_permissions"
