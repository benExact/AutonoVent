"""Owner product management. These routes are not part of the public catalogue."""

import logging
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.v1.auth import require_csrf, require_owner
from app.core.config import get_settings
from app.db.session import get_session
from app.models.admin import AdminUser
from app.models.auth import AdminSession
from app.models.product import Product
from app.products.deletion import delete_product_permanently, storage_roots
from app.products.gallery import (
    GalleryError,
    add_image,
    list_images,
    list_specifications,
    remove_image,
    reorder_images,
    replace_image,
    replace_specifications,
)
from app.products.images import ImageRejected, image_directory, public_image_url, remove_product_image, save_product_image
from app.products.specifications import (
    PDF_TYPE,
    SpecificationRejected,
    max_specification_bytes,
    open_specification,
    original_name,
    public_specification_name,
    remove_specification,
    save_specification,
    specification_directory,
)
from app.products.service import (
    ProductConflict,
    ProductError,
    ProductNotFound,
    create_product,
    get_product,
    list_audit_events,
    list_products,
    update_product,
)
from app.schemas.admin_product import (
    ImageOrder,
    ManagedImage,
    ManagedProduct,
    ManagedSpecification,
    ProductAuditEventView,
    ProductAuditList,
    ProductList,
    ProductPatch,
    ProductWrite,
    SpecificationSheet,
)

router = APIRouter()
logger = logging.getLogger(__name__)
UNAVAILABLE = "Product management is temporarily unavailable."
STORAGE_FAILED = "The specification sheet could not be stored on the server."
DELETE_FAILED = "The product could not be deleted. Nothing was removed. Try again."


def _sheet(product: Product) -> SpecificationSheet:
    configured = bool(product.specification_stored_name)
    available = configured and open_specification(specification_directory(get_settings()), product.specification_stored_name) is not None
    return SpecificationSheet(
        enabled=product.specification_enabled,
        configured=configured,
        file_available=available,
        original_name=product.specification_original_name if configured else None,
        size_bytes=product.specification_size_bytes if configured else None,
        content_type=product.specification_content_type if configured else None,
    )


def _view(product: Product, session: Session) -> ManagedProduct:
    images = []
    for row in list_images(session, product.id):
        url = public_image_url(row.stored_name)
        if url is None:
            continue
        images.append(ManagedImage(id=row.id, url=url, thumb_url=public_image_url(row.thumb_name), position=row.position))
    specifications = [
        ManagedSpecification(id=row.id, label=row.label, value=row.value, position=row.position)
        for row in list_specifications(session, product.id)
    ]
    return ManagedProduct(
        id=product.id,
        slug=product.slug,
        name=product.name,
        description=product.description,
        short_description=product.short_description,
        sku=product.sku,
        unit_price_cents=product.unit_price_cents,
        currency=product.currency,
        active=product.active,
        in_stock=product.in_stock,
        image_url=images[0].url if images else public_image_url(product.image_filename),
        images=images,
        specifications=specifications,
        specification_sheet=_sheet(product),
        created_at=product.created_at,
        updated_at=product.updated_at,
    )


@router.get("/products", response_model=ProductList)
def products(
    _principal: tuple[AdminUser, AdminSession] = Depends(require_owner),
    session: Session = Depends(get_session),
) -> ProductList:
    try:
        rows = list_products(session)
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None
    return ProductList(products=[_view(row, session) for row in rows])


@router.post("/products", response_model=ManagedProduct, status_code=201)
def add_product(
    body: ProductWrite,
    principal: tuple[AdminUser, AdminSession] = Depends(require_csrf),
    session: Session = Depends(get_session),
) -> ManagedProduct:
    owner, _row = principal
    try:
        product = create_product(session, body.stored(), owner.email)
        if body.specifications:
            replace_specifications(session, product, [(item.label, item.value) for item in body.specifications])
    except ProductConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ProductError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except GalleryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None
    return _view(product, session)


