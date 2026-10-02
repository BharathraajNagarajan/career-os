import base64
import hashlib
import hmac
import json
from dataclasses import asdict, dataclass

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

PREAUTH_COOKIE = "career_os_preauth"
PREAUTH_PATH = "/api/v1/auth"
PREAUTH_TTL_SECONDS = 600


@dataclass(frozen=True)
class PreAuth:
    state: str
    nonce: str
    code_verifier: str
    return_to: str


def _fernet(secret: SecretStr) -> Fernet:
    key = hmac.new(
        secret.get_secret_value().encode(), b"preauth-cookie-v1", hashlib.sha256
    ).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def seal(secret: SecretStr, value: PreAuth) -> str:
    return _fernet(secret).encrypt(json.dumps(asdict(value)).encode()).decode()


def unseal(secret: SecretStr, sealed: str | None) -> PreAuth | None:
    if not sealed:
        return None
    try:
        data = json.loads(_fernet(secret).decrypt(sealed.encode(), ttl=PREAUTH_TTL_SECONDS))
        return PreAuth(
            state=str(data["state"]),
            nonce=str(data["nonce"]),
            code_verifier=str(data["code_verifier"]),
            return_to=str(data["return_to"]),
        )
    except (InvalidToken, ValueError, KeyError, TypeError):
        return None
