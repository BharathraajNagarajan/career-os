# Task 3 checkpoint: Authentication

Branch `task-03-auth`. Brief: [docs/briefs/task-03.md](../briefs/task-03.md). Design: [docs/architecture/auth.md](../architecture/auth.md).

## What was implemented (mapped to the acceptance criteria)

| Acceptance criterion (spec 14) | Implementation |
| --- | --- |
| Google OIDC sign-in with PKCE, state and nonce | `app/auth/router.py` (`/auth/google/start`, `/auth/google/callback`), `oidc.py`, `google.py`. State, nonce and code verifier live in an encrypted, HttpOnly, SameSite=Lax, 10-minute, single-use cookie scoped to `/api/v1/auth` (`preauth.py`). The ID token is verified by our code (RS256 signature against JWKS, iss, aud, exp/iat with 60 s leeway, nonce, `email_verified`). Account resolution rejects a matching email with no identity (`account_conflict`). |
| Sessions stored hashed, idle and absolute expiry | `sessions.token_hash` is the SHA-256 of a 32-byte random token; absolute expiry in `expires_at`, idle check against `last_seen_at`, refreshed at most every 5 minutes (`auth/service.py`). Every sign-in creates a new session. |
| CSRF on mutations | SameSite=Lax plus double-submit token: `HMAC-SHA256(SESSION_SECRET, session id)` in `career_os_csrf`, required in `X-CSRF-Token` on every non-safe `/api/v1` request, constant-time compare, 403 `csrf_failed` (`auth/deps.py`). |
| Sign-out and revoke-session | `POST /auth/logout`, `GET /auth/sessions`, `DELETE /auth/sessions/{id}`; a foreign session id is 404 through `resolve_owned`. Settings page in the frontend. |
| Account deletion removes all user rows and objects | `POST /account/deletion` (typed confirmation, CSRF) marks the user `deletion_requested`, drops sessions and enqueues a system job; the worker handler runs deletion hooks (empty registry; Task 4 registers object deletion) and calls the `delete_user_account` SECURITY DEFINER function (migration 0002). Cascades remove events, jobs, identities and sessions. |
| Isolation harness runs against every registered route | `tests/db/test_isolation.py`: every route must be PUBLIC or PROTECTED with a case; no session gives 401, foreign ids give 404, lists never leak, and acting as B never changes A. A self-test proves an unclassified new route fails. |
| No Gmail scope at sign-in | Scopes are exactly `openid email profile`; asserted in a unit test and in the integration test. |

Also delivered: migration 0002 (`auth_identities`, `sessions`, grants, function, working downgrade); OpenAPI export (`backend/openapi.json`) and generated frontend types; frontend sign-in page, route guard, settings page and a fetch wrapper that adds the CSRF header and maps 401 to the sign-in page; Compose passes OAuth and session settings to the API only; the `REQUIRE_DB_TESTS` CI guard.

## Evidence

**Local checks on the final code (commit f07bc9f):** ruff check and format clean; mypy strict, 70 files, no issues; 176 backend tests passed, 0 failed, 0 skipped, with `REQUIRE_DB_TESTS=1` and Postgres; frontend lint, typecheck, 16 tests and build pass; regenerating `openapi.json` and `schema.d.ts` produced no diff.

**Migrations (empty scratch DB):** bootstrap, `upgrade head`, `alembic check` ("No new upgrade operations detected"), `downgrade base`, `upgrade head` all exited 0. The scratch DB was dropped afterwards.

**Stack:** `docker compose up --build -d`; `migrate` exited 0; `/healthz` 200; `GET /api/v1/auth/me` without a cookie returned 401 `{"error":{"code":"unauthenticated"}}`. `/api/v1/auth/google/start` returned a 302 to `https://accounts.google.com/o/oauth2/v2/auth?response_type=code&client_id=<REDACTED>&redirect_uri=http%3A%2F%2Flocalhost%3A5173%2Fapi%2Fv1%2Fauth%2Fgoogle%2Fcallback&scope=openid+email+profile&state=<REDACTED>&nonce=<REDACTED>&code_challenge=<challenge>&code_challenge_method=S256`. The worker container has no Google or session secret variables.

**Live Google sign-in (check 5, your account):**
- After sign-in, as the database owner: 1 `users` row (active), 1 `auth_identities` row (provider `google`, subject and login time set), 1 `sessions` row for the same user.
- `sessions.token_hash` is 32 bytes (a raw SHA-256 digest); the cookie is a 43-character URL-safe token, so they cannot be equal. I never saw the cookie value. `test_successful_sign_in_creates_user_identity_and_hashed_session` asserts the stored hash equals the SHA-256 of the cookie. `expires_at` was exactly 30 days after `created_at`; a user-agent hash was stored.
- Cookie flags from your Edge devtools (values not copied): `career_os_session` HttpOnly, Secure, SameSite=Lax, Path=/, expires 2026-11-01T14:40:49Z (30 days). `career_os_csrf` readable by JavaScript (HttpOnly blank, as designed), Secure, SameSite=Lax, Path=/, same expiry. An `ajs_anonymous_id` cookie also present is an unrelated analytics cookie from another localhost app.
- `SESSION_COOKIE_SECURE=true` was used locally as you requested; Edge accepted the Secure cookie on `http://localhost` and sign-in worked, so no revert to `false` was needed.
- Sign-out from the Settings page: `POST /api/v1/auth/logout` returned 204 (api log) and the owner query then showed 1 user, 1 identity, 0 sessions.

