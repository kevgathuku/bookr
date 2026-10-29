"""Partner token issue/verify/rotate. Raw tokens never touch the database."""

import hashlib
import hmac
import secrets


def new_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, _hash(raw)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def verify(raw: str, token_hash: str) -> bool:
    return hmac.compare_digest(_hash(raw), token_hash)


def rotate() -> tuple[str, str]:
    return new_token()
