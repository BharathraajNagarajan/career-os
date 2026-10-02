# Authentication

Google OpenID Connect sign-in, server-side sessions, CSRF protection and account deletion. Spec references: 3, 4.2, 7.1, 8 (T1, T7, T8, T9, T13, T16), 9, 11, 14. Decisions: ADR-003, ADR-004.

Sign-in requests only `openid email profile`. Gmail access is a separate, later grant (spec 7.1); a test asserts the authorization URL contains no Gmail scope.

## Sign-in sequence

```
Browser                    API (/api/v1/auth)                 Google
  | GET /google/start         |                                  |
  |-------------------------->| make state, nonce, code_verifier |
  |                           | seal them in the pre-auth cookie |
  | 302 accounts.google.com   |                                  |
  |<--------------------------|                                  |
  |------------------------------- authorize (state, nonce, code_challenge) -->|
  | 302 /google/callback?code&state                              |
  |<-------------------------------------------------------------|
  | GET /google/callback      |                                  |
  |-------------------------->| check state against cookie       |
  |                           | POST token endpoint (code, code_verifier, secret)
  |                           |--------------------------------->|
  |                           |<----- id_token ------------------|
  |                           | verify ID token, resolve account |
  |                           | create a new session             |
  | 302 APP_BASE_URL + path   |                                  |
  |   Set-Cookie session+csrf |                                  |
  |<--------------------------|                                  |
```

What each value prevents:

| Value | Prevents |
| --- | --- |
| `state` | Login CSRF. The callback only proceeds if the `state` Google returns equals the one sealed in this browser's pre-auth cookie, so an attacker cannot make a victim finish the attacker's sign-in. |
| `nonce` | ID token replay. It is sent to Google, echoed inside the signed ID token, and compared with the value in the cookie, so a token minted for another login cannot be injected into this one. |
| PKCE (`code_verifier`, S256 `code_challenge`) | Authorization code interception. Only the party holding the verifier can redeem the code, so a stolen code is useless. |

The pre-auth cookie `career_os_preauth` holds `state`, `nonce`, `code_verifier` and the return path. It is encrypted and authenticated with Fernet using a key derived from `SESSION_SECRET`, is HttpOnly, SameSite=Lax, scoped to `Path=/api/v1/auth`, expires after 10 minutes and is cleared by every callback outcome, so it is single use. No table stores pre-auth state.

`return_to` must be a relative path starting with a single `/`. Absolute URLs, `//host`, backslashes and control characters are rejected with 400, which prevents open redirects. The redirect URI is built from `APP_BASE_URL`, never from request headers.

### ID token checks

The application verifies the token itself (`app/auth/oidc.py`), with Authlib's `joserfc`:

- signature against the provider's JWKS, RS256 only (so `alg: none` and key-confusion tokens fail),
- `iss` equals the discovered issuer, `aud` equals our client ID,
- `exp` and `iat` present and valid with 60 seconds of leeway,
- `nonce` equals the cookie's value (constant-time comparison),
- `email_verified` is true and `email` is present.

Discovery and JWKS documents are cached for 15 minutes. The provider sits behind the `IdentityProvider` protocol; tests use `FakeIdentityProvider`, which signs tokens with a test RSA key and enforces PKCE, so no test touches the network.

### Account resolution

| Situation | Result |
| --- | --- |
| `(google, sub)` identity exists, user active | Sign in; update `last_login_at` and `email_at_login` |
| No identity, no user with that email (case-insensitive) | Create user and identity in one transaction |
| No identity, but a user already has that email | Reject with `account_conflict` (never link by email, to prevent takeover) |
| User is `deletion_requested` | Reject with `account_unavailable` |

Failures redirect to `APP_BASE_URL/sign-in?error=<code>` with a generic code only. Details go to the server log as `error_code`.

## Sessions

- The session token is 32 random bytes (`secrets.token_urlsafe`). Only its SHA-256 hash is stored (`sessions.token_hash`); the raw token exists only in the cookie. A database leak therefore does not yield usable sessions.
- Every sign-in creates a new session. A token is never reused or upgraded (session fixation).
- Absolute expiry: `expires_at` is set at creation (`SESSION_ABSOLUTE_TIMEOUT_HOURS`, default 720). Idle expiry: a session unused for longer than `SESSION_IDLE_TIMEOUT_HOURS` (default 168) is rejected. `last_seen_at` is refreshed at most once every 5 minutes to avoid a write per request.
- A rejected session (expired, idle, or user not active) is deleted and the cookies are cleared. Missing or unknown tokens return 401.
- `GET /auth/sessions` lists only the caller's sessions (never tokens or hashes). `DELETE /auth/sessions/{id}` goes through `resolve_owned`, so another user's session id returns 404.

