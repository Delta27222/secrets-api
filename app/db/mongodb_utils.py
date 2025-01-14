import logging

from motor.motor_asyncio import AsyncIOMotorClient

from ..core.config import MAX_CONNECTIONS_COUNT, MIN_CONNECTIONS_COUNT, MONGODB_URL
from .mongodb import db


async def connect_to_mongo():
    logging.info("Start DB connection...")
    db.client = AsyncIOMotorClient(str(MONGODB_URL),
                                   maxPoolSize=MAX_CONNECTIONS_COUNT,
                                   minPoolSize=MIN_CONNECTIONS_COUNT)
    logging.info("DB connection created")


async def close_mongo_connection():
    logging.info("Closing DB connection...")
    db.client.close()
    logging.info("DB Client connection closed")
