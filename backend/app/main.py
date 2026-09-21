import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import agent, conversations, tasks
from app.core.config import env_file_found, get_settings
from app.core.logging import log_event, setup_logging
from app.db.session import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    init_db()
    settings = get_settings()
    log_event(
        logging.getLogger("startup"),
        operation="startup",
        env_file_found=env_file_found(),
        anthropic_key_configured=bool(settings.anthropic_api_key),  # never the key itself
        model=settings.model_name,
    )
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Task Manager", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health():
        return {"status": "ok", "assistant_configured": bool(settings.anthropic_api_key)}

    app.include_router(tasks.router)
    app.include_router(agent.router)
    app.include_router(conversations.router)
    return app


app = create_app()
