import logging

from fastapi import FastAPI

from app.api.routes import grants, health
from app.core.config import get_settings

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

app = FastAPI(
    title="TractPitch",
    description="Census tract grant eligibility screener and narrative report generator.",
    version="0.1.0",
)

app.include_router(health.router, tags=["Health"])
app.include_router(grants.router, prefix="/api/v1/grants", tags=["Grants"])
