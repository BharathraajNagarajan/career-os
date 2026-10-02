This is the full Task 3 brief. GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are already filled in my local .env: do NOT add empty Google lines or modify them; only check the names exist, never print values.

You are my hands-on implementation and debugging partner for Career OS, working in C:\Users\bhara\career-os on Windows with Docker Desktop (WSL2). GNU Make is not installed; use docker compose, uv and npm directly. Everything you need is in this brief, the repository, and docs/.

STEP 0: PRE-FLIGHT
1. Confirm you are running on a Sonnet model. If not, tell me before doing anything else.
2. git switch main && git pull. Confirm main contains the merged Task 2 work (docs/checkpoints/task-02.md, backend/app/jobs/) and the working tree is clean.
3. Confirm python resolves to backend\.venv, Docker is running (docker info), and node -v is v22.x.
4. Create branch task-03-auth from main.
5. FIRST save this entire brief verbatim to docs/briefs/task-03.md and commit it ("docs: Task 3 brief").

AUTHORIZED SCOPE
Only Phase 1A Task 3: Authentication. Do NOT start Task 4 (profile, artifacts, resumes). The only new tables are auth_identities and sessions. No other tables.

SOURCE OF TRUTH (read before coding)
- docs/spec/phase-0-spec.md (FROZEN): 0A, 1.3 (invariants, especially INV-02, INV-06, INV-11, INV-18), 2.1, 3 (authentication row), 4.1, 4.2 (User, AuthIdentity, Session), 7.1 (sign-in scopes vs the separate Gmail grant), 8 (threats T1, T7, T8, T9, T13, T16), 9 (Auth module and boundary rules: 404 not 403 for foreign resources), 11 (authorization and isolation testing), 14 (Task 3 acceptance criteria)
- docs/adr/004-authentication.md, docs/adr/003-tenant-isolation-model.md
- docs/architecture/database.md, docs/checkpoints/task-02.md, README.md, backend/app/ (existing db, tenancy, jobs, worker, config, logging)
The spec wins over this brief. If they disagree, stop and escalate.

WORKING RULES
- You own local operations for this task only: terminal, Docker/Compose, Git, dependencies, tests, debugging, code edits.
- Never install anything system-wide without asking. Project dependencies via uv add / npm install are fine.
- Approve-each-time: git push, docker compose down -v, deleting files outside build caches.
- NEVER add Co-Authored-By, "Generated with Claude" or any Claude attribution to commits or PR text. I am the sole contributor.
- Learning mode: briefly explain meaningful concepts as you work (OAuth 2.0 authorization code flow, OIDC ID tokens, state vs nonce vs PKCE, JWKS signature verification, session tokens and hashing, idle vs absolute expiry, cookie flags, CSRF, SECURITY DEFINER functions, isolation testing, root causes of errors). Skip trivial commands.
- Debugging rule: observe → identify failing layer → hypothesis → inspect evidence → smallest justified change → rerun failing check → rerun related checks. Say explicitly when a problem is environmental.
- No code comments; minimal readable code; don't restructure working Task 1/2 code unless required.
- Secrets: never print, log or commit GOOGLE_CLIENT_SECRET, SESSION_SECRET, session tokens, ID tokens, authorization codes or PKCE verifiers.

TASK 3 ACCEPTANCE CRITERIA (spec section 14)
Google OIDC sign-in with PKCE, state and nonce; sessions stored hashed with idle and absolute expiry; CSRF on mutations; sign-out and revoke-session work; account deletion removes all user rows and objects; isolation test harness runs against every registered route; no Gmail scope at sign-in.

IMPLEMENTATION DECISIONS ALREADY MADE BY THE PLANNING CHAT (they translate the spec, they do not change it)

