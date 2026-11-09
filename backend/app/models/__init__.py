"""Import models so Alembic can see the metadata."""

from app.models.admin import AdminUser
from app.models.carousel import CarouselSlide
from app.models.email_notification import EmailNotification
from app.models.file_cleanup import FileCleanup
from app.models.audit import ProductAuditEvent
from app.models.auth import AdminSession, LoginAttempt
from app.models.order import Order, OrderItem, OrderStatusEvent
from app.models.payment import Payment
from app.models.product import Product, ProductImage, ProductSlugAlias, ProductSpecification
from app.models.shipment import Shipment

__all__ = [
    "AdminUser",
    "CarouselSlide",
    "EmailNotification",
    "FileCleanup",
    "AdminSession",
    "LoginAttempt",
    "Order",
    "OrderItem",
    "OrderStatusEvent",
    "Payment",
    "Product",
    "ProductImage",
    "ProductSlugAlias",
    "ProductSpecification",
    "ProductAuditEvent",
    "Shipment",
]
