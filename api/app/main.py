from fastapi import FastAPI

from app.core.config import settings
from app.routers import ask

app = FastAPI(title=settings.app_name, debug=settings.debug)

app.include_router(ask.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