@router.patch("/products/{product_id}", response_model=ManagedProduct)
def edit_product(
    product_id: uuid.UUID,
    body: ProductPatch,
    principal: tuple[AdminUser, AdminSession] = Depends(require_csrf),
    session: Session = Depends(get_session),
) -> ManagedProduct:
    owner, _row = principal
    changes = body.stored()
    specs_sent = "specifications" in body.model_fields_set and body.specifications is not None
    if not changes and not specs_sent:
        raise HTTPException(status_code=422, detail="Choose a product field to change.")
    try:
        product = update_product(session, product_id, changes, owner.email, image_directory(get_settings())) if changes else get_product(session, product_id)
        if product is None:
            raise ProductNotFound("The product does not exist.")
        if "specifications" in body.model_fields_set and body.specifications is not None:
            replace_specifications(session, product, [(item.label, item.value) for item in body.specifications])
    except ProductNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ProductConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ProductError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except GalleryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None
    return _view(product, session)


@router.post("/products/{product_id}/image", response_model=ManagedProduct)
async def replace_product_image(
    product_id: uuid.UUID,
    image: UploadFile = File(...),
    principal: tuple[AdminUser, AdminSession] = Depends(require_csrf),
    session: Session = Depends(get_session),
) -> ManagedProduct:
    owner, _row = principal
    data = await image.read(5 * 1024 * 1024 + 1)
    await image.close()
    directory = image_directory(get_settings())
    try:
        filename = save_product_image(directory, data)
    except ImageRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    previous = None
    try:
        current = session.get(Product, product_id)
        if current is not None and current.archived_at is not None:
            current = None
        previous = current.image_filename if current is not None else None
        product = update_product(session, product_id, {"image_filename": filename}, owner.email)
    except ProductNotFound as exc:
        remove_product_image(directory, filename)
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ProductConflict as exc:
        remove_product_image(directory, filename)
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except SQLAlchemyError:
        remove_product_image(directory, filename)
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None
    if previous and previous != filename:
        remove_product_image(directory, previous)
    return _view(product, session)


@router.get("/products/{product_id}/specification", response_model=SpecificationSheet)
def product_specification(
    product_id: uuid.UUID,
    _principal: tuple[AdminUser, AdminSession] = Depends(require_owner),
    session: Session = Depends(get_session),
) -> SpecificationSheet:
    try:
        product = _owned_product(session, product_id)
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None
    return _sheet(product)


