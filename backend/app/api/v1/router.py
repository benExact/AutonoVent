"""Version 1 routes."""

from fastapi import APIRouter

from app.api.v1.addresses import router as addresses_router
from app.api.v1.admin import router as admin_router
from app.api.v1.auth import router as auth_router
from app.api.v1.checkout import router as checkout_router
from app.api.v1.health import router as health_router
from app.api.v1.orders import router as orders_router
from app.api.v1.products import router as products_router

router = APIRouter()
router.include_router(health_router, tags=["health"])
router.include_router(products_router, tags=["catalogue"])
router.include_router(addresses_router, tags=["addresses"])
router.include_router(checkout_router, tags=["checkout"])
router.include_router(auth_router, prefix="/auth", tags=["auth"])
router.include_router(orders_router, tags=["orders"])
router.include_router(admin_router, prefix="/admin", tags=["admin"])
