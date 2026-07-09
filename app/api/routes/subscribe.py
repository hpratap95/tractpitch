import logging

from fastapi import APIRouter, HTTPException, Request

from app.services.stripe_service import create_checkout_session, get_price_id

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/subscribe")
def start_subscription(request: Request):
    """
    Create a Stripe Checkout Session for the TractPitch Pro subscription.
    Returns a checkout URL to redirect the user to Stripe's hosted checkout.
    """
    if not get_price_id():
        raise HTTPException(
            status_code=503,
            detail="Subscription checkout is not available right now. Please try again later.",
        )

    base = str(request.base_url).rstrip("/")
    try:
        checkout_url = create_checkout_session(
            success_url=f"{base}/subscribe/success",
            cancel_url=f"{base}/subscribe/cancel",
        )
    except Exception as exc:
        logger.error("Stripe checkout session creation failed: %s", exc)
        raise HTTPException(status_code=502, detail="Could not create checkout session.")

    return {"checkout_url": checkout_url}
