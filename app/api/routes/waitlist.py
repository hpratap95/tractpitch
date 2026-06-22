import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter()
logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class WaitlistRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("Invalid email address.")
        if len(v) > 254:
            raise ValueError("Email address is too long.")
        return v


@router.post("/waitlist")
def join_waitlist(payload: WaitlistRequest, db: Session = Depends(get_db)):
    """
    Save an email address to the Pro plan waitlist.
    Returns 200 whether the email is new or already registered
    (no information leakage about existing sign-ups).
    """
    try:
        db.execute(
            text("""
                INSERT INTO public.waitlist (email, source)
                VALUES (:email, 'pro_landing')
                ON CONFLICT (email) DO NOTHING
            """),
            {"email": payload.email},
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("Waitlist insert failed: %s", exc)
        raise HTTPException(status_code=500, detail="Could not save your email. Please try again.")

    return {"status": "ok", "message": "You're on the list! We'll email you when Pro launches."}
