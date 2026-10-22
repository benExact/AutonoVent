"""FastAPI application."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import router as v1_router
from app.core.config import get_settings
from app.products.images import router as product_images_router


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Autonovent API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origin_list(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
    )
    app.include_router(v1_router, prefix="/api/v1")
    app.include_router(product_images_router)
    return app


app = create_app()
