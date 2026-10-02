# Task 5 checkpoint: Model gateway and review framework

Branch `task-05-model-gateway`. Brief: [docs/briefs/task-05.md](../briefs/task-05.md). Design: [docs/architecture/llm.md](../architecture/llm.md) and [docs/architecture/review.md](../architecture/review.md).

## What was implemented (mapped to the acceptance criteria)

| Acceptance criterion (spec 14) | Implementation |
| --- | --- |
| `ModelGateway` with structured-output and streaming methods | `app/llm/gateway.py`. `structured(...)` returns a `StructuredResult` (validated Pydantic object, `run_id`, `repaired`). `stream(...)` returns a `ModelStream` yielding text deltas, exposing `run_id` and `usage`, settling on completion, error, cancel or close. Both take user id, purpose, prompt id, tier, variables, context manifest and `max_output_tokens`, and refuse a purpose or tier that differs from the registered prompt (INV-17). No endpoint, job or scheduler calls a model in this task. |
| One vendor adapter and a fake | `ModelProvider` protocol (`complete`, `stream`). `FakeProvider` (default; scripted or deterministic output, deterministic chunking, failure injection) and `AnthropicProvider` in `app/llm/providers/anthropic.py`, the only module importing the SDK (a test scans `app`, `tests` and `alembic`). Structured output uses `output_config.format` with a JSON schema; the SDK's own retries are off so cost accounting stays exact. Tested through an `httpx2` mock transport (request body, usage, HTTP and connection errors, refusal, streaming), never the network. |
| Model tiers by configuration | `LLM_MODEL_FAST`, `LLM_MODEL_REASONING`, `LLM_MODEL_PRICES` (JSON, per million tokens), `LLM_PROVIDER` (default `fake`), `ANTHROPIC_API_KEY` (`SecretStr`, Compose passes it to API and worker only), `LLM_REQUEST_TIMEOUT_SECONDS`, `LLM_DEFAULT_MAX_OUTPUT_TOKENS`. Startup fails clearly if a tier's model has no price or if `anthropic` is selected without a key. A test scans `app/` for vendor model names; none are hard-coded. Anthropic ids and prices (read from the public docs on 2026-10-02) are commented placeholders in `.env.example` only. |
| Prompt registry with versions | `app/llm/prompts/`. Rejects duplicate `(id, version)` and unknown ids; `get` returns the latest version. `prompts.lock.json` pins a SHA-256 per registered version over purpose, tier, templates, JSON schema and untrusted variables; a test fails if content changes without a version bump. Two generic self-test prompts only. |
| Every call writes an `LlmRun` with manifest | Migration 0004, `llm_runs`: spec fields plus `tier`, `max_output_tokens`, `reserved_cost_usd`, `cost_usd`, `attempt`, `repair_of_run_id` (composite FK), `created_at`, `settled_at`. Typed `context_manifest` and `output` JSONB. No prompt or model text stored (a test asserts a marker string and an invalid reply never appear in any column). |
| Validation with one repair retry | Validate with Pydantic; on failure exactly one repair call (new row, `attempt = 2`, `repair_of_run_id`) whose prompt carries the validation errors (location and message only) and the previous reply wrapped as untrusted data. Second failure raises `llm_output_invalid`; a third call never happens. Unvalidated output is never returned. |
| Per-user daily cost cap: reservation, settlement, typed refusal, budget indicator (13.1) | Reservation in one short transaction under `pg_advisory_xact_lock` on a stable 64-bit hash of the user id: spent today (UTC day, `coalesce(cost_usd, reserved_cost_usd)`) plus worst case (input estimate of UTF-8 bytes / 2 + 64, plus `max_output_tokens`, at configured prices, rounded up) against the cap; otherwise insert `reserved` and commit. Provider call outside the transaction; settlement in a second transaction guarded by `status = 'reserved'`. Refusal raises `llm_budget_exhausted`, provider never called, API maps it to 429. Race test with real Postgres and threads: exactly one success and one refusal; a control test removes the lock and shows both succeed past the cap. `GET /api/v1/llm/budget` returns `spent_usd`, `cap_usd`, `remaining_usd` (strings, six decimals) and `resets_at`. Settings page shows the indicator and a plain exhausted message. |
| `review_items` with Confirm, Edit + Confirm, Reject / Ignore dispatching to domain commands | Migration 0004, `review_items` with `state_version`, `llm_run_id` (composite FK), `decided_payload`, `decision_note`, `evidence_ref_id` (plain uuid, no FK). `ReviewHandlerRegistry` maps proposal type to `{payload model, confirm(ctx, payload)}`; the framework writes no domain state. Pure `transition()` with exhaustive tests. Each command is one transaction with an optimistic version check: stale is 409 `conflict`, non-pending is 409 `invalid_transition`, no handler is 422 `no_handler` (reject still works), bad edit is 422 `invalid_payload`. The version-checked `UPDATE` runs before the handler so concurrent confirms apply the command exactly once (threaded test). A raising handler rolls everything back (test). `ReviewItemRepository.create` validates against the registered model. Routes: list, get, confirm, edit-confirm, reject, each with an isolation case. Review page: pending items, plain-text payload, Confirm, Edit + Confirm (JSON textarea), Reject with note, conflict message and refresh. |

