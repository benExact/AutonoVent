"""Owner sessions, login limits, and the one-off owner account."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.auth.passwords import hash_password, verify_missing_owner, verify_password
from app.auth.tokens import hashes_match, new_token, token_hash
from app.core.config import Settings
from app.models.admin import AdminUser
from app.models.auth import AdminSession, LoginAttempt

INVALID_LOGIN = "The email or password is not correct."
RATE_LIMITED = "Too many login attempts. Try again later."
CSRF_FAILED = "This request could not be verified."
AUTH_REQUIRED = "Authentication is required."


class OwnerExistsError(Exception):
    """An owner account is already stored."""


class OwnerProvisioningError(Exception):
    """The supplied owner details cannot be stored."""


def create_initial_owner(session: Session, email: str, password: str) -> AdminUser:
    normalized = _email(email)
    if len(password) < 12 or len(password) > 200:
        raise OwnerProvisioningError("The password must be 12 to 200 characters.")
    with session.begin():
        existing = session.scalar(select(func.count()).select_from(AdminUser))
        if existing:
            raise OwnerExistsError("An owner account already exists.")
        owner = AdminUser(email=normalized, password_hash=hash_password(password), role="owner")
        session.add(owner)
        session.flush()
        owner_id = owner.id
    stored = session.get(AdminUser, owner_id)
    if stored is None:
        raise OwnerProvisioningError("The owner account could not be read after it was saved.")
    if session.in_transaction():
        session.commit()
    return stored


def issue_csrf_token() -> str:
    return new_token()


def anonymous_csrf_ok(header: str | None, cookie: str | None) -> bool:
    if not header or not cookie:
        return False
    return hmac_equal(header, cookie)


def login_owner(
    session: Session,
    *,
    settings: Settings,
    email: str,
    password: str,
    source: str,
    previous_session_token: str | None,
) -> tuple[AdminUser, str, str, int] | None:
    subject = token_hash(_email_or_blank(email))
    source_digest = token_hash(source or "unknown")
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(seconds=settings.auth_login_window_seconds)
    with session.begin():
        _delete_old_attempts(session, window_start)
        if _attempt_limit_reached(session, settings, subject, source_digest, window_start):
            raise LoginLimited()
        owner = session.scalar(select(AdminUser).where(AdminUser.email == _email_or_blank(email)))
        if owner is None or owner.disabled_at is not None or owner.role != "owner":
            verify_missing_owner(password)
            accepted = False
        else:
            accepted = verify_password(owner.password_hash, password)
        if not accepted:
            session.add(LoginAttempt(subject_hash=subject, source_hash=source_digest, attempted_at=now))
            return None
        if previous_session_token:
            previous = session.scalar(
                select(AdminSession).where(AdminSession.token_hash == token_hash(previous_session_token))
            )
            if previous is not None and previous.revoked_at is None:
                previous.revoked_at = now
        session.execute(delete(LoginAttempt).where(LoginAttempt.subject_hash == subject))
        raw_session, raw_csrf, lifetime = _new_session(session, owner, settings, now)
        owner_id = owner.id
    stored = session.get(AdminUser, owner_id)
    if stored is None:
        return None
    if session.in_transaction():
        session.commit()
    return stored, raw_session, raw_csrf, lifetime


def resolve_owner(session: Session, settings: Settings, raw_session_token: str | None) -> tuple[AdminUser, AdminSession] | None:
    if not raw_session_token:
        return None
    now = datetime.now(timezone.utc)
    idle = timedelta(seconds=settings.auth_session_idle_seconds)
    with session.begin():
        row = session.scalar(select(AdminSession).where(AdminSession.token_hash == token_hash(raw_session_token)))
        if row is None:
            return None
        expired = row.revoked_at is not None or row.expires_at <= now or row.last_seen_at + idle <= now
        if expired:
            if row.revoked_at is None:
                row.revoked_at = now
            return None
        owner = session.get(AdminUser, row.admin_user_id)
        if owner is None or owner.disabled_at is not None or owner.role != "owner":
            row.revoked_at = now
            return None
        row.last_seen_at = now
        owner_id = owner.id
        session_id = row.id
    stored_owner = session.get(AdminUser, owner_id)
    stored_session = session.get(AdminSession, session_id)
    if stored_owner is None or stored_session is None:
        return None
    if session.in_transaction():
        session.commit()
    return stored_owner, stored_session


def revoke_session(db: Session, raw_session_token: str | None) -> None:
    if not raw_session_token:
        return
    now = datetime.now(timezone.utc)
    with db.begin():
        row = db.scalar(select(AdminSession).where(AdminSession.token_hash == token_hash(raw_session_token)))
        if row is not None and row.revoked_at is None:
            row.revoked_at = now


def session_csrf_ok(row: AdminSession, header: str | None, cookie: str | None) -> bool:
    if not header or not cookie or not hmac_equal(header, cookie):
        return False
    return hashes_match(header, row.csrf_token_hash)


class LoginLimited(Exception):
    """Too many recent login attempts."""


def _new_session(session: Session, owner: AdminUser, settings: Settings, now: datetime) -> tuple[str, str, int]:
    raw_session = new_token()
    raw_csrf = new_token()
    lifetime = settings.auth_session_ttl_seconds
    session.add(
        AdminSession(
            admin_user_id=owner.id,
            token_hash=token_hash(raw_session),
            csrf_token_hash=token_hash(raw_csrf),
            created_at=now,
            expires_at=now + timedelta(seconds=lifetime),
            last_seen_at=now,
        )
    )
    return raw_session, raw_csrf, lifetime


def _attempt_limit_reached(session: Session, settings: Settings, subject: str, source: str, window_start: datetime) -> bool:
    subject_count = session.scalar(
        select(func.count()).select_from(LoginAttempt).where(
            LoginAttempt.subject_hash == subject, LoginAttempt.attempted_at >= window_start
        )
    )
    source_count = session.scalar(
        select(func.count()).select_from(LoginAttempt).where(
            LoginAttempt.source_hash == source, LoginAttempt.attempted_at >= window_start
        )
    )
    limit = settings.auth_login_max_failures
    return (subject_count or 0) >= limit or (source_count or 0) >= limit


def _delete_old_attempts(session: Session, window_start: datetime) -> None:
    session.execute(delete(LoginAttempt).where(or_(LoginAttempt.attempted_at < window_start)))


def _email(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) < 3 or len(normalized) > 254 or "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
        raise OwnerProvisioningError("A valid email address is required.")
    return normalized


def _email_or_blank(value: str) -> str:
    try:
        return _email(value)
    except OwnerProvisioningError:
        return value.strip().lower()


def hmac_equal(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left, right)
