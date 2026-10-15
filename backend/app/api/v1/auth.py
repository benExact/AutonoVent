"""Owner login and logout. There is no public registration route."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.service import (
    AUTH_REQUIRED,
    CSRF_FAILED,
    INVALID_LOGIN,
    RATE_LIMITED,
    LoginLimited,
    anonymous_csrf_ok,
    issue_csrf_token,
    login_owner,
    resolve_owner,
    revoke_session,
    session_csrf_ok,
)
from app.core.config import get_settings
from app.db.session import get_session
from app.models.admin import AdminUser
from app.models.auth import AdminSession

router = APIRouter()
SESSION_COOKIE = "autonovent_session"
CSRF_COOKIE = "autonovent_csrf"
CSRF_HEADER = "x-csrf-token"


class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


class OwnerSessionView(BaseModel):
    email: str
    role: str


def _cookie_kwargs(*, secure: bool, max_age: int, httponly: bool) -> dict[str, object]:
    return {
        "max_age": max_age,
        "httponly": httponly,
        "secure": secure,
        "samesite": "lax",
        "path": "/",
    }


def _set_auth_cookies(response: Response, *, raw_session: str, raw_csrf: str, max_age: int, secure: bool) -> None:
    response.set_cookie(SESSION_COOKIE, raw_session, **_cookie_kwargs(secure=secure, max_age=max_age, httponly=True))
    response.set_cookie(CSRF_COOKIE, raw_csrf, **_cookie_kwargs(secure=secure, max_age=max_age, httponly=False))


def _clear_auth_cookies(response: Response, *, secure: bool) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=secure, httponly=True, samesite="lax")
    response.delete_cookie(CSRF_COOKIE, path="/", secure=secure, httponly=False, samesite="lax")


def _client_source(request: Request) -> str:
    if request.client is None:
        return "unknown"
    return request.client.host


def require_owner(request: Request, session: Session = Depends(get_session)) -> tuple[AdminUser, AdminSession]:
    try:
        resolved = resolve_owner(session, get_settings(), request.cookies.get(SESSION_COOKIE))
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="The sign-in service is unavailable.") from None
    if resolved is None:
        raise HTTPException(status_code=401, detail=AUTH_REQUIRED)
    return resolved


def require_csrf(
    request: Request,
    principal: tuple[AdminUser, AdminSession] = Depends(require_owner),
) -> tuple[AdminUser, AdminSession]:
    owner, row = principal
    if not session_csrf_ok(row, request.headers.get(CSRF_HEADER), request.cookies.get(CSRF_COOKIE)):
        raise HTTPException(status_code=403, detail=CSRF_FAILED)
    return owner, row


@router.get("/csrf")
def issue_csrf(request: Request, response: Response, session: Session = Depends(get_session)) -> dict[str, str]:
    settings = get_settings()
    try:
        if resolve_owner(session, settings, request.cookies.get(SESSION_COOKIE)) is not None:
            return {"csrf_token": ""}
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="The sign-in service is unavailable.") from None
    token = issue_csrf_token()
    response.set_cookie(CSRF_COOKIE, token, **_cookie_kwargs(secure=settings.cookie_secure, max_age=3600, httponly=False))
    return {"csrf_token": token}


@router.post("/login", response_model=OwnerSessionView)
def login(body: LoginRequest, request: Request, response: Response, session: Session = Depends(get_session)) -> OwnerSessionView:
    if not anonymous_csrf_ok(request.headers.get(CSRF_HEADER), request.cookies.get(CSRF_COOKIE)):
        raise HTTPException(status_code=403, detail=CSRF_FAILED)
    settings = get_settings()
    try:
        result = login_owner(
            session,
            settings=settings,
            email=body.email,
            password=body.password,
            source=_client_source(request),
            previous_session_token=request.cookies.get(SESSION_COOKIE),
        )
    except LoginLimited:
        raise HTTPException(status_code=429, detail=RATE_LIMITED) from None
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="The sign-in service is unavailable.") from None
    if result is None:
        raise HTTPException(status_code=401, detail=INVALID_LOGIN)
    owner, raw_session, raw_csrf, lifetime = result
    _set_auth_cookies(response, raw_session=raw_session, raw_csrf=raw_csrf, max_age=lifetime, secure=settings.cookie_secure)
    return OwnerSessionView(email=owner.email, role=owner.role)


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    principal: tuple[AdminUser, AdminSession] = Depends(require_csrf),
    session: Session = Depends(get_session),
) -> Response:
    try:
        revoke_session(session, request.cookies.get(SESSION_COOKIE))
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="The sign-in service is unavailable.") from None
    response = Response(status_code=204)
    _clear_auth_cookies(response, secure=get_settings().cookie_secure)
    return response


@router.get("/me", response_model=OwnerSessionView)
def me(principal: tuple[AdminUser, AdminSession] = Depends(require_owner)) -> OwnerSessionView:
    owner, _row = principal
    return OwnerSessionView(email=owner.email, role=owner.role)
