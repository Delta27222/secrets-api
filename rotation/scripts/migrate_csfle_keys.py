#!/usr/bin/env python3
"""
Migra encryption keys de CSFLE-encriptado a plain text.

Ejecución:
    python3 migrate_csfle_keys.py \
      --mongodb-url "mongodb+srv://..." \
      --csfle-key "base64-encoded-96-bytes" \
      --db "secrets-27222"
"""

import asyncio
import argparse
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from bson.binary import Binary
import base64

# Importar CSFLE desde API
import sys
sys.path.insert(0, '/Users/delta27222/Desktop/tesis/tek-secrets/api')

from app.core.csfle import decrypt_field

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def migrate_csfle_keys(mongodb_url: str, mongo_db: str, csfle_key: str):
    """Migra keys CSFLE encriptadas a plain text."""

    client = AsyncIOMotorClient(mongodb_url)
    db = client[mongo_db]
    keys_collection = db['encryption_keys']

    try:
        # Obtener todas las keys con key_material Binary (CSFLE)
        cursor = keys_collection.find({'key_material': {'$type': 'binData'}})

        csfle_keys = []
        async for key_doc in cursor:
            csfle_keys.append(key_doc)

        logger.info(f"🔍 Encontradas {len(csfle_keys)} keys encriptadas con CSFLE")

        if not csfle_keys:
            logger.info("✅ No hay keys para migrar")
            return

        # Migrar cada key
        for key_doc in csfle_keys:
            key_id = key_doc['key_id']
            encrypted_material = key_doc['key_material']

            try:
                # Desencriptar con CSFLE
                plain_material = decrypt_field(encrypted_material)

                # Actualizar en BD
                await keys_collection.update_one(
                    {'_id': key_doc['_id']},
                    {'$set': {'key_material': plain_material}}
                )

                logger.info(f"✅ Migrado: {key_id}")

            except Exception as e:
                logger.error(f"❌ Error migrando {key_id}: {e}")
                raise

        logger.info(f"✅ Migración completa: {len(csfle_keys)} keys")

    finally:
        client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Migra keys CSFLE a plain text')
    parser.add_argument('--mongodb-url', required=True, help='MongoDB connection URL')
    parser.add_argument('--db', default='secrets-27222', help='Database name')
    parser.add_argument('--csfle-key', required=True, help='CSFLE Master Key (base64)')

    args = parser.parse_args()

    # Set CSFLE key en env var (para que csfle.py lo use)
    import os
    os.environ['MONGODB_CSFLE_MASTER_KEY'] = args.csfle_key

    # Ejecutar
    asyncio.run(migrate_csfle_keys(args.mongodb_url, args.db, args.csfle_key))