@router.get("/products/{product_id}/specification/file")
def preview_product_specification(
    product_id: uuid.UUID,
    _principal: tuple[AdminUser, AdminSession] = Depends(require_owner),
    session: Session = Depends(get_session),
) -> FileResponse:
    try:
        product = _owned_product(session, product_id)
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None
    path = open_specification(specification_directory(get_settings()), product.specification_stored_name)
    if path is None:
        raise HTTPException(status_code=404, detail="No specification sheet is stored for this product.")
    return FileResponse(
        path,
        media_type=PDF_TYPE,
        headers={
            "Content-Disposition": f'inline; filename="{public_specification_name(product.specification_original_name)}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/products/{product_id}/specification", response_model=ManagedProduct)
async def upload_product_specification(
    product_id: uuid.UUID,
    specification: UploadFile = File(...),
    principal: tuple[AdminUser, AdminSession] = Depends(require_csrf),
    session: Session = Depends(get_session),
) -> ManagedProduct:
    owner, _row = principal
    settings = get_settings()
    limit = max_specification_bytes(settings)
    data = await specification.read(limit + 1)
    await specification.close()
    directory = specification_directory(settings)
    stored_name = None
    try:
        product = _owned_product(session, product_id)
        previous = product.specification_stored_name
        stored_name, size = save_specification(directory, data, specification.filename or "", specification.content_type, limit)
        product = update_product(
            session,
            product_id,
            {
                "specification_stored_name": stored_name,
                "specification_original_name": original_name(specification.filename),
                "specification_content_type": PDF_TYPE,
                "specification_size_bytes": size,
            },
            owner.email,
        )
    except HTTPException:
        raise
    except SpecificationRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except ProductNotFound as exc:
        remove_specification(directory, stored_name)
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ProductError as exc:
        remove_specification(directory, stored_name)
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except SQLAlchemyError:
        remove_specification(directory, stored_name)
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None
    except OSError:
        logger.exception("Specification sheet storage failed")
        remove_specification(directory, stored_name)
        raise HTTPException(status_code=503, detail=STORAGE_FAILED) from None
    if previous and previous != stored_name:
        remove_specification(directory, previous)
    return _view(product, session)


@router.delete("/products/{product_id}/specification", response_model=ManagedProduct)
def delete_product_specification(
    product_id: uuid.UUID,
    principal: tuple[AdminUser, AdminSession] = Depends(require_csrf),
    session: Session = Depends(get_session),
) -> ManagedProduct:
    owner, _row = principal
    directory = specification_directory(get_settings())
    try:
        product = _owned_product(session, product_id)
        previous = product.specification_stored_name
        changes: dict[str, object] = {
            "specification_stored_name": None,
            "specification_original_name": None,
            "specification_content_type": None,
            "specification_size_bytes": None,
        }
        if product.active:
            changes["specification_enabled"] = False
        product = update_product(session, product_id, changes, owner.email)
    except HTTPException:
        raise
    except ProductNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None
    try:
        remove_specification(directory, previous)
    except OSError:
        logger.exception("Specification sheet cleanup failed")
    return _view(product, session)


def _owned_product(session: Session, product_id: uuid.UUID) -> Product:
    product = get_product(session, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="The product does not exist.")
    return product


@router.post("/products/{product_id}/images", response_model=ManagedProduct, status_code=201)
async def add_product_image(
    product_id: uuid.UUID,
    image: UploadFile = File(...),
    principal: tuple[AdminUser, AdminSession] = Depends(require_csrf),
    session: Session = Depends(get_session),
) -> ManagedProduct:
    _owner, _row = principal
    data = await image.read(5 * 1024 * 1024 + 1)
    await image.close()
    directory = image_directory(get_settings())
    try:
        product = _owned_product(session, product_id)
        add_image(session, product, directory, data)
    except HTTPException:
        raise
    except ImageRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except GalleryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None
    return _view(product, session)


@router.post("/products/{product_id}/images/{image_id}", response_model=ManagedProduct)
async def replace_gallery_image(
    product_id: uuid.UUID,
    image_id: uuid.UUID,
    image: UploadFile = File(...),
    principal: tuple[AdminUser, AdminSession] = Depends(require_csrf),
    session: Session = Depends(get_session),
) -> ManagedProduct:
    _owner, _row = principal
    data = await image.read(5 * 1024 * 1024 + 1)
    await image.close()
    directory = image_directory(get_settings())
    try:
        product = _owned_product(session, product_id)
        replace_image(session, product, image_id, directory, data)
    except HTTPException:
        raise
    except ImageRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except GalleryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None
    return _view(product, session)


@router.delete("/products/{product_id}/images/{image_id}", response_model=ManagedProduct)
def delete_gallery_image(
    product_id: uuid.UUID,
    image_id: uuid.UUID,
    principal: tuple[AdminUser, AdminSession] = Depends(require_csrf),
    session: Session = Depends(get_session),
) -> ManagedProduct:
    _owner, _row = principal
    directory = image_directory(get_settings())
    try:
        product = _owned_product(session, product_id)
        remove_image(session, product, image_id, directory)
    except HTTPException:
        raise
    except GalleryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None
    return _view(product, session)


@router.put("/products/{product_id}/images/order", response_model=ManagedProduct)
def order_gallery_images(
    product_id: uuid.UUID,
    body: ImageOrder,
    principal: tuple[AdminUser, AdminSession] = Depends(require_csrf),
    session: Session = Depends(get_session),
) -> ManagedProduct:
    _owner, _row = principal
    try:
        product = _owned_product(session, product_id)
        reorder_images(session, product, body.image_ids)
    except HTTPException:
        raise
    except GalleryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None
    return _view(product, session)


@router.delete("/products/{product_id}", status_code=204)
def remove_product(
    product_id: uuid.UUID,
    principal: tuple[AdminUser, AdminSession] = Depends(require_csrf),
    session: Session = Depends(get_session),
) -> Response:
    owner, _row = principal
    try:
        delete_product_permanently(session, product_id, storage_roots(get_settings()), owner.email)
    except ProductNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except SQLAlchemyError:
        logger.exception("Product %s could not be deleted. The transaction was rolled back.", product_id)
        raise HTTPException(status_code=503, detail=DELETE_FAILED) from None
    return Response(status_code=204)


@router.get("/products/{product_id}/audit", response_model=ProductAuditList)
def product_audit(
    product_id: uuid.UUID,
    _principal: tuple[AdminUser, AdminSession] = Depends(require_owner),
    session: Session = Depends(get_session),
) -> ProductAuditList:
    try:
        events = list_audit_events(session, product_id)
    except ProductNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None
    return ProductAuditList(
        events=[
            ProductAuditEventView(created_at=event.created_at, actor=event.actor, changes=event.changes)
            for event in events
        ]
    )