Also delivered: logging allowlist extended with run, prompt, model, token, cost and review fields; untrusted-content wrapper (`wrap_untrusted`) that neutralises embedded delimiters in any case or spacing, with a standing system notice; import-boundary tests for `app/llm` and `app/review`; a socket guard that makes every test fail if it tries a non-loopback connection; `llm.md`, `review.md`, README and `database.md` updates; regenerated OpenAPI contract and frontend types.

## Evidence

**Backend:** `ruff check` and `ruff format --check` clean; `mypy` strict, 139 files, no issues; `pytest` with Postgres and `REQUIRE_DB_TESTS=1`: **539 passed, 1 skipped, 0 failed** (all Task 1 to 4 tests included). The skip is the symlink-escape storage test, which skips on this Windows host and runs on Linux CI. The three concurrency tests (budget race, no-lock control, concurrent confirm) passed 10 consecutive runs.

**Migrations (empty scratch database):** bootstrap, `upgrade head` (0001 to 0004), `alembic check` ("No new upgrade operations detected"), `downgrade base` (0 tables left), `upgrade head`, `alembic check` all pass. The scratch database was dropped afterwards.

**Frontend:** `npm run lint` (max warnings 0), `tsc -b`, `vitest run` (11 files, 53 tests passed), `npm run build` pass; types regenerated from the final OpenAPI export.

