from fastapi import FastAPI

from app.core.env import load_env

load_env()

from app.api.routes.health import router as health_router
from app.api.routes.documents import router as documents_router
from app.api.routes.ask import router as ask_router

app = FastAPI(title="TunisieValeurs RAG API")

app.include_router(health_router, prefix="/api")
app.include_router(documents_router, prefix="/api")
app.include_router(ask_router, prefix="/api")
