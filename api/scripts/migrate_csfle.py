"""
Script de migración: encripta key_material existente (plaintext) con CSFLE.

Uso:
    cd api && source .venv/bin/activate
    python -m scripts.migrate_csfle

Qué hace:
    1. Conecta a MongoDB
    2. Inicializa CSFLE (crea DEK si no existe)
    3. Busca documentos en encryption_keys donde key_material es string (plaintext)
    4. Los encripta con CSFLE y actualiza el documento
    5. Reporta resultados
"""

import sys
import os

# Agregar path del proyecto
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo import MongoClient
from bson.binary import Binary

from app.core.config import MONGODB_URL, database_name, encryption_keys_collection_name
from app.core.csfle import init_csfle, encrypt_field, close_csfle


def migrate():
    print("=" * 70)
    print("MIGRACIÓN CSFLE: Encriptar key_material existente")
    print("=" * 70)

    # 1. Inicializar CSFLE (crea DEK + indice si no existen)
    print("\n1. Inicializando CSFLE...")
    init_csfle()
    print("   CSFLE inicializado")

    # 2. Conectar a MongoDB
    print("\n2. Conectando a MongoDB...")
    client = MongoClient(str(MONGODB_URL))
    db = client[database_name]
    collection = db[encryption_keys_collection_name]

    # 3. Buscar documentos con key_material en plaintext (tipo string)
    print("\n3. Buscando documentos con key_material en plaintext...")
    total = collection.count_documents({})
    print(f"   Total documentos en {encryption_keys_collection_name}: {total}")

    migrated = 0
    already_encrypted = 0
    errors = 0

    for doc in collection.find({}):
        key_id = doc.get("key_id", "unknown")
        key_material = doc.get("key_material")

        # Si ya es Binary (CSFLE), skip
        if isinstance(key_material, (Binary, bytes)):
            already_encrypted += 1
            print(f"   [SKIP] {key_id} — ya encriptado con CSFLE")
            continue

        # Si es string (plaintext), encriptar
        if isinstance(key_material, str):
            try:
                encrypted = encrypt_field(key_material)
                collection.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"key_material": encrypted}}
                )
                migrated += 1
                print(f"   [OK]   {key_id} — migrado a CSFLE")
            except Exception as e:
                errors += 1
                print(f"   [ERR]  {key_id} — {e}")
        else:
            print(f"   [WARN] {key_id} — tipo inesperado: {type(key_material)}")

    # 4. Resumen
    print("\n" + "=" * 70)
    print("RESUMEN")
    print("=" * 70)
    print(f"   Total:              {total}")
    print(f"   Migrados:           {migrated}")
    print(f"   Ya encriptados:     {already_encrypted}")
    print(f"   Errores:            {errors}")
    print("=" * 70)

    # Cleanup
    client.close()
    close_csfle()

    if errors > 0:
        print("\n⚠️  Hubo errores. Revisa los logs arriba.")
        sys.exit(1)
    else:
        print("\n✅ Migración completada exitosamente.")


if __name__ == "__main__":
    migrate()