**Account deletion (check 6):** exercised with synthetic personas, not a real account, in `tests/db/test_account_deletion.py`. The request marks the user `deletion_requested`, removes the sessions, enqueues a system job with `unique_key = delete_account:<user_id>` and clears cookies. Running the worker once removes every row for that user in `users`, `auth_identities`, `sessions` and `domain_events`, leaves the bystander's rows and session unchanged, and marks the job `succeeded`. Hooks run before the user row is removed; the handler refuses a user not pending deletion and is idempotent when the user is gone.

**GitHub Actions:** run 37025776128 on f07bc9f: backend, frontend and secrets jobs all succeeded (backend includes DB tests with `REQUIRE_DB_TESTS=1`, the OpenAPI drift check and migrations; frontend includes the generated-types drift check). The checkpoint commit itself will be validated by the next run after you approve its push.

**`/me` latency (NFR-04 target: deterministic reads p95 < 300 ms).** 20 sequential calls, synthetic session (created and removed as owner, never your session):

| Measurement | p50 | p95 |
| --- | --- | --- |
| `/me` client-side via `localhost:8000` | 222 ms | 292 ms |
| `/healthz` (no DB) via `localhost:8000` | 219 ms | 224 ms |
| `/me` client-side via `127.0.0.1:8000` | 10 ms | 13 ms |
| `/me` server-side `duration_ms` (warm) | 7 ms | 10 ms |
| `/me` via Vite proxy `localhost:5173` | 228 ms | 411 ms (max 537) |

`/healthz` does no database work and still costs about 219 ms through `localhost`, while `127.0.0.1` costs about 10 ms. The floor is therefore environmental (this Windows host resolves `localhost` to IPv6 first and falls back to IPv4 because Docker publishes on `127.0.0.1`), not Task 3 code. Server-side time is p50 7 ms, p95 10 ms warm. A stale session that triggers the `last_seen_at` write adds about 5 ms. The first request after an API restart took 152 ms because it opens a new database connection. No code was changed. See Unresolved issues for what is not explained.

## Changes outside the expected file set

| File | Change | Reason |
| --- | --- | --- |
| `backend/app/main.py` | `create_app` accepts `session_factory` and `identity_provider`, installs error handlers and the auth router, disposes the engine on shutdown | The API had no database session or routes before Task 3 |
| `backend/app/worker.py` | Calls `register_job_handlers` at startup | Registers the `delete_account` handler |
| `backend/tests/db/conftest.py` | Appended `idp`, `auth_settings` and `app` fixtures and imports | Shared DB fixtures for the auth integration tests |
| `backend/tests/conftest.py` | `REQUIRE_DB_TESTS=1` raises instead of skipping DB tests | CI guard promised in the Task 2 checkpoint |
| `backend/pyproject.toml`, `uv.lock` | Added `authlib`, `httpx`, `cryptography`; mypy `ignore_missing_imports` for `authlib.*` | Authlib ships no type stubs |
| `frontend/package.json`, `package-lock.json` | Added `openapi-typescript`, a `generate:api` script, and an npm `overrides` entry (see below) | OpenAPI types (decision I) |
| `frontend/src/app/Layout.tsx` | Added a Settings link in the header | Reachability of the Settings page; a link in `HomePlaceholder` broke its Task 2 test, which renders without a router |
| `frontend/src/app/router.tsx` | Added sign-in, guard and settings routes | Required by decision H |
| `infra/docker-compose.yml`, `.env.example`, `.github/workflows/ci.yml` | Auth variables for the API service only, placeholders, CI env values, drift checks and the DB-test guard | Decision J |
| `README.md`, `docs/architecture/database.md` | Auth section, configuration table, new tables and function | Decision K |

**openapi-typescript TypeScript peer override.** `openapi-typescript` 7.13.0 declares a peer dependency of `typescript ^5.x`, while the project uses TypeScript 6.0.3, so `npm install` failed with `ERESOLVE`. I added `"overrides": {"openapi-typescript": {"typescript": "$typescript"}}` to `frontend/package.json`. This applies to that one package only (a repo-wide `legacy-peer-deps` would hide other conflicts). Type generation, lint, typecheck, build and CI all work with it. Remove the override when `openapi-typescript` publishes TypeScript 6 support.

## Important things I learned

