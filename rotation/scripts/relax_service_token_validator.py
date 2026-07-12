#!/usr/bin/env python3
"""
Relaja el $jsonSchema de la colección service_tokens para permitir
project_id = null (necesario para tokens de SISTEMA / globales).

Qué hace:
- Lee el validador actual de la colección
- Cambia project_id.bsonType de "objectId" a ["objectId", "null"]
- Quita project_id de 'required' (si estuviera)
- Aplica con collMod (NO borra el resto del validador)

Uso:
    python3 relax_service_token_validator.py \
      --mongodb-url "mongodb+srv://..." \
      --db secrets-27222
"""

import argparse
import json
from pymongo import MongoClient


def patch_project_id(schema: dict) -> bool:
    """Parcha project_id dentro del $jsonSchema. Retorna True si cambió algo."""
    changed = False
    js = schema.get("$jsonSchema", {})

    # 1. properties.project_id.bsonType -> ["objectId", "null"]
    props = js.get("properties", {})
    pid = props.get("project_id")
    if isinstance(pid, dict) and "bsonType" in pid:
        current = pid["bsonType"]
        if current != ["objectId", "null"]:
            pid["bsonType"] = ["objectId", "null"]
            changed = True

    # 2. required: quitar project_id si está
    required = js.get("required")
    if isinstance(required, list) and "project_id" in required:
        js["required"] = [r for r in required if r != "project_id"]
        changed = True

    return changed


def main(mongodb_url: str, db_name: str):
    client = MongoClient(mongodb_url)
    db = client[db_name]

    # Leer info de la colección (incluye validator)
    info = db.command("listCollections", filter={"name": "service_tokens"})
    coll_info = info["cursor"]["firstBatch"]
    if not coll_info:
        print("❌ Colección service_tokens no encontrada")
        return

    options = coll_info[0].get("options", {})
    validator = options.get("validator")

    if not validator or "$jsonSchema" not in validator:
        print("⚠️  La colección no tiene validador $jsonSchema. Nada que hacer.")
        print("    (El error debe venir de otra parte.)")
        return

    print("=== Validador ACTUAL (project_id) ===")
    print(json.dumps(
        validator["$jsonSchema"].get("properties", {}).get("project_id"),
        indent=2, default=str
    ))

    changed = patch_project_id(validator)

    if not changed:
        print("\n✅ project_id ya permite null. Nada que cambiar.")
        return

    # Aplicar collMod con el validador parcheado (conserva todo lo demás)
    db.command({
        "collMod": "service_tokens",
        "validator": validator,
        "validationLevel": options.get("validationLevel", "strict"),
        "validationAction": options.get("validationAction", "error"),
    })

    print("\n✅ Validador actualizado: project_id ahora acepta objectId O null")
    print("=== NUEVO (project_id) ===")
    print(json.dumps(
        validator["$jsonSchema"]["properties"].get("project_id"),
        indent=2, default=str
    ))

    client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mongodb-url", required=True)
    parser.add_argument("--db", default="secrets-27222")
    args = parser.parse_args()
    main(args.mongodb_url, args.db)
