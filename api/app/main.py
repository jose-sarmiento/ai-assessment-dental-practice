import logging

from fastapi import FastAPI

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from app.core.config import settings
from app.routers import ask, session

app = FastAPI(title=settings.app_name, debug=settings.debug)

app.include_router(ask.router)
app.include_router(session.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