Cookies:

| Cookie | Flags | Purpose |
| --- | --- | --- |
| `career_os_session` | HttpOnly, SameSite=Lax, `Path=/`, `Secure` per `SESSION_COOKIE_SECURE`, no `Domain`, `Max-Age` = absolute timeout | Session token |
| `career_os_csrf` | Readable by JavaScript, SameSite=Lax, `Path=/`, `Secure` per setting, same `Max-Age` | CSRF token |
| `career_os_preauth` | HttpOnly, SameSite=Lax, `Path=/api/v1/auth`, `Secure` per setting, 10 minutes | Sign-in state |

`SESSION_COOKIE_SECURE` defaults to `true` in the application. The local Compose file and `.env.example` set it to `false` because local development is served over plain HTTP; never do this outside local development.

## CSRF

SameSite=Lax is the first layer. The second is a double-submit token (spec T7): `career_os_csrf` carries `base64url(HMAC-SHA256(SESSION_SECRET, "csrf:" + session id))`. Every non-GET/HEAD/OPTIONS request under `/api/v1` must send it in `X-CSRF-Token`; the server recomputes the expected value for the current session and compares in constant time. A missing, wrong or other-session token gets 403 `csrf_failed`. An unauthenticated mutation gets 401 first. Because the token is derived from the session id, a token from another session never validates.

## Account deletion

`POST /api/v1/account/deletion` with `{"confirm": "DELETE MY ACCOUNT"}`, authenticated and CSRF-protected.

1. One transaction: set `users.status = 'deletion_requested'`, delete all of the user's sessions, enqueue a `delete_account` job. The response is 202 and clears the cookies. The job is a system job (`user_id` NULL, payload `{"user_id": ...}`, `unique_key = delete_account:<user_id>`); a user-owned job would be removed by the very cascade it triggers.
2. The worker re-resolves the user (INV-18) and requires `deletion_requested`. It runs the registered deletion hooks (`app/auth/deletion.py`; Task 4 registers artifact and object deletion here), then calls `delete_user_account(user_id)`. It does nothing if the user is already gone, so retries are safe.
3. `ON DELETE CASCADE` removes the user's `domain_events`, `jobs`, `auth_identities` and `sessions`.

A user in `deletion_requested` cannot sign in and none of their sessions authenticates.

### Why a SECURITY DEFINER function

`career_os_app` has no DELETE on `users` or `domain_events`; the event log is append-only by privilege (INV-04). Account deletion still has to remove those rows. The migration creates `delete_user_account(target uuid)` owned by the migration owner with `SECURITY DEFINER`, so it runs with the owner's rights, and the application role only gets `EXECUTE`. It deletes the `users` row only `WHERE id = target AND status = 'deletion_requested'` and returns whether a row was deleted, so it cannot be used to delete an active account.

`SET search_path = pg_catalog, public` is pinned because a definer function runs with elevated rights: without a fixed search path, a caller could create an object with the same name as one the function references in a schema earlier in their own path and have it executed as the owner. The function also uses schema-qualified names. `EXECUTE` is revoked from `PUBLIC` and granted only to `career_os_app`.

## Isolation harness (spec 11)

`tests/db/test_isolation.py` lists every registered route (from the OpenAPI schema plus the framework routes) and requires each to be classified in one place: `PUBLIC` (explicit list: health, sign-in start and callback, built-in docs) or `PROTECTED` with an isolation case. For every protected route it checks: no session gives 401, a second persona using the first persona's ids gets 404 (never 403), list endpoints never return the other persona's rows, and acting as one persona never changes the other's state. Personas are synthetic.

**Every new route needs an isolation case.** An unclassified route fails `test_every_registered_route_is_classified`, so CI fails. Routes hidden from the schema also fail the test.

## Google Cloud setup for local development

1. In the Google Cloud console, create or choose a project and open APIs & Services, OAuth consent screen. Configure it as External, in Testing mode, and add your own Google account as a test user.
2. Under Credentials, create an OAuth client ID of type Web application.
3. Add the authorized redirect URI `http://localhost:5173/api/v1/auth/google/callback` (it must match `APP_BASE_URL` plus `/api/v1/auth/google/callback` exactly).
4. Put the client ID and secret in your local `.env` as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, and set `SESSION_SECRET` to at least 32 random characters (for example `python -c "import secrets; print(secrets.token_urlsafe(48))"`). `.env` is git-ignored; never commit or paste these values.
5. Sign-in requests only the basic OpenID scopes, so no sensitive-scope verification is needed.
6. Start the stack and open http://localhost:5173.
