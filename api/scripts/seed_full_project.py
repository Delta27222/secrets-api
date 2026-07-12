"""
Script para crear un proyecto completo con encriptación funcional.

Crea:
1. Usuario de prueba
2. Organización de prueba
3. Proyecto "Proyecto Inicial"
4. Llave de encriptación automática
5. 3 ambientes (dev, stg, prd) con secretos

Uso:
    python -m scripts.seed_full_project

Resultado:
    Proyecto listo para testing de encriptación
"""

import asyncio
import os
import sys
from datetime import datetime
import logging
import warnings

# Agregar el parent directory al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from bson import ObjectId

load_dotenv()

# Silenciar logs de httpx y warnings de deprecation
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("app.services.encryption_keys").setLevel(logging.WARNING)
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Importar servicios
from app.core.config import MONGODB_URL, database_name
from app.models.organization import OrganizationCreate
from app.models.project import ProjectCreate

from app.models.organization_member import OrganizationMemberCreate, MembershipStatus, OrganizationRole
from app.services.users import get_user_by_email
from app.services.organizations import create_organization, create_organization_member
from app.services.projects import create_project
from app.services.environment import create_environment
from app.services.secret_encryption import encrypt_secrets


def get_timestamp_suffix():
    """Genera timestamp con formato: Hora x pm/am, fecha x de mes x"""
    from datetime import datetime

    # Nombres de meses en español
    meses = [
        "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
    ]

    now = datetime.now()
    hora = now.strftime("%I").lstrip("0")  # Hora sin leading zero
    minutos = now.strftime("%M")
    ampm = now.strftime("%p").lower()  # am/pm
    dia = now.day
    mes = meses[now.month - 1]

    return f"{hora}:{minutos} {ampm}, {dia} de {mes}"


