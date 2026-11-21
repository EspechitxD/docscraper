from __future__ import annotations

import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import OperationalError

from cpmh_backend import __version__
from cpmh_backend.api import router
from cpmh_backend.knowledge.routes import router as knowledge_router
from cpmh_backend.config import get_settings
from cpmh_backend.db import init_db
from cpmh_backend.logging_setup import setup_logging
from cpmh_backend.services.pipeline import QueueWorker


def create_app(*, start_worker: bool = True) -> FastAPI:
    settings = get_settings()
    setup_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db(settings)
        worker = None
        if start_worker:
            worker = QueueWorker()
            worker.start()
            app.state.worker = worker
        yield
        if worker is not None:
            worker.stop()

    app = FastAPI(title="CPMH Document Intelligence", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:5174", "http://localhost:5174"],
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
        allow_credentials=False,
    )
    @app.exception_handler(OperationalError)
    async def database_busy(_request: Request, exc: OperationalError) -> JSONResponse:
        text = str(getattr(exc, "orig", exc)).lower()
        if "locked" in text or "busy" in text:
            message = "O banco local estava ocupado pela extração. Clique em Extrair de novo."
            code = "database_busy"
        else:
            message = "Não foi possível gravar no banco local."
            code = "database"
        return JSONResponse(status_code=503, content={"detail": {"code": code, "message": message}})

    app.include_router(router, prefix="/api")
    app.include_router(knowledge_router, prefix="/api")
    if settings.static_dir and settings.static_dir.exists():
        app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="ui")
    return app


def main() -> None:
    settings = get_settings()
    uvicorn.run(create_app(), host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
