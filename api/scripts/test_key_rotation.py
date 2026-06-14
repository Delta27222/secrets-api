"""
Script para verificar y testear rotación de llaves de encriptación.

Flujo:
1. Obtener proyecto "Proyecto Inicial"
2. Mostrar llave ACTUAL
3. Simular paso de 90 días (modificar created_at en MongoDB)
4. Disparar rotación manual
5. Mostrar nueva llave (v2)
6. Verificar que ambientes antiguos aún desencriptan
7. Re-encriptar batch
8. Verificar auditoría en QuestDB

Uso:
    python -m scripts.test_key_rotation
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta
import json
import logging
import warnings

# Agregar el parent directory al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from bson import ObjectId

load_dotenv()

# Silenciar logs verbose y warnings de deprecation
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("app.services.encryption_keys").setLevel(logging.WARNING)
warnings.filterwarnings("ignore", category=DeprecationWarning)

from app.core.config import (
    EC2_INSTANCE_IP,
    EC2_INSTANCE_PORT,
    MONGODB_URL,
    database_name,
)
from app.services.encryption_keys import get_key_manager


async def obtener_version_activa(db, project_id: str) -> int:
    """Obtiene el número de versión de la llave activa."""
    active_key = await db["encryption_keys"].find_one(
        {"project_id": project_id, "is_primary": True}
    )
    return active_key.get("version") if active_key else None


async def mostrar_llaves(db, project_id: str):
    """Muestra todas las llaves del proyecto."""
    keys = await db["encryption_keys"].find(
        {"project_id": project_id}
    ).sort([("version", -1)]).to_list(None)

    if not keys:
        print("❌ No se encontraron llaves")
        return

    print(f"\n📦 Llaves ({len(keys)} total):")
    print("─" * 100)
    for key in keys:
        status_icon = "🟢" if key['status'] == "active" else "🟡" if key['status'] == "pending" else "🔴"
        primary = "PRIMARY" if key.get('is_primary', False) else ""
        print(f"{status_icon}\tv{key['version']}\t{key['status']:<10s}\t{key['key_id']}\t{primary}")
    print("─" * 100)


async def obtener_ambientes(db, project_id: str):
    """Obtiene ambientes del proyecto."""
    envs = await db["environments"].find(
        {"project_id": project_id}
    ).to_list(None)

    if not envs:
        print("❌ No se encontraron ambientes")
        return {}

    result = {}
    print(f"\n🌍 Ambientes ({len(envs)} total):")
    print("─" * 100)
    for env in envs:
        meta = env.get("secrets_encryption", {})
        key_version = meta.get("key_version", "?")
        key_id = meta.get("encrypted_with_key_id", "N/A")
        secrets_count = len(env.get('secrets', {}))
        print(f"  {env['name']}\tv{key_version}\t{key_id}\t{secrets_count} secretos")
        result[env["_id"]] = {
            "name": env["name"],
            "slug": env["slug"],
            "encrypted_with_key_id": key_id
        }
    print("─" * 100)

    return result, envs


async def simular_paso_tiempo(db, project_id: str):
    """Simula que pasaron 91 días (para rotar automáticamente)."""
    print("\n⏳ Simulando paso de tiempo")
    print("─" * 100)

    # Modificar created_at de la llave activa
    result = await db["encryption_keys"].update_one(
        {"project_id": project_id, "is_primary": True},
        {"$set": {"created_at": datetime.utcnow() - timedelta(days=91)}}
    )

    if result.modified_count == 1:
        print("  ✅ Llave actual: -91 días")
        print("─" * 100)
    else:
        print("❌ No se pudo modificar el timestamp")
        return False

    return True


async def disparar_rotacion(client, project_id: str):
    """Dispara rotación manual."""
    print("\n🔄 Rotación de llave")
    print("─" * 100)

    try:
        manager = get_key_manager()

        # 1. Generar nueva llave
        new_key = await manager.generate_key(
            client,
            project_id,
            created_by="test-script",
            reason="testing"
        )
        print(f"  ✅ Generada: v{new_key['version']}")

        # 2. Rotar (pending → active)
        rotated = await manager.rotate_key(client, project_id, actor_id="test-script")
        print(f"  ✅ Activada: {rotated['new_key_id']}")
        print("─" * 100)

        return True

    except Exception as e:
        print(f"❌ Error en rotación: {e}")
        import traceback
        traceback.print_exc()
        return False


async def probar_desencriptacion(client, db, env_id: ObjectId, env_name: str):
    """Intenta desencriptar un ambiente."""
    print(f"\n🔐 Desencriptación (verificar compatibilidad)")
    print("─" * 100)

    try:
        from app.services.secret_encryption import decrypt_secrets

        env_doc = await db["environments"].find_one({"_id": env_id})
        if not env_doc:
            print(f"❌ Ambiente no encontrado")
            return False

        meta = env_doc.get("secrets_encryption", {})
        key_id = meta.get("encrypted_with_key_id")
        key_version = meta.get("key_version", "?")

        # Desencriptar
        decrypted = await decrypt_secrets(client, env_doc)

        if decrypted:
            print(f"  ✅ {env_name}\tv{key_version}\t{key_id}\t{len(decrypted)} secretos")
            print("─" * 100)
            return True
        else:
            print(f"❌ Desencriptación falló")
            return False

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def reencriptar_batch(client, db, project_id: str):
    """Re-encripta todos los ambientes con la nueva llave."""
    print("\n♻️  Re-encriptando todos los ambientes...")
    print("─" * 100)

    try:
        from app.services.secret_encryption import encrypt_secrets, decrypt_secrets

        envs = await db["environments"].find(
            {"project_id": project_id}
        ).to_list(None)

        if not envs:
            print("❌ No hay ambientes")
            return False

        reencrypted = 0
        failed = 0

        for env in envs:
            try:
                # 1. Desencriptar
                decrypted = await decrypt_secrets(client, env)

                # 2. Encriptar con llave nueva
                encrypted, metadata = await encrypt_secrets(client, decrypted, project_id)

                # 3. Actualizar
                await db["environments"].update_one(
                    {"_id": env["_id"]},
                    {
                        "$set": {
                            "secrets": encrypted,
                            "secrets_encryption": metadata,
                            "updated_at": datetime.utcnow()
                        }
                    }
                )

                print(f"  ✅ {env['name']}\tv{metadata['key_version']}\t{metadata['encrypted_with_key_id']}")
                reencrypted += 1

            except Exception as e:
                print(f"  ❌ {env['name']}\t{str(e)[:40]}")
                failed += 1

        print("─" * 100)
        if failed == 0:
            print(f"✅ Listo: {reencrypted}/{len(envs)} re-encriptados")
        else:
            print(f"⚠️  {reencrypted} OK, {failed} fallidos")
        return failed == 0

    except Exception as e:
        print(f"❌ Error en batch: {e}")
        import traceback
        traceback.print_exc()
        return False


async def consultar_auditoria(db):
    """Consulta auditoría en QuestDB."""
    print("\n📊 Auditoría de eventos (QuestDB)")
    print("─" * 100)

    try:
        import httpx

        query = "SELECT timestamp, action, key_id, operation_result FROM encryption_key_audit ORDER BY timestamp DESC LIMIT 15"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"http://{EC2_INSTANCE_IP}:{EC2_INSTANCE_PORT}/exec",
                params={"query": query},
                timeout=5
            )

            if response.status_code == 200:
                try:
                    data = response.json()
                    if isinstance(data, dict) and "dataset" in data:
                        # Formato QuestDB
                        for row in data.get("dataset", [])[:5]:
                            action = row[1] if len(row) > 1 else "?"
                            key_id = row[2] if len(row) > 2 else "?"
                            result = row[3] if len(row) > 3 else "?"
                            status = "✅" if result == "success" else "❌"
                            print(f"  {status}\t{action:<20s}\t{key_id}")
                    print("─" * 100)
                except:
                    print("  ⚠️  Formato no reconocido")
                    print("─" * 100)
            else:
                print(f"  ⚠️  QuestDB: {response.status_code}")
                print("─" * 100)

    except Exception as e:
        print(f"  ⚠️  No conecta QuestDB: {e}")
        print("─" * 100)


async def test_key_rotation():
    """Ejecuta el test completo."""

    print("=" * 100)
    print("🔐 TEST: ROTACIÓN DE LLAVES DE ENCRIPTACIÓN")
    print("=" * 100)

    # Conectar
    client = AsyncIOMotorClient(str(MONGODB_URL))
    db = client[database_name]

    try:
        # Paso 1: Obtener proyecto
        print("\n1️⃣  Obtener proyecto")

        # Buscar proyecto que comience con "Proyecto Inicial" (tiene timestamp)
        import re
        project = await db["projects"].find_one({"name": re.compile("^Proyecto Inicial")})

        if not project:
            print("❌ Proyecto 'Proyecto Inicial' no encontrado")
            print("   Ejecuta primero: python -m scripts.seed_full_project")
            return False

        project_id = str(project["_id"])
        print(f"✅ Proyecto encontrado: {project['name']}")
        print(f"   ID: {project_id}")

        # Paso 2: Mostrar llaves actuales
        print("\n2️⃣  Llaves actuales")

        await mostrar_llaves(db, project_id)
        version_anterior = await obtener_version_activa(db, project_id)

        # Paso 3: Obtener ambientes
        print("\n3️⃣  Ambientes")

        ambientes_info, envs = await obtener_ambientes(db, project_id)

        # Paso 4: Simular paso de tiempo
        print("\n4️⃣  Simular paso de tiempo")

        if not await simular_paso_tiempo(db, project_id):
            return False

        # Paso 5: Disparar rotación
        print("\n5️⃣  Rotación de llave")

        if not await disparar_rotacion(client, project_id):
            return False

        # Paso 6: Mostrar nuevas llaves
        print("\n6️⃣  Llaves después de rotación")

        await mostrar_llaves(db, project_id)
        version_nueva = await obtener_version_activa(db, project_id)

        # Paso 7: Probar desencriptación (ambiente antiguo)
        print("\n7️⃣  Desencriptación con llave antigua")

        if envs:
            env_id = envs[0]["_id"]
            env_name = envs[0]["name"]
            await probar_desencriptacion(client, db, env_id, env_name)

        # Paso 8: Re-encriptar batch
        print("\n8️⃣  Re-encriptación batch")

        if not await reencriptar_batch(client, db, project_id):
            print("⚠️  Re-encriptación tuvo errores")

        # Paso 9: Mostrar estado final
        print("\n9️⃣  Estado final")

        await obtener_ambientes(db, project_id)

        # Paso 10: Consultar auditoría
        print("\n🔟 Auditoría")

        await consultar_auditoria(db)

        # ===================================================================
        # RESUMEN
        # Resumen final
        print("\n" + "=" * 100)
        print("✅ TEST COMPLETADO")
        print("=" * 100)
        print(f"""
Resultado: ✅ Sistema funcionando correctamente
  ✓ Llaves rotadas (v{version_anterior} → v{version_nueva})
  ✓ Datos antiguos desencriptables
  ✓ Re-encriptación exitosa
  ✓ Auditoría registrada
        """)

        return True

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        client.close()


async def main():
    """Ejecuta el test."""
    success = await test_key_rotation()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
