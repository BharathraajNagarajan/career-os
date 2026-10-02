import time
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from joserfc.jwk import RSAKey

from app.auth.oidc import SCOPES, OidcError, verify_id_token
from tests.auth.fake_idp import FakeIdentityProvider

NONCE = "nonce-value"


@pytest.fixture(scope="module")
def idp() -> FakeIdentityProvider:
    return FakeIdentityProvider()


def verify(idp: FakeIdentityProvider, token: str, nonce: str = NONCE) -> object:
    return verify_id_token(token, provider=idp, nonce=nonce)


def valid_claims(idp: FakeIdentityProvider, **overrides: Any) -> dict[str, Any]:
    return idp.claims(NONCE, subject="sub-1", email="ada@example.test", **overrides)


def test_valid_token_yields_identity(idp: FakeIdentityProvider) -> None:
    identity = verify_id_token(
        idp.sign(valid_claims(idp, name="Ada Example")), provider=idp, nonce=NONCE
    )

    assert identity.subject == "sub-1"
    assert identity.email == "ada@example.test"
    assert identity.name == "Ada Example"


def test_bad_signature_is_rejected(idp: FakeIdentityProvider) -> None:
    other_key = RSAKey.generate_key(2048, {"kid": "test-key", "use": "sig"})

    with pytest.raises(OidcError):
        verify(idp, idp.sign(valid_claims(idp), key=other_key))


def test_wrong_audience_is_rejected(idp: FakeIdentityProvider) -> None:
    with pytest.raises(OidcError):
        verify(idp, idp.sign(valid_claims(idp, aud="someone-else")))


def test_wrong_issuer_is_rejected(idp: FakeIdentityProvider) -> None:
    with pytest.raises(OidcError):
        verify(idp, idp.sign(valid_claims(idp, iss="https://evil.example.test")))


def test_expired_token_is_rejected(idp: FakeIdentityProvider) -> None:
    now = int(time.time())

    with pytest.raises(OidcError):
        verify(idp, idp.sign(valid_claims(idp, iat=now - 7200, exp=now - 3600)))


def test_small_clock_skew_is_tolerated(idp: FakeIdentityProvider) -> None:
    now = int(time.time())

    verify(idp, idp.sign(valid_claims(idp, iat=now - 400, exp=now - 30)))


def test_wrong_nonce_is_rejected(idp: FakeIdentityProvider) -> None:
    with pytest.raises(OidcError) as error:
        verify(idp, idp.sign(valid_claims(idp)), nonce="a-different-nonce")

    assert error.value.code == "nonce_mismatch"


def test_unverified_email_is_rejected(idp: FakeIdentityProvider) -> None:
    with pytest.raises(OidcError) as error:
        verify(idp, idp.sign(valid_claims(idp, email_verified=False)))

    assert error.value.code == "email_not_verified"


def test_missing_email_is_rejected(idp: FakeIdentityProvider) -> None:
    claims = valid_claims(idp)
    del claims["email"]

    with pytest.raises(OidcError):
        verify(idp, idp.sign(claims))


def test_unsigned_algorithm_none_is_rejected(idp: FakeIdentityProvider) -> None:
    header = "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0"
    payload = "eyJpc3MiOiJ4In0"

    with pytest.raises(OidcError):
        verify(idp, f"{header}.{payload}.")


def test_garbage_token_is_rejected(idp: FakeIdentityProvider) -> None:
    with pytest.raises(OidcError):
        verify(idp, "not-a-jwt")


def test_authorization_url_has_only_identity_scopes_and_pkce(idp: FakeIdentityProvider) -> None:
    url = idp.authorization_url(state="s", nonce="n", code_verifier="v" * 50)
    query = parse_qs(urlparse(url).query)

    assert SCOPES == "openid email profile"
    assert query["scope"] == ["openid email profile"]
    assert "gmail" not in url
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"]
    assert query["state"] == ["s"]
    assert query["nonce"] == ["n"]
    assert query["response_type"] == ["code"]


def test_rotated_key_is_found_by_refetching_the_jwks_once() -> None:
    idp = FakeIdentityProvider()
    new_key = idp.rotate_key()
    claims = idp.claims(NONCE, subject="sub-1", email="ada@example.test")

    identity = verify_id_token(idp.sign(claims, key=new_key), provider=idp, nonce=NONCE)

    assert identity.subject == "sub-1"
    assert idp.refresh_count == 1


def test_unknown_key_still_missing_after_refetch_is_rejected() -> None:
    idp = FakeIdentityProvider()
    stranger = RSAKey.generate_key(2048, {"kid": "never-published", "use": "sig"})
    claims = idp.claims(NONCE, subject="sub-1", email="ada@example.test")

    with pytest.raises(OidcError):
        verify_id_token(idp.sign(claims, key=stranger), provider=idp, nonce=NONCE)

    assert idp.refresh_count == 1


def test_known_key_does_not_refetch(idp: FakeIdentityProvider) -> None:
    before = idp.refresh_count

    verify(idp, idp.sign(valid_claims(idp)))

    assert idp.refresh_count == before
