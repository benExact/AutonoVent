"""Liveness and database readiness."""

from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_engine

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "autonovent-api"}


@router.get("/health/ready")
def ready() -> dict[str, str]:
    from fastapi import HTTPException

    if not get_settings().database_url:
        raise HTTPException(status_code=503, detail="The database is not configured.") from None
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(status_code=503, detail="Database is not reachable.") from None
    return {"status": "ok", "database": "reachable"}
