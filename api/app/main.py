from fastapi import FastAPI

from .api.v1.api import router as api_router
from .db.mongodb_utils import close_mongo_connection, connect_to_mongo

app = FastAPI(title='Tek Secrets')


app.add_event_handler("startup", connect_to_mongo)
app.add_event_handler("shutdown", close_mongo_connection)
app.include_router(api_router, prefix='/v1')
