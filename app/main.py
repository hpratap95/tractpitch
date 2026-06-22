import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.api.routes import grants, health, geocode, waitlist
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

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(health.router, tags=["Health"])
app.include_router(grants.router, prefix="/api/v1/grants", tags=["Grants"])
app.include_router(geocode.router, prefix="/api/v1", tags=["Geocode"])
app.include_router(waitlist.router, prefix="/api/v1", tags=["Waitlist"])


@app.get("/", include_in_schema=False)
def landing():
    return FileResponse("app/templates/landing.html")


@app.get("/screener", include_in_schema=False)
def screener():
    return FileResponse("app/templates/index.html")
