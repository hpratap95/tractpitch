"""
Stripe integration — product/price bootstrap and checkout session creation.

On startup, ensures a 'TractPitch Pro' product and $49/month recurring
price exist in Stripe, then caches the price_id for checkout session use.
"""
import logging

import stripe

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_price_id: str | None = None


def init_stripe() -> None:
    """
    Called once at application startup.
    Configures the Stripe API key and ensures the Pro product + price exist.
    Skips gracefully if the secret key is not configured.
    """
    global _price_id

    settings = get_settings()
    if not settings.stripe_secret_key:
        logger.warning("STRIPE_SECRET_KEY not set — Stripe integration disabled.")
        return

    stripe.api_key = settings.stripe_secret_key

    # ── Find or create the product ───────────────────────────────────────────
    product = None
    for p in stripe.Product.list(active=True, limit=100).auto_paging_iter():
        if p.name == "TractPitch Pro":
            product = p
            break

    if product is None:
        product = stripe.Product.create(
            name="TractPitch Pro",
            description=(
                "Unlimited grant searches, saved addresses, deadline alerts, "
                "and bulk CSV upload for community development teams."
            ),
        )
        logger.info("Created Stripe product: %s (%s)", product.name, product.id)
    else:
        logger.info("Found existing Stripe product: %s (%s)", product.name, product.id)

    # ── Find or create the $49/month price ───────────────────────────────────
    price = None
    for pr in stripe.Price.list(product=product.id, active=True, limit=100).auto_paging_iter():
        if (
            pr.unit_amount == 4900
            and pr.currency == "usd"
            and pr.recurring
            and pr.recurring.interval == "month"
        ):
            price = pr
            break

    if price is None:
        price = stripe.Price.create(
            product=product.id,
            unit_amount=4900,
            currency="usd",
            recurring={"interval": "month"},
        )
        logger.info("Created Stripe price: $49/month (%s)", price.id)
    else:
        logger.info("Found existing Stripe price: $49/month (%s)", price.id)

    _price_id = price.id


def get_price_id() -> str | None:
    return _price_id


def create_checkout_session(success_url: str, cancel_url: str) -> str:
    """
    Create a Stripe Checkout Session for the Pro subscription.
    Returns the session URL to redirect the user to.
    """
    if not _price_id:
        raise RuntimeError("Stripe price not initialised — check STRIPE_SECRET_KEY.")

    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": _price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        allow_promotion_codes=True,
        billing_address_collection="auto",
        subscription_data={
            "trial_period_days": 14,
        },
    )
    return session.url