async def seed_full_project():
    """Ejecuta el seed completo."""

    print("=" * 60)
    print("🌱 SEED - PROYECTO INICIAL CON ENCRIPTACIÓN")
    print("=" * 60)

    # Generar timestamp
    timestamp = get_timestamp_suffix()
    print(f"\n⏰ Timestamp: {timestamp}")

    # Conectar a MongoDB
    client = AsyncIOMotorClient(str(MONGODB_URL))
    db = client[database_name]

    try:
        # ===================================================================
        # 0. Verificar usuario requerido
        # ===================================================================
        print("\n🔐 Verificando usuario requerido...")

        required_email = "angelgabriel.hernandez@gmail.com"
        required_user = await get_user_by_email(client, required_email)

        if not required_user:
            print(f"\n❌ ERROR CRÍTICO:")
            print(f"   El usuario '{required_email}' NO está registrado.")
            print(f"\n   ⚠️  ANTES de ejecutar este seed, debes registrar el usuario en la aplicación")
            print(f"   o crear manualmente en MongoDB:")
            print(f"\n      mongosh")
            print(f"      use secrets-27222")
            print(f"      db.users.insertOne({{")
            print(f"        email: '{required_email}',")
            print(f"        username: 'angelgabriel',")
            print(f"        displayName: 'Ángel Gabriel Hernández',")
            print(f"        provider: 'github',")
            print(f"        provider_id: 'angelgabriel-xxx'")
            print(f"      }})")
            print(f"\n❌ Seed cancelado.")
            return False

        user = required_user
        user_id = str(user.id)
        user_email = required_email
        print(f"✅ Usuario encontrado: {user_email}")
        print(f"   ID: {user_id}")

        # ===================================================================
        # 0.5. Limpiar tablas (DESTRUCTIVO)
        # ===================================================================
        print("\n⚠️  Limpiando base de datos...")

        collections_to_clear = [
            "encryption_key_versions",
            "encryption_keys",
            "environments",
            "organization_members",
            "organizations",
            "project_members",
            "projects",
            "service_token_rotations",
            "token_permissions",
            "service_tokens",
        ]

        for coll_name in collections_to_clear:
            result = await db[coll_name].delete_many({})
            print(f"   ✅ {coll_name}: {result.deleted_count} documentos eliminados")

        print("\n✨ Base de datos limpiada")

        # ===================================================================
        # 1. Crear/obtener organización de prueba
        # ===================================================================
        print("\n🏢 Preparando organización...")

        org_name = f"Organización Inicial - {timestamp}"
        org_slug = "organizacion-inicial"

        org_create = OrganizationCreate(name=org_name, slug=org_slug)
        organization = await create_organization(client, org_create, user_email)
        print(f"   ✅ Organización creada: {org_name}")

        org_id = ObjectId(str(organization.id))

        # ===================================================================
        # 1.5. Crear membership usuario-organización
        # ===================================================================
        print("\n👥 Vinculando usuario con organización...")

        # Verificar si ya existe membership
        existing_member = await db["organization_members"].find_one({
            "organization_id": str(org_id),
            "email": user_email
        })

        if not existing_member:
            member_create = OrganizationMemberCreate(
                organization_id=str(org_id),
                email=user_email,
                role=OrganizationRole.owner,
                status=MembershipStatus.accepted
            )
            member = await create_organization_member(client, member_create)
            print(f"   ✅ Usuario vinculado: {user_email} (rol: owner)")
        else:
            print(f"   ✅ Membership ya existe: {user_email}")

        # ===================================================================
        # 2. Crear proyecto con encriptación
        # ===================================================================
        print("\n🔑 Creando proyecto con encriptación automática...")

        project_create = ProjectCreate(
            name=f"Proyecto Inicial - {timestamp}",
            slug="proyecto-inicial",
            organization_id=str(org_id),
        )
        project = await create_project(client, project_create, org_id, user_id)

        project_id = str(project.id)
        print(f"   ✅ Proyecto creado: {project.name}")
        print(f"      ID: {project_id}")

        # Verificar que la llave fue creada
        encryption_keys = await db["encryption_keys"].find_one(
            {"project_id": project_id, "is_primary": True}
        )
        if encryption_keys:
            print(f"   ✅ Llave de encriptación creada: {encryption_keys['key_id']}")
            print(f"      Status: {encryption_keys['status']}")
            print(f"      Version: {encryption_keys['version']}")
        else:
            print("   ⚠️  ADVERTENCIA: No se encontró llave de encriptación")

        # ===================================================================
        # 3. Obtener ambientes (ya creados por create_project)
        # ===================================================================
        print("\n📦 Ambientes creados automáticamente:")

        environments = await db["environments"].find(
            {"project_id": project_id}
        ).to_list(None)

        for env in environments:
            secrets_meta = env.get("secrets_encryption") or {}
            key_id = secrets_meta.get("encrypted_with_key_id", "N/A")
            print(f"   ✅ {env['name']} (slug: {env['slug']})")
            print(f"      Encriptado con: {key_id}")
            print(f"      Secretos: {len(env.get('secrets', {}))} (encriptados)")

        # ===================================================================
        # 4. Agregar secretos de prueba a cada ambiente
        # ===================================================================
        print("\n🔐 Agregando secretos de prueba...")

        test_secrets = {
            "dev": {
                "DB_HOST": "localhost",
                "DB_PORT": "5432",
                "DB_USER": "dev_user",
                "DB_PASSWORD": "dev_password_123",
                "API_KEY": "dev-api-key-xyz",
                "REDIS_URL": "redis://localhost:6379"
            },
            "stg": {
                "DB_HOST": "stg-db.internal",
                "DB_PORT": "5432",
                "DB_USER": "stg_user",
                "DB_PASSWORD": "stg_password_456",
                "API_KEY": "stg-api-key-abc",
                "REDIS_URL": "redis://stg-redis:6379"
            },
            "prd": {
                "DB_HOST": "prod-db.internal",
                "DB_PORT": "5432",
                "DB_USER": "prod_user",
                "DB_PASSWORD": "prod_password_789",
                "API_KEY": "prod-api-key-def",
                "REDIS_URL": "redis://prod-redis:6379"
            }
        }

        for env in environments:
            slug = env["slug"]
            if slug in test_secrets:
                # Encriptar secretos con llave activa
                encrypted_secrets, encryption_metadata = await encrypt_secrets(
                    client,
                    test_secrets[slug],
                    project_id=project_id
                )

                # Actualizar ambiente con secretos ENCRIPTADOS
                await db["environments"].update_one(
                    {"_id": env["_id"]},
                    {
                        "$set": {
                            "secrets": encrypted_secrets,
                            "secrets_encryption": encryption_metadata,
                            "updated_at": datetime.utcnow()
                        }
                    }
                )

                # Re-obtener para verificar
                updated_env = await db["environments"].find_one({"_id": env["_id"]})
                key_id = encryption_metadata.get("encrypted_with_key_id", "N/A")
                print(f"   ✅ {env['name']}: {len(updated_env['secrets'])} secretos encriptados")
                print(f"      Llave: {key_id}")

        # ===================================================================
        # 5. Resumen final
        # ===================================================================
        print("\n" + "=" * 60)
        print("✅ SEED COMPLETADO CON ÉXITO")
        print("=" * 60)

        print("\n📊 Resumen:")
        print(f"  Usuario:      {user_email}")
        print(f"  Organización: {org_name}")
        print(f"  Proyecto:     Proyecto Inicial")
        print(f"  Project ID:   {project_id}")
        print(f"  Ambientes:    3 (dev, stg, prd)")
        print(f"  Secretos:     {sum(len(s) for s in test_secrets.values())} totales")

        print("\n🧪 Testing:")
        print("  1. Ver llave activa:")
        print(f"     curl http://localhost:8000/v1/keys/current")
        print("  2. Ver ambiente con secretos:")
        print(f"     curl http://localhost:8000/v1/environments/<env_id>")
        print("  3. Ver auditoría:")
        print(f"     curl http://localhost:8000/v1/keys/audit-log")

        print("\n📂 MongoDB:")
        print(f"  DB:       {database_name}")
        print(f"  Collections creadas:")
        print(f"    - encryption_keys")
        print(f"    - encryption_key_versions")
        print(f"    - environments")
        print(f"    - projects")
        print(f"    - users")
        print(f"    - organizations")

        print("\n📈 QuestDB:")
        print(f"  Tabla:    encryption_key_audit")
        print(f"  Eventos:  KEY_GENERATED, KEY_ROTATED (registrados)")

        print("\n✨ ¡Listo para testing de encriptación!\n")

    except Exception as e:
        print(f"\n❌ Error durante seed: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        client.close()

    return True


async def main():
    """Ejecuta el seed."""
    success = await seed_full_project()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
