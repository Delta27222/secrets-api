import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.logging import LoggingMiddleware
from .api.v1.api import router as api_router
from .db.mongodb_utils import close_mongo_connection, connect_to_mongo, create_indexes

logger = logging.getLogger(__name__)

app = FastAPI(title='Tek Secrets')
origins = [
    "*"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(LoggingMiddleware)

@app.on_event("startup")
async def on_startup():
    """Ejecuta al iniciar la aplicación."""
    await connect_to_mongo()
    await create_indexes()
    logger.info("Aplicación iniciada. Índices de base de datos creados.")

@app.on_event("shutdown")
async def on_shutdown():
    """Ejecuta al cerrar la aplicación."""
    await close_mongo_connection()
app.include_router(api_router, prefix='/v1')
