"""Version 1 routes. Order submission is not available yet."""

from fastapi import APIRouter

from app.api.v1.health import router as health_router
from app.api.v1.products import router as products_router

router = APIRouter()
router.include_router(health_router, tags=["health"])
router.include_router(products_router, tags=["catalogue"])
