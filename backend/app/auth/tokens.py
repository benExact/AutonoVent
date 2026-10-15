"""Random session values. The database stores only their SHA-256 hashes."""

import hashlib
import hmac
import secrets


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hashes_match(supplied: str, stored_hash: str) -> bool:
    return hmac.compare_digest(token_hash(supplied), stored_hash)
