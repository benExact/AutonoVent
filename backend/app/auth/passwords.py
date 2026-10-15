"""Password hashing with Argon2id from the argon2-cffi library."""

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from argon2.low_level import Type

_hasher = PasswordHasher(type=Type.ID)
_DUMMY_HASH = _hasher.hash("owner-login-timing-placeholder")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError):
        return False


def verify_missing_owner(password: str) -> None:
    verify_password(_DUMMY_HASH, password)
