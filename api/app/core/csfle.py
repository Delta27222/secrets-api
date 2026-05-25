"""
MongoDB CSFLE (Client-Side Field Level Encryption).

Encripta key_material con AES-256 antes de guardarlo en MongoDB.
MongoDB nunca ve el texto plano — solo blobs binarios.

Arquitectura de llaves (envelope encryption):
    Master Key (env var) → protege → DEK (en key_vault) → protege → key_material
"""

import base64
import logging
from typing import Optional

from pymongo import MongoClient
from pymongo.encryption import ClientEncryption, Algorithm
from bson.codec_options import CodecOptions
from bson.binary import STANDARD, Binary

from .config import MONGODB_CSFLE_MASTER_KEY, MONGODB_URL

logger = logging.getLogger(__name__)

# Namespace donde se guardan las DEKs encriptadas
KEY_VAULT_NAMESPACE = "encryption_db.key_vault"
KEY_VAULT_DB = "encryption_db"
KEY_VAULT_COLL = "key_vault"

# Nombre alternativo para la DEK global
DEK_ALT_NAME = "tek_secrets_dek"

# Singleton
_client_encryption: Optional[ClientEncryption] = None
_sync_client: Optional[MongoClient] = None


def _get_master_key() -> bytes:
    """Decodifica la Master Key desde la env var (base64 → 96 bytes)."""
    if not MONGODB_CSFLE_MASTER_KEY:
        raise ValueError(
            "MONGODB_CSFLE_MASTER_KEY no configurada. "
            "Genera con: python3 -c \"import os,base64; print(base64.b64encode(os.urandom(96)).decode())\""
        )
    key_bytes = base64.b64decode(MONGODB_CSFLE_MASTER_KEY)
    if len(key_bytes) != 96:
        raise ValueError(
            f"Master Key debe ser 96 bytes, tiene {len(key_bytes)}. Regenera la key."
        )
    return key_bytes


def get_client_encryption() -> ClientEncryption:
    """Obtiene singleton de ClientEncryption."""
    global _client_encryption, _sync_client

    if _client_encryption is not None:
        return _client_encryption

    master_key = _get_master_key()
    kms_providers = {"local": {"key": master_key}}
    codec_options = CodecOptions(uuid_representation=STANDARD)

    _sync_client = MongoClient(str(MONGODB_URL))

    _client_encryption = ClientEncryption(
        kms_providers=kms_providers,
        key_vault_namespace=KEY_VAULT_NAMESPACE,
        key_vault_client=_sync_client,
        codec_options=codec_options,
    )

    logger.info("CSFLE ClientEncryption inicializado")
    return _client_encryption


def init_csfle():
    """
    Inicializa CSFLE: crea indice en key_vault y DEK si no existe.
    Llamar una vez en startup de la app.
    """
    global _sync_client

    encryption = get_client_encryption()

    # Crear indice unico en keyAltNames (recomendado por MongoDB)
    if _sync_client is None:
        _sync_client = MongoClient(str(MONGODB_URL))

    key_vault_coll = _sync_client[KEY_VAULT_DB][KEY_VAULT_COLL]
    key_vault_coll.create_index("keyAltNames", unique=True, sparse=True)

    # Crear DEK si no existe
    existing = key_vault_coll.find_one({"keyAltNames": DEK_ALT_NAME})
    if not existing:
        data_key_id = encryption.create_data_key(
            "local",
            key_alt_names=[DEK_ALT_NAME]
        )
        logger.info(f"DEK creada: {data_key_id}")
    else:
        logger.info("DEK ya existe, reutilizando")


def encrypt_field(value: str) -> Binary:
    """
    Encripta un string con CSFLE (explicit encryption).

    Args:
        value: texto plano a encriptar

    Returns:
        Binary BSON encriptado (blob que MongoDB almacena)
    """
    encryption = get_client_encryption()
    return encryption.encrypt(
        value,
        Algorithm.AEAD_AES_256_CBC_HMAC_SHA_512_Random,
        key_alt_name=DEK_ALT_NAME,
    )


def decrypt_field(encrypted_value: Binary) -> str:
    """
    Desencripta un campo CSFLE.

    Args:
        encrypted_value: Binary BSON encriptado

    Returns:
        String en texto plano
    """
    encryption = get_client_encryption()
    return encryption.decrypt(encrypted_value)


def close_csfle():
    """Cierra recursos de CSFLE. Llamar en shutdown."""
    global _client_encryption, _sync_client
    if _client_encryption:
        _client_encryption.close()
        _client_encryption = None
    if _sync_client:
        _sync_client.close()
        _sync_client = None
    logger.info("CSFLE cerrado")
