import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.api.routes import grants, health, geocode, waitlist, subscribe
from app.core.config import get_settings
from app.services.stripe_service import init_stripe

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    logger.info("Initialising Stripe product catalogue…")
    try:
        init_stripe()
    except Exception as exc:
        logger.error("Stripe initialisation failed: %s", exc)
    yield
    # ── Shutdown ─────────────────────────────────────────────────────────────


app = FastAPI(
    title="TractPitch",
    description="Census tract grant eligibility screener and narrative report generator.",
    version="0.1.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(health.router, tags=["Health"])
app.include_router(grants.router, prefix="/api/v1/grants", tags=["Grants"])
app.include_router(geocode.router, prefix="/api/v1", tags=["Geocode"])
app.include_router(waitlist.router, prefix="/api/v1", tags=["Waitlist"])
app.include_router(subscribe.router, prefix="/api/v1", tags=["Subscribe"])


@app.get("/", include_in_schema=False)
def landing():
    return FileResponse("app/templates/landing.html")


@app.get("/screener", include_in_schema=False)
def screener():
    return FileResponse("app/templates/index.html")


@app.get("/subscribe/success", include_in_schema=False)
def subscribe_success():
    return FileResponse("app/templates/subscribe_success.html")


@app.get("/subscribe/cancel", include_in_schema=False)
def subscribe_cancel():
    return FileResponse("app/templates/subscribe_cancel.html")