- `state`, `nonce` and PKCE block three different attacks: `state` ties the callback to the browser that started the login (login CSRF), `nonce` ties the signed ID token to this login (replay), and PKCE makes a stolen authorization code unredeemable without the verifier. All three are needed; none replaces another.
- Verifying the ID token ourselves with RS256 pinned means `alg: none` and wrong-key tokens fail by construction. The `alg=none` and bad-signature cases are explicit tests.
- Storing only the SHA-256 of a 32-byte random session token is enough, with no salt or slow hash, because the token has 256 bits of entropy; the hash only protects against a database leak.
- A SECURITY DEFINER function runs with its owner's rights, so its `search_path` must be pinned (`pg_catalog, public`) or a caller could shadow a name the function uses. We also revoke `EXECUTE` from `PUBLIC`; Postgres grants it to everyone by default.
- The deletion job has to be a system job (`user_id` NULL): a user-owned job row would be removed by the cascade it triggers, in the middle of its own transaction.
- FastAPI 0.141 wraps included routers in a private `_IncludedRouter`, so `app.routes` no longer lists API routes. The isolation harness enumerates routes from the OpenAPI schema instead, and fails if any route is hidden from the schema.
- Sourcing the whole `.env` into the shell broke unrelated settings parsing (`CORS_ALLOWED_ORIGINS` and others); exporting only the two variables the tests need fixed it. That was an environment mistake, not a code bug.
- `localhost` can add about 200 ms per request on this machine (IPv6 then IPv4 fallback), which looked like a slow API until `/healthz` showed the same cost.

## Checks run and results

| Check | Result |
| --- | --- |
| `ruff check`, `ruff format --check` | Pass (70 files formatted) |
| `mypy` (strict) | Pass, 70 files |
| `pytest` with Postgres, `REQUIRE_DB_TESTS=1` | 176 passed, 0 failed, 0 skipped (includes Task 2's tests) |
| `REQUIRE_DB_TESTS=1` without `TEST_ADMIN_DATABASE_URL` | Fails with a usage error instead of skipping |
| Migrations: upgrade, `alembic check`, downgrade, upgrade | Pass |
| Frontend lint, typecheck, test (16), build | Pass |
| OpenAPI contract and generated types up to date | Pass (no diff after regenerating) |
| Stack up; migrate 0; `/healthz` 200; `/me` unauthenticated 401; start redirect to Google with only `openid email profile` and S256 | Pass |
| Live Google sign-in, DB rows, hash, cookie flags, sign-out | Pass |
| Account deletion with synthetic users | Pass (tests) |
| GitHub Actions on f07bc9f (backend, frontend, secrets) | Green |

## Deviations from the frozen spec

None identified. The spec and brief did not conflict anywhere I found. One implementation choice worth noting: `SESSION_COOKIE_SECURE` defaults to `true` everywhere, including local Compose.

## Unresolved issues

- **`/me` latency, NFR-04 not fully confirmed.** Server-side `/me` is fast (p50 7 ms, p95 10 ms warm). Client-side p95 through `localhost` was 292 ms, with an environmental floor of about 219 ms (the `localhost` IPv6 then IPv4 fallback on this Windows and Docker host, shown by `/healthz` costing the same and `127.0.0.1` costing about 10 ms). The 441 to 482 ms server-side values seen in the API log for browser requests were not reproduced: a cold connection costs about 150 ms and the `last_seen_at` write about 5 ms. They are probably browser traffic through the Vite proxy after idle gaps (the proxy path showed p95 411 ms, max 537 ms), but I did not isolate it. Re-measure on a host without the `localhost` fallback, or in a deployed environment, before treating NFR-04 as confirmed.
- JWKS is cached for 15 minutes with no forced refresh on an unknown `kid`; after a Google key rotation, sign-ins could fail for up to 15 minutes.
- A deletion job for a user who is not `deletion_requested` raises and is retried up to the job's attempt limit before failing; it is harmless but not fail-fast.
- The account-deletion flow was verified only with synthetic users and the real worker path in tests, not through the browser against a live account, as agreed.
- The deletion hook registry is empty; Task 4 must register artifact and object deletion so "all objects" is true once objects exist.
- Provider HTTP calls are synchronous with a 10-second timeout, run in FastAPI's threadpool; there is no circuit breaker if Google is slow.

## Git state

- Branch: `task-03-auth`, pushed to `origin/task-03-auth`, 10 commits ahead of `main` before this checkpoint (brief, settings and models, migration, OIDC boundary, service and routes, tests and harness, compose, CI and OpenAPI, frontend, docs, cookie default).
- PR: not opened (`gh` is not authenticated). Compare URL: https://github.com/BharathraajNagarajan/career-os/compare/main...task-03-auth
- CI: green on f07bc9f (run 37025776128): backend, frontend, secrets.

## Recommendation

Approve. Every acceptance criterion is implemented and evidenced locally, in CI and in a live Google sign-in and sign-out, with no spec deviations. The remaining items are recorded above; the `/me` latency one is environmental on this host and should be re-measured elsewhere, but nothing indicates a defect in the code.