A. Tables (migration 0002, hand-reviewed, with grants and working downgrade)
- auth_identities (user-owned): id, user_id, provider CHECK ('google'), provider_subject, email_at_login, created_at, last_login_at. UNIQUE (provider, provider_subject). UNIQUE (user_id, id) via the owned-table convention. Holds no tokens.
- sessions (user-owned): id (UUIDv7, the public handle), user_id, token_hash bytea UNIQUE (SHA-256 of a 32-byte random token; the raw token exists only in the cookie), created_at, last_seen_at, expires_at (absolute), user_agent_hash text NULL. UNIQUE (user_id, id).
- Grants to career_os_app: auth_identities SELECT, INSERT, UPDATE; sessions SELECT, INSERT, UPDATE, DELETE.

B. Privileged account-deletion path (the spec's "account deletion needs a privileged path")
- In migration 0002, create a SQL function delete_user_account(target uuid) RETURNS boolean, LANGUAGE plpgsql, SECURITY DEFINER, owned by the migration owner, with SET search_path = pg_catalog, public. It deletes the users row only WHERE id = target AND status = 'deletion_requested', and returns whether a row was deleted. REVOKE ALL ON FUNCTION ... FROM PUBLIC; GRANT EXECUTE TO career_os_app. Explain SECURITY DEFINER and why search_path must be pinned.
- ON DELETE CASCADE removes the user's domain_events, jobs, auth_identities and sessions. The app role still has no DELETE on users or domain_events (keep the existing tests passing).
- Request flow: POST /api/v1/account/deletion with JSON {"confirm": "DELETE MY ACCOUNT"}, authenticated + CSRF. One transaction: set users.status = 'deletion_requested', delete all of the user's sessions, enqueue job kind "delete_account" as a SYSTEM job (user_id NULL, payload {"user_id": ...}, unique_key "delete_account:<user_id>"). Respond 202 and clear the session and CSRF cookies.
  The job is a system job on purpose: a user-owned job row would be cascade-deleted mid-transaction by the deletion itself.
- Worker handler "delete_account": re-resolve the user (INV-18; must be deletion_requested), run registered deletion hooks (an account-deletion hook registry, empty for now; Task 4 registers artifact/object deletion so "objects" are covered when they exist), then call delete_user_account. Idempotent if the user is already gone.
- A user in deletion_requested cannot sign in or use any session.

C. OIDC sign-in (Google), authorization code flow + PKCE (S256) + state + nonce
- Scopes exactly: openid email profile. A test asserts the authorization URL contains only these scopes and no gmail scope (spec 7.1).
- Provider boundary: an IdentityProvider interface (authorization endpoint, token exchange, JWKS, issuer, client_id) with a Google implementation (discovery document + JWKS fetched and cached) and a FakeIdentityProvider for tests that signs ID tokens with a test RSA key and serves its JWKS in-process (no network in tests).
- Our code, not the provider, verifies the ID token: signature against JWKS, iss, aud = client_id, exp/iat with small leeway, nonce matches, email_verified is true. Tests cover each failure (bad signature, wrong aud, wrong iss, expired, wrong nonce, email not verified).
- Library: use Authlib (spec section 3) for PKCE, the authorization URL and JOSE/ID-token verification, plus a runtime HTTP client for discovery/token/JWKS calls. Pick the minimal combination, add it with uv, and justify it in the report.
- Pre-auth state: no new table. Store state, nonce, code_verifier and return path in a short-lived (10 min) ENCRYPTED, HttpOnly, SameSite=Lax cookie scoped to path /api/v1/auth, encrypted with a key derived from SESSION_SECRET (for example Fernet via the cryptography package). Single use: cleared on callback. The callback rejects a missing/expired cookie, state mismatch, or an IdP error parameter, with a redirect to the frontend sign-in page carrying a generic error code (never details).
- Account resolution on callback:
  - existing auth_identity (google, sub) → that user; update last_login_at and email_at_login.
  - no identity and no user with that email (case-insensitive) → create user (primary_email from the verified email, display_name from name) + identity in one transaction.
  - no identity but a user already exists with that email → reject with error code account_conflict (prevents account takeover by email matching).
  - user status deletion_requested → reject.
- Session rotation: every successful sign-in creates a brand-new session (never reuses a token) and clears the pre-auth cookie.

D. Sessions
- Settings: SESSION_SECRET (SecretStr, min 32 chars), SESSION_IDLE_TIMEOUT_HOURS (default 168), SESSION_ABSOLUTE_TIMEOUT_HOURS (default 720), SESSION_COOKIE_SECURE (default true), APP_BASE_URL (default http://localhost:5173), GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET (SecretStr). The redirect URI is APP_BASE_URL + /api/v1/auth/google/callback, built from config, never from request headers.
- Session cookie: name career_os_session, HttpOnly, Secure per SESSION_COOKIE_SECURE, SameSite=Lax, Path=/, no Domain attribute; Max-Age = absolute timeout.
- A FastAPI dependency resolves the current user: read the cookie, hash it, look up the session, reject if expired (absolute), idle (now - last_seen_at > idle timeout) or the user is not active; on rejection delete the session row and clear cookies; return an AuthContext(user_id, session_id). Update last_seen_at at most once every 5 minutes to avoid a write per request. Unauthenticated → 401.
- Constant-time comparisons where secrets are compared.

E. CSRF (spec T7: SameSite=Lax + double-submit token on all non-GET requests)
- CSRF token = HMAC-SHA256(SESSION_SECRET, session id), base64url. Set as a readable (not HttpOnly) cookie career_os_csrf at sign-in.
- Every non-GET/HEAD/OPTIONS request to /api/v1 must send header X-CSRF-Token equal to the expected HMAC for the current session; compare in constant time. Failure → 403 with error code csrf_failed. Tests cover missing, wrong and token-from-another-session.

F. API (prefix /api/v1; typed errors; foreign resources return 404, never 403)
- GET /api/v1/auth/google/start?return_to=/path (relative paths only; reject absolute URLs to prevent open redirects) → 302 to Google
- GET /api/v1/auth/google/callback → sets cookies, 302 to APP_BASE_URL + return path
- POST /api/v1/auth/logout → deletes the current session, clears cookies, 204
- GET /api/v1/auth/me → id, primary_email, display_name, status
- GET /api/v1/auth/sessions → caller's sessions only: id, created_at, last_seen_at, expires_at, current (bool). Never the token or hash.
- DELETE /api/v1/auth/sessions/{session_id} → revoke one of the caller's sessions; another user's session id → 404 (INV-18 via resolve_owned)
- POST /api/v1/account/deletion → as in B
- Routers handle HTTP only; services own rules; repositories own SQL and take user_id keyword-only.

G. Isolation test harness (spec 11; must run against every registered route)
- A test enumerates app.routes. Every route must be classified in one place as either PUBLIC (healthz, auth start, auth callback; explicit list) or PROTECTED with an isolation case. A route that is neither fails the test, so a future endpoint without an isolation case fails CI.
- For every PROTECTED route: no session → 401; persona B acting on persona A's resource ids → 404; list endpoints called by B never return A's rows.
- Use two synthetic personas with unrelated data (INV-01: no real people or careers).

H. Frontend (minimal, functional, no design work; design tokens are Task 10)
- Sign-in page with "Sign in with Google" linking to /api/v1/auth/google/start, showing a plain message for error codes.
- Route guard: call /api/v1/auth/me; unauthenticated → sign-in page; authenticated → existing Home placeholder.
- Settings page: list sessions with "Sign out this session" per row, "Sign out" for the current one, and "Delete account" with a typed confirmation.
- One fetch wrapper: credentials same-origin, adds X-CSRF-Token from the career_os_csrf cookie on mutating requests, maps 401 to the sign-in page.
- Vitest tests for the guard, the wrapper's CSRF header, and the sign-in error message.

I. OpenAPI types (spec 3: OpenAPI as the API contract)
- Add a backend script that exports openapi.json and a frontend step using openapi-typescript to generate src/api/schema.d.ts. Frontend API calls use those types. CI fails if the generated file is out of date.

J. Compose, config, CI
- Compose passes GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, SESSION_SECRET, APP_BASE_URL, SESSION_* to the api service only (explicit allowlist, like Task 2). The worker does not get OAuth or session secrets.
- Add placeholders to .env.example. In my local .env, add SESSION_SECRET (random, never printed) only if missing. GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are already set by me: do not add, duplicate or modify them.
- CI: throwaway values for SESSION_SECRET and Google settings; all auth tests use the fake IdP.
- Add the CI guard promised after Task 2: set REQUIRE_DB_TESTS=1 in the CI backend job and make the test session fail (not skip) if DB tests would be skipped while it is set.

K. Docs
- docs/architecture/auth.md: sign-in sequence (start → Google → callback), what state, nonce and PKCE each prevent, ID token checks, session model and expiry, cookie flags, CSRF scheme, account-deletion flow including the SECURITY DEFINER function, isolation harness rule ("every new route needs an isolation case"), and the Google Cloud setup steps for local development.
- Update README (configuration table and auth notes) and docs/architecture/database.md (new tables, grants, function).

ACCEPTANCE CHECKS YOU MUST RUN
1. Backend: ruff check, ruff format --check, mypy, pytest with Postgres (all DB tests, including Task 2's, must still pass).
2. Migrations on an empty DB: upgrade head → alembic check → downgrade base → upgrade head.
3. Frontend: lint, typecheck, test, build; the generated OpenAPI types are up to date.
4. Stack: docker compose up --build -d; migrate exits 0; /healthz is 200; GET /api/v1/auth/me without a cookie is 401; /api/v1/auth/google/start redirects to accounts.google.com with only openid email profile scopes and a code_challenge (show the URL with client_id redacted).
5. Live Google login (my Google credentials are already in .env): I sign in through http://localhost:5173; you then verify, via psql as the owner, that one users row, one auth_identities row and one sessions row exist, that sessions.token_hash is not equal to the cookie value, and that cookie flags are as specified (ask me to read them from browser devtools). Then I sign out, and you confirm the session row is gone.
6. Account deletion with a synthetic user (not my real account): create one via the fake-IdP path in a test, or directly as owner in a scratch DB, request deletion, run the worker, and show that all rows for that user are gone while other users are untouched.
7. Push the branch (ask me first) and confirm GitHub Actions is green for backend (including DB tests, the REQUIRE_DB_TESTS guard and migrations), frontend (including the OpenAPI types check) and secrets.

ESCALATION
If you find a spec contradiction, a required architecture change, a required scope change, a security issue affecting the frozen design, a schema requirement beyond auth_identities, sessions and the deletion function, or a missing prerequisite that changes architecture: STOP that part and report:
PROBLEM / EVIDENCE / WHY THE CURRENT SPEC CANNOT BE FOLLOWED / SMALLEST OPTIONS / RECOMMENDATION / WHAT IS BLOCKED
Continue only with work that does not depend on the outcome. Do not silently redesign.

GIT AND FINISH
- Commit in logical steps on task-03-auth with clear messages and no attribution trailers.
- Push (ask first). gh is not authenticated; give me the compare URL to open the PR. Do NOT merge.
- Write docs/checkpoints/task-03.md in this format, commit and push it:
  What was implemented (mapped to each acceptance criterion) / Evidence / Changes outside the expected file set (file, change, reason) or none / Important things I learned (4 to 8 bullets, specific) / Checks run and results (table) / Deviations from the frozen spec or none / Unresolved issues / Git state (branch, commits, PR URL, CI status) / Recommendation: approve or not, with reason
- Then STOP. Do not start Task 4.

Begin with Step 0.
