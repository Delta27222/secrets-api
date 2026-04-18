"""
Crea datos mínimos en MongoDB (Atlas o local) para las colecciones que usa la API.

Colecciones (nombre de BD: MONGO_DB, por defecto ``dev``):
  users, organizations, organization_members, projects, project_members, environments

Uso (desde la carpeta ``api``)::

  cd api
  source .venv/bin/activate   # o tu venv
  export MONGODB_URL='mongodb+srv://...'   # o déjalo en .env
  python scripts/seed_mongo.py

Si ``mongodb+srv`` falla en tu red (SSL / *connection reset* a varios ``shard-00-XX``),
solo para **pruebas locales** puedes usar **un solo nodo** (copia host desde Atlas
→ Connect → "standard connection string" o el hostname del shard)::

  export MONGODB_DIRECT_URL='mongodb://USUARIO:PASS@ac-....shard-00-00....mongodb.net:27017/?authSource=admin&tls=true&directConnection=true'

``MONGODB_DIRECT_URL`` tiene prioridad sobre ``MONGODB_URL`` si ambas están definidas.
No uses conexión directa en producción: el primary puede cambiar de nodo.

Si ya existe un usuario con username ``seed-dev-user``, el script no hace nada.

Alternativa sin script (orden típico vía HTTP):
  1. ``GET /v1/auth/github/token?code=...`` → token OAuth
  2. ``POST /v1/auth/github`` con cabecera ``X-GitHub-Token: <access_token>`` → crea usuario
  3. ``POST /v1/organizations/`` con cuerpo JSON ``{ "name", "slug" }`` y el mismo header → org + membresía owner
  4. Crear proyecto / entornos con los endpoints correspondientes (requieren usuario autenticado)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

# Permite ``from app....`` al ejecutar ``python scripts/seed_mongo.py`` desde ``api/``
_API_ROOT = Path(__file__).resolve().parent.parent
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

from dotenv import load_dotenv  # noqa: E402
from pymongo import MongoClient  # noqa: E402

load_dotenv(_API_ROOT / ".env")

from app.core.config import (  # noqa: E402
    database_name,
    environments_collection_name,
    organization_members_collection_name,
    organizations_collection_name,
    project_members_collection_name,
    projects_collection_name,
    users_collection_name,
)
from app.models.environment import EnvironmentCreate  # noqa: E402
from app.services.environment import encrypt_secrets  # noqa: E402

SEED_USERNAME = os.getenv("SEED_USERNAME", "delta27222")
SEED_EMAIL = os.getenv("SEED_EMAIL", "angelgabriel.hernandez@gmail.com")
SEED_ORG_SLUG = os.getenv("SEED_ORG_SLUG", "koda-tech")
SEED_PROJECT_SLUG = os.getenv("SEED_PROJECT_SLUG", "koda-tech-project")


def _mongo_uri() -> Optional[str]:
    direct = (os.getenv("MONGODB_DIRECT_URL") or "").strip()
    srv = (os.getenv("MONGODB_URL") or "").strip()
    return direct or srv or None


def _validate_direct_url(url: str) -> None:
    """Evita que MONGODB_DIRECT_URL sea en realidad un SRV o un host sin directConnection."""
    if "mongodb+srv://" in url.lower():
        print(
            "Error: MONGODB_DIRECT_URL no debe usar mongodb+srv:// (eso descubre los 3 nodos).\n"
            "Usa mongodb:// con UN solo host ac-...-shard-00-XX....mongodb.net:27017 y en la query:\n"
            "  authSource=admin&tls=true&directConnection=true",
            file=sys.stderr,
        )
        sys.exit(1)
    if "directconnection=true" not in url.lower().replace(" ", "") and "directconnection=1" not in url.lower():
        print(
            "Error: MONGODB_DIRECT_URL debe incluir directConnection=true (o =1) en la query string.\n"
            "Sin eso, PyMongo descubre el replica set y vuelve a intentar los 3 shards (y falla igual que srv).",
            file=sys.stderr,
        )
        sys.exit(1)


def main() -> None:
    url = _mongo_uri()
    if not url:
        print(
            "Error: define MONGODB_URL (mongodb+srv) o MONGODB_DIRECT_URL (un host, solo dev) "
            "en el entorno o en api/.env",
            file=sys.stderr,
        )
        sys.exit(1)

    using_direct = bool((os.getenv("MONGODB_DIRECT_URL") or "").strip())
    if using_direct:
        print("(Usando MONGODB_DIRECT_URL — solo adecuado para desarrollo local.)")
        _validate_direct_url(url)

    client = MongoClient(url, serverSelectionTimeoutMS=25000)
    try:
        client.admin.command("ping")
    except Exception as e:
        print(f"No se pudo conectar a MongoDB: {e}", file=sys.stderr)
        if not using_direct and "srv" in url.lower():
            print(
                "\nSugerencia: tu red suele cortar el TLS a algunos nodos del replica set. "
                "Prueba otra WiFi/datos, o define MONGODB_DIRECT_URL (ver docstring al inicio de este script).",
                file=sys.stderr,
            )
        sys.exit(1)

    db = client[database_name]
    users = db[users_collection_name]

    if users.find_one({"username": SEED_USERNAME}):
        print(f"Ya existe el usuario '{SEED_USERNAME}'. No se insertó nada.")
        return

    # 1) Usuario (misma forma que ``UserCreate.model_dump(by_alias=True)``)
    user_doc = {
        "username": SEED_USERNAME,
        "email": SEED_EMAIL,
        "displayName": "Seed Dev User",
    }
    uid = users.insert_one(user_doc).inserted_id
    user_id = str(uid)
    print(f"Usuario creado _id={user_id}")

    # 2) Organización
    org_doc = {"name": "Koda Tech", "slug": SEED_ORG_SLUG}
    oid = db[organizations_collection_name].insert_one(org_doc).inserted_id
    org_id = str(oid)
    print(f"Organización creada _id={org_id}")

    # 3) Membresía de organización (owner aceptado)
    member_doc = {
        "organization_id": org_id,
        "email": SEED_EMAIL,
        "role": "owner",
        "status": "accepted",
    }
    db[organization_members_collection_name].insert_one(member_doc)
    print("organization_members: owner vinculado")

    # 4) Proyecto (organization_id como string, igual que en ``projects.py``)
    project_doc = {
        "name": "Seed Project",
        "slug": SEED_PROJECT_SLUG,
        "tags": {},
        "organization_id": org_id,
    }
    pid = db[projects_collection_name].insert_one(project_doc).inserted_id
    project_id = str(pid)
    print(f"Proyecto creado _id={project_id}")

    # 5) Miembro de proyecto (admin)
    pm_doc = {"project": project_id, "user": user_id, "role": "admin"}
    db[project_members_collection_name].insert_one(pm_doc)
    print("project_members: admin asignado")

    # 6) Entornos por defecto (secretos cifrados como en ``create_environment``)
    envs = db[environments_collection_name]
    for name, slug in (
        ("Development", "dev"),
        ("Staging", "stg"),
        ("Production", "prd"),
    ):
        ec = EnvironmentCreate(
            project_id=project_id, name=name, slug=slug, secrets={}
        )
        payload = ec.model_dump()
        payload["secrets"] = encrypt_secrets(payload["secrets"])
        envs.insert_one(payload)
        print(f"environment: {slug}")

    print("Listo. Revisa la base", repr(database_name), "en Atlas/Compass.")


if __name__ == "__main__":
    main()
