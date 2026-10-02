import base64
import hashlib
import hmac
import secrets
import uuid

from pydantic import SecretStr


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def new_random_value() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def hash_user_agent(user_agent: str | None) -> str | None:
    if not user_agent:
        return None
    return hashlib.sha256(user_agent.encode()).hexdigest()


def csrf_token(secret: SecretStr, session_id: uuid.UUID) -> str:
    digest = hmac.new(
        secret.get_secret_value().encode(), b"csrf:" + session_id.bytes, hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def values_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode(), right.encode())
