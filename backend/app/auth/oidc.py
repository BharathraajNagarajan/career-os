import base64
import hmac
import json
from dataclasses import dataclass
from typing import Any, Protocol, cast

from authlib.integrations.httpx_client import OAuth2Client
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet, KeySetSerialization

SCOPES = "openid email profile"
CLOCK_LEEWAY_SECONDS = 60


class OidcError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class IdentityProvider(Protocol):
    @property
    def issuer(self) -> str: ...

    @property
    def client_id(self) -> str: ...

    def authorization_url(self, *, state: str, nonce: str, code_verifier: str) -> str: ...

    def exchange_code(self, *, code: str, code_verifier: str) -> str: ...

    def jwks(self, *, refresh: bool = False) -> dict[str, Any]: ...


@dataclass(frozen=True)
class VerifiedIdentity:
    subject: str
    email: str
    name: str | None


def build_authorization_url(
    *,
    endpoint: str,
    client_id: str,
    redirect_uri: str,
    state: str,
    nonce: str,
    code_verifier: str,
) -> str:
    client = OAuth2Client(
        client_id=client_id,
        scope=SCOPES,
        redirect_uri=redirect_uri,
        code_challenge_method="S256",
    )
    url, _ = client.create_authorization_url(
        endpoint, state=state, nonce=nonce, code_verifier=code_verifier
    )
    return str(url)


def _token_kid(id_token: str) -> str | None:
    try:
        segment = id_token.split(".", 1)[0]
        header = json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
    except ValueError as exc:
        raise OidcError("invalid_id_token") from exc
    kid = header.get("kid") if isinstance(header, dict) else None
    return kid if isinstance(kid, str) else None


def _signing_keys(id_token: str, provider: IdentityProvider) -> dict[str, Any]:
    keys = provider.jwks()
    kid = _token_kid(id_token)
    if kid is not None and kid not in {key.get("kid") for key in keys.get("keys", [])}:
        keys = provider.jwks(refresh=True)
    return keys


def verify_id_token(
    id_token: str, *, provider: IdentityProvider, nonce: str, now: int | None = None
) -> VerifiedIdentity:
    try:
        token = jwt.decode(
            id_token,
            KeySet.import_key_set(cast(KeySetSerialization, _signing_keys(id_token, provider))),
            algorithms=["RS256"],
        )
        claims = token.claims
        jwt.JWTClaimsRegistry(
            now=now,
            leeway=CLOCK_LEEWAY_SECONDS,
            iss={"essential": True, "value": provider.issuer},
            aud={"essential": True, "value": provider.client_id},
            sub={"essential": True},
            exp={"essential": True},
            iat={"essential": True},
            nonce={"essential": True},
        ).validate(claims)
    except (JoseError, ValueError, KeyError, TypeError) as exc:
        raise OidcError("invalid_id_token") from exc
    if not hmac.compare_digest(str(claims["nonce"]).encode(), nonce.encode()):
        raise OidcError("nonce_mismatch")
    email = claims.get("email")
    if claims.get("email_verified") not in (True, "true") or not isinstance(email, str):
        raise OidcError("email_not_verified")
    name = claims.get("name")
    return VerifiedIdentity(
        subject=str(claims["sub"]), email=email, name=name if isinstance(name, str) else None
    )
