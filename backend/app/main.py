from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .config import settings
from .db import Base, SessionLocal, engine
from .seed import is_empty, seed
from .services.ops_service import TimerService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("opspulse")


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        empty = is_empty(s)
    if settings.reset_on_startup or (settings.seed_on_startup and empty):
        seed(reset=settings.reset_on_startup)
    with SessionLocal() as s:
        closed = TimerService(s).reconcile()
        s.commit()
        if closed:
            log.info("Force-closed %d stale timers", closed)
    yield


app = FastAPI(
    title="OpsPulse API",
    version="1.0.0",
    description="Operations work intelligence: SLA-breach prediction, workload balancing and capacity forecasting.",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["*"], allow_headers=["*"])
app.include_router(router)


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    # Never leak stack traces to end users; log them server-side.
    log.exception("Unhandled error: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# Serve the built React app (single-container deploy).
if (settings.static_dir / "index.html").exists():
    static_root = settings.static_dir.resolve()
    if (static_root / "assets").exists():
        app.mount("/assets", StaticFiles(directory=static_root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = (static_root / path).resolve()
        if path and f.is_file() and f.is_relative_to(static_root):
            return FileResponse(f)
        return FileResponse(static_root / "index.html")
