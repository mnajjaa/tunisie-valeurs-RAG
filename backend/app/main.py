from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.env import load_env
from app.api.routes.health import router as health_router
from app.api.routes.documents import router as documents_router
from app.api.routes.ask import router as ask_router

load_env()

app = FastAPI(title="TunisieValeurs RAG API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200", "http://127.0.0.1:4200"],
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api")
app.include_router(documents_router, prefix="/api")
app.include_router(ask_router, prefix="/api")
