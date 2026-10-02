import time
from collections.abc import Callable
from typing import Any

import httpx
from authlib.common.errors import AuthlibBaseError
from authlib.integrations.httpx_client import OAuth2Client

from app.auth.oidc import OidcError, build_authorization_url
from app.config import AuthSettings

DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
CACHE_SECONDS = 900
HTTP_TIMEOUT_SECONDS = 10.0


class GoogleIdentityProvider:
    def __init__(
        self,
        settings: AuthSettings,
        http: httpx.Client | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._http = http or httpx.Client(timeout=HTTP_TIMEOUT_SECONDS)
        self._clock = clock
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    @property
    def client_id(self) -> str:
        return self._settings.google_client_id

    @property
    def issuer(self) -> str:
        return str(self._discovery()["issuer"])

    def authorization_url(self, *, state: str, nonce: str, code_verifier: str) -> str:
        return build_authorization_url(
            endpoint=str(self._discovery()["authorization_endpoint"]),
            client_id=self.client_id,
            redirect_uri=self._settings.google_redirect_uri,
            state=state,
            nonce=nonce,
            code_verifier=code_verifier,
        )

    def exchange_code(self, *, code: str, code_verifier: str) -> str:
        try:
            with OAuth2Client(
                client_id=self.client_id,
                client_secret=self._settings.google_client_secret.get_secret_value(),
                redirect_uri=self._settings.google_redirect_uri,
                code_challenge_method="S256",
                timeout=HTTP_TIMEOUT_SECONDS,
            ) as client:
                token = client.fetch_token(
                    str(self._discovery()["token_endpoint"]),
                    grant_type="authorization_code",
                    code=code,
                    code_verifier=code_verifier,
                )
        except (AuthlibBaseError, httpx.HTTPError, KeyError) as exc:
            raise OidcError("token_exchange_failed") from exc
        id_token = token.get("id_token")
        if not isinstance(id_token, str):
            raise OidcError("token_exchange_failed")
        return id_token

    def jwks(self) -> dict[str, Any]:
        return self._cached("jwks", lambda: self._get(str(self._discovery()["jwks_uri"])))

    def _discovery(self) -> dict[str, Any]:
        return self._cached("discovery", lambda: self._get(DISCOVERY_URL))

    def _cached(self, name: str, load: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        cached = self._cache.get(name)
        if cached is not None and self._clock() - cached[0] < CACHE_SECONDS:
            return cached[1]
        value = load()
        self._cache[name] = (self._clock(), value)
        return value

    def _get(self, url: str) -> dict[str, Any]:
        try:
            response = self._http.get(url)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OidcError("provider_unavailable") from exc
        if not isinstance(body, dict):
            raise OidcError("provider_unavailable")
        return body
