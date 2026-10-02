import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Any

from joserfc import jwt
from joserfc.jwk import RSAKey

from app.auth.oidc import OidcError, build_authorization_url

FAKE_ISSUER = "https://idp.example.test"
FAKE_CLIENT_ID = "test-client-id"
FAKE_REDIRECT_URI = "http://localhost:5173/api/v1/auth/google/callback"


@dataclass
class PendingAuthorization:
    nonce: str
    code_challenge: str


class FakeIdentityProvider:
    issuer = FAKE_ISSUER
    client_id = FAKE_CLIENT_ID

    def __init__(self) -> None:
        self.key = RSAKey.generate_key(2048, {"kid": "test-key", "use": "sig"})
        self.published = [self.key]
        self.cached = [self.key]
        self.refresh_count = 0
        self.pending: dict[str, PendingAuthorization] = {}
        self.codes: dict[str, str] = {}

    def authorization_url(self, *, state: str, nonce: str, code_verifier: str) -> str:
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).rstrip(b"=")
        self.pending[state] = PendingAuthorization(nonce, challenge.decode())
        return build_authorization_url(
            endpoint=f"{FAKE_ISSUER}/authorize",
            client_id=FAKE_CLIENT_ID,
            redirect_uri=FAKE_REDIRECT_URI,
            state=state,
            nonce=nonce,
            code_verifier=code_verifier,
        )

    def exchange_code(self, *, code: str, code_verifier: str) -> str:
        entry = self.codes.pop(code, None)
        if entry is None:
            raise OidcError("token_exchange_failed")
        challenge, id_token = entry.split("|", 1)
        digest = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
        if digest.rstrip(b"=").decode() != challenge:
            raise OidcError("token_exchange_failed")
        return id_token

    def jwks(self, *, refresh: bool = False) -> dict[str, Any]:
        if refresh:
            self.refresh_count += 1
            self.cached = list(self.published)
        return {"keys": [key.as_dict(private=False) for key in self.cached]}

    def rotate_key(self) -> RSAKey:
        new_key = RSAKey.generate_key(2048, {"kid": f"rotated-{len(self.published)}", "use": "sig"})
        self.published = [new_key]
        return new_key

    def sign(self, claims: dict[str, Any], key: RSAKey | None = None) -> str:
        signing_key = key or self.key
        return jwt.encode({"alg": "RS256", "kid": signing_key.kid}, claims, signing_key)

    def claims(
        self,
        nonce: str,
        *,
        subject: str,
        email: str,
        name: str | None = "Test Person",
        **overrides: Any,
    ) -> dict[str, Any]:
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": FAKE_ISSUER,
            "aud": FAKE_CLIENT_ID,
            "sub": subject,
            "iat": now,
            "exp": now + 300,
            "nonce": nonce,
            "email": email,
            "email_verified": True,
            "name": name,
        }
        claims.update(overrides)
        return claims

    def issue_code(
        self,
        state: str,
        *,
        subject: str,
        email: str,
        name: str | None = "Test Person",
        **overrides: Any,
    ) -> str:
        pending = self.pending[state]
        nonce = overrides.pop("nonce", pending.nonce)
        token = self.sign(self.claims(nonce, subject=subject, email=email, name=name, **overrides))
        code = secrets.token_urlsafe(16)
        self.codes[code] = f"{pending.code_challenge}|{token}"
        return code
