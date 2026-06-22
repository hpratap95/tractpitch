from fastapi import APIRouter

from app.db.session import check_connection

router = APIRouter()


@router.get("/health")
def health_check():
    db_ok = check_connection()
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "connected" if db_ok else "unreachable",
        "service": "tractpitch",
    }