**Stack (`docker compose up --build -d`):** `migrate` exited 0 (applied 0004 to the local dev database), `/healthz` 200, API healthy. A script created a synthetic user and session as owner and deleted them afterwards (0 runs, 0 items, 0 users left). Output:
- Budget endpoint on the running container: `spent_usd '0'`, `cap_usd '1.00'`, `remaining_usd '1.00'`, reset `2026-10-03T00:00:00Z`.
- Gateway with the fake provider against the running database. In flight: `status=reserved reserved=0.001402 cost=None settled=no`. After: `status=succeeded in=108 out=12 reserved=0.001402 cost=0.000168 settled=yes`.
- Budget endpoint afterwards: `spent_usd '0.000168'`, `remaining_usd '0.999832'`.
- Tiny test cap (injected into the script's gateway only, your `.env` untouched): `refused: code=llm_budget_exhausted; provider calls made after refusal: 0`; row count unchanged.
- Review items (test handler registered by the script in an in-process API over the real database): confirm 200, status `confirmed`, version 2, profile headline updated; stale confirm 409 `conflict`; confirm again 409 `invalid_transition`; reject 200 with note, headline unchanged.
- Real container API, which registers no handlers: confirm of a `claim` item 422 `no_handler`, listed with `confirmable: false`, reject 200.

**Optional live call (check 5): not run.** No `ANTHROPIC_API_KEY` is set in `.env`, so per the brief I did not ask or call. The adapter is covered by mock-transport tests only; real token counts and prices have not been observed.

## Changes outside the expected file set

| File | Change | Reason |
| --- | --- | --- |
| `backend/app/core/errors.py` | Handler mapping `LlmBudgetExhausted` to 429 | Brief: the API maps the refusal |
| `backend/app/core/logging.py` | Allowlist gained run, prompt, model, token, cost, status, tier, review fields | Brief: extend the allowlist as needed |
| `backend/app/main.py` | Includes the llm and review routers; `create_app(review_registry=...)` keeps the registry on `app.state` | Routes and handler registration |
| `backend/app/config.py` | New LLM settings, `ModelPrice`, startup validation | Brief decision B |
| `backend/app/db/models.py` | New enums and the two tables | Brief decision A |
| `backend/pyproject.toml`, `uv.lock` | Added `anthropic` (with its dependencies) | Brief: add via uv |
| `backend/tests/conftest.py` | Autouse socket guard blocking non-loopback connections | Brief: a test asserts no test touches the network |
| `backend/tests/db/conftest.py`, `test_isolation.py` | Test app uses a recording review registry; harness seeds llm runs and review items and gains six route cases | Harness rule: every route gets a case |
| `infra/docker-compose.yml`, `.env.example` | LLM variables to API and worker only; `LLM_MODEL_PRICES` and the key pass through unset | Brief decision H |
| `README.md`, `docs/architecture/database.md` | Configuration rows, section, new tables and grants | Brief decision H |
| `frontend/src/app/Layout.tsx`, `router.tsx`, `Layout.test.tsx`, `routes/Settings.tsx` | Review nav link and route; budget indicator on Settings | Brief decision G |

## Important things I learned

- SQLAlchemy writes Python `None` into a JSONB column as JSON `null`, not SQL `NULL`. That broke the `decided_payload IS NULL OR status = 'confirmed'` check on the first confirm, and would have silently stored JSON `null` in `llm_runs.output` (it reads back as `None` either way, so the first test passed). Fixed with `JSONB(none_as_null=True)` and tests that query `IS NULL` in SQL.
- Check-then-act races need the check and the write under one lock. The advisory lock is held only for the short reserve transaction, not the network call, so concurrent calls by one user stay fast. My first race test was itself racy: once call 1 settles at its real, much smaller cost, call 2 legitimately fits. Forcing the two reservations to overlap (the provider holds until the other call is refused) made it deterministic, and a no-lock control test shows the race is real.
- Claiming the review row with the version-checked `UPDATE` before running the handler is what makes confirm exactly-once. If the handler ran first, two requests that both read version 1 would both apply the command; with the claim first, the second blocks on the row lock and then matches zero rows.
- Column-level `GRANT UPDATE` makes the records immutable by privilege: runs can only settle, review proposals can never be rewritten. Tests try eight and four immutable columns and expect `InsufficientPrivilege`.
- The newer Claude models reject forced `tool_choice`, so structured output uses `output_config.format` with a JSON schema. The SDK's `transform_schema` mutates the schema it is given (my provider test caught this), so the adapter passes a deep copy. Anthropic SDK 1.x is built on `httpx2`, not `httpx`, which is why mock transports come from `httpx2`.
- Reservation estimates must over-count: bytes divided by two is about twice the real token count for English, and newer Anthropic tokenizers produce about 30% more tokens than older ones; both fit under the estimate. A refused call writes no row, so a retry loop against a capped user cannot grow the table.
- Delimiting untrusted text lowers risk but is not a defence by itself; the wrapper neutralises embedded delimiters, and the real controls stay structural (schema output, no side-effect tools, review items before any state change).
- Environmental: shell heredocs broke again on this host (one test file), so files were written with the editor tool. `.env` starts with a BOM and holds JSON values, so it cannot be sourced by a shell; test scripts read single values instead.

## Checks run and results

| Check | Result |
| --- | --- |
| `ruff check`, `ruff format --check` | Pass |
| `mypy` (strict) | Pass, 139 files |
| `pytest` with Postgres, `REQUIRE_DB_TESTS=1` | 539 passed, 1 skipped (symlink test, host limitation), 0 failed |
| Concurrency tests repeated 10 times | 10 of 10 pass |
| OpenAPI contract up to date | Pass |
| Migrations: upgrade, `alembic check`, downgrade base, upgrade, check | Pass |
| Frontend `npm run lint`, `typecheck`, `test` (53 tests), `build` | Pass |
| Generated API types up to date | Pass |
| Stack: compose up, migrate exit 0, `/healthz` 200 | Pass |
| Stack: budget 0, reserved then settled row, budget reflects spend | Pass |
| Stack: refusal with a tiny test cap, no provider call | Pass |
| Stack: review confirm, stale, repeat, reject, no handler | Pass |
| Optional live Anthropic call | Not run (no key in `.env`) |
| GitHub Actions (backend, frontend, secrets) | Pending push |

## Deviations from the frozen spec

None. Clarifications where the brief left room: a refused call is not recorded as a row (the spec says it is refused and never sent; recording would let a loop grow the table); `llm_runs.status` has three values (`reserved`, `succeeded`, `failed`); `UPDATE` privileges on both tables are column-level, which is stricter than a table-level grant; the migration is revision `0004` (the next after `0003`); `structured` takes an `output_type` for static typing and returns the object together with its `run_id`, which producers need for `llm_run_id`.

## Unresolved issues

- The Anthropic adapter has not made a real call. Token counts, the structured-output request shape and prices are verified only against mocks and the public docs; run the optional live check once a key is available.
- Prices in `.env.example` are assumptions from the public pricing page on 2026-10-02.
- No automatic release of stale `reserved` rows: a crashed call keeps counting at its reserved cost until the UTC day ends (documented, conservative).
- `app/llm/router.py` imports auth dependencies, so the INV-11 import test exempts it from the strict allowlist and checks it against a small HTTP allowlist instead.
- The fake provider's default model names and prices are Python defaults so tests and CI need no configuration; they are labels, not vendor values.
- Review expiry automation, batch confirm, typed edit forms and the AI-action budget indicator (Task 10) are deferred. Production registers no review handlers until Tasks 6 and 9.
- The local dev database now has migration 0004 applied (expected).

## Git state

Branch `task-05-model-gateway` from `main` (merge of Task 4). Commits (oldest first): `docs: Task 5 brief`; schema, gateway, prompt registry and review framework; gateway, review and isolation tests with JSONB null handling and OpenAPI; configuration, Compose and docs; frontend; deterministic budget race test and six-decimal money; this checkpoint. Not pushed yet. PR URL: none (gh is not authenticated); compare URL once pushed: https://github.com/BharathraajNagarajan/career-os/compare/main...task-05-model-gateway. CI status: pending push.

## Recommendation

Approve once Actions are green. Every acceptance criterion has automated tests plus live-stack evidence, and the frozen spec is followed without deviation. The two caveats are that the Anthropic adapter is mock-tested only (run the optional live check when you have a key) and that no review handler exists in production until the first producers arrive.
