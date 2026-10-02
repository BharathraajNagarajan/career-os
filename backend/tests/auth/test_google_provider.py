import httpx

from app.auth.google import DISCOVERY_URL, GoogleIdentityProvider
from app.config import AuthSettings

JWKS_URL = "https://idp.example.test/jwks"


def provider() -> tuple[GoogleIdentityProvider, dict[str, int]]:
    calls = {"jwks": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == DISCOVERY_URL:
            return httpx.Response(
                200, json={"issuer": "https://idp.example.test", "jwks_uri": JWKS_URL}
            )
        calls["jwks"] += 1
        return httpx.Response(200, json={"keys": [{"kid": f"key-{calls['jwks']}"}]})

    settings = AuthSettings(session_secret="x" * 40)
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return GoogleIdentityProvider(settings, http=http), calls


def test_jwks_is_cached_between_calls() -> None:
    google, calls = provider()

    google.jwks()
    google.jwks()

    assert calls["jwks"] == 1


def test_refresh_bypasses_the_cache_once_per_call() -> None:
    google, calls = provider()
    google.jwks()

    refreshed = google.jwks(refresh=True)
    google.jwks()

    assert calls["jwks"] == 2
    assert refreshed["keys"][0]["kid"] == "key-2"
