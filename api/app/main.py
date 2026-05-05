import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI

from app.core.config import settings
from app.core.logging import JSONFormatter, PHIRedactFilter
from app.core.metrics import snapshot
from app.routers import agent, ask, session

logging.basicConfig(level=logging.DEBUG if settings.debug else logging.INFO)

Path("logs").mkdir(exist_ok=True)
_file_handler = RotatingFileHandler(
    "logs/api.log", maxBytes=10_000_000, backupCount=5, encoding="utf-8"
)

for _handler in [*logging.getLogger().handlers, _file_handler]:
    _handler.setFormatter(JSONFormatter())
    _handler.addFilter(PHIRedactFilter())

logging.getLogger().addHandler(_file_handler)

logging.getLogger(__name__).info(f"[startup] debug mode: {settings.debug}")

for _name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
    for _h in logging.getLogger(_name).handlers:
        _h.setFormatter(JSONFormatter())
        _h.addFilter(PHIRedactFilter())

app = FastAPI(title=settings.app_name, debug=settings.debug)

app.include_router(ask.router)
app.include_router(agent.router)
app.include_router(session.router)


@app.get("/health")
async def health():
    from app.db.connection import get_conn
    try:
        conn = get_conn()
        conn.close()
        return {"status": "ok"}
    except Exception:
        return {"status": "degraded", "detail": "database not ready"}


@app.get("/metrics")
async def metrics():
    return snapshot()
