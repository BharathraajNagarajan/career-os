You are my hands-on implementation and debugging partner for Career OS, working in C:\Users\bhara\career-os on Windows with Docker Desktop (WSL2). GNU Make is not installed; use docker compose, uv and npm directly. Everything you need is in this brief, the repository, and docs/.

STEP 0: PRE-FLIGHT
1. Confirm you are running on a Sonnet model. If not, tell me before doing anything else.
2. git switch main && git pull. Confirm main contains the merged Task 4 work (docs/checkpoints/task-04.md, backend/app/resumes/, backend/app/artifacts/) and the working tree is clean.
3. Confirm python resolves to backend\.venv, Docker is running (docker info), and node -v is v22.x.
4. Create branch task-05-model-gateway from main.
5. FIRST save this entire brief verbatim to docs/briefs/task-05.md and commit it ("docs: Task 5 brief"). Long shell heredocs break on this host: write files with your editor tool, not cat <<EOF.

AUTHORIZED SCOPE
Only Phase 1A Task 5: model gateway and review framework. The only new tables are llm_runs and review_items. Do NOT start Task 6 (JD ingestion) or Task 9 (resume extraction, claims, skills). No real producer of review items is built in this task; the first producers arrive in Tasks 6 and 9.

SOURCE OF TRUTH (read before coding)
- docs/spec/phase-0-spec.md (FROZEN): 0A, 1.3 (invariants, especially INV-01, INV-07, INV-11, INV-14, INV-17, INV-18), 2.1 (model gateway, review inbox rows), 2.2, 3 (LLM rows), 4.1 (provenance columns, state versions, JSONB rules), 4.2/4.5/4.7 (ReviewItem and LlmRun rows; use the latest field lists in the frozen file), 5 (ReviewItem state machine), 6.1, 8 (T2, T3, T12, T14), 9 (Review module, boundary rules, typed errors), 11 (LLM structured output testing), 13.1 (daily cost cap), 14 (Task 5 acceptance criteria)
- docs/adr/007-model-gateway-with-single-vendor-adapter-and-daily-cost-cap.md, ADR-017 if relevant
- docs/architecture/database.md, auth.md, artifacts.md; docs/checkpoints/task-04.md
- backend/app/ (db conventions, tenancy, versioning, jobs, auth deps, error handling, logging allowlist, isolation harness)
The spec wins over this brief. If they disagree, stop and escalate.

WORKING RULES
- You own local operations for this task only: terminal, Docker/Compose, Git, dependencies, tests, debugging, code edits.
- Never install anything system-wide without asking. Project dependencies via uv add / npm install are fine.
- Approve-each-time: git push, docker compose down -v, deleting files outside build caches, and ANY real (paid) model API call.
- NEVER add Co-Authored-By, "Generated with Claude" or any Claude attribution to commits or PR text. I am the sole contributor.
- Learning mode: briefly explain meaningful concepts as you work (gateway/adapter pattern, structured output and schema validation, repair retries, streaming and SSE basics, reserve-then-settle budgeting, per-user advisory locks and race conditions, context manifests, prompt versioning, prompt injection and untrusted-content delimiting, import-boundary tests, optimistic concurrency, command dispatch). Skip trivial commands.
- Debugging rule: observe → identify failing layer → hypothesis → inspect evidence → smallest justified change → rerun failing check → rerun related checks. Say explicitly when a problem is environmental.
- Use 127.0.0.1 (not localhost) for local DB URLs and curl. Browser checks use http://localhost:5173 (the OAuth redirect URI and cookies are bound to localhost).
- No code comments; minimal readable code; don't restructure working Task 1-4 code unless required.
- INV-01: all prompts, fixtures and test data are generic and synthetic. No real people, companies or career data.
- Never log prompts, model inputs, model outputs, document text or API keys. Log only ids, purpose, prompt id/version, model, token counts, cost, latency, status and error codes (extend the logging allowlist as needed).
- Commit after every logical step so work is recoverable if usage limits interrupt the session.

TASK 5 ACCEPTANCE CRITERIA (spec section 14)
ModelGateway with structured-output and streaming methods; one vendor adapter and a fake; model tiers by configuration; prompt registry with versions; every call writes an LlmRun with manifest; validation with one repair retry; per-user daily LLM cost cap with reservation, settlement, typed refusal and a budget indicator (13.1); review_items with the Confirm, Edit + Confirm, Reject / Ignore command framework that dispatches to domain commands (first producers arrive in Tasks 6 and 9).

IMPLEMENTATION DECISIONS ALREADY MADE BY THE PLANNING CHAT (they translate the spec, they do not change it)

A. Tables (migration 0005-style next revision after 0003; hand-reviewed, grants, working downgrade)
- llm_runs (user-owned): the spec's LlmRun fields (purpose CHECK with the spec's purpose list, prompt_id, prompt_version, provider, model, input_tokens, output_tokens, latency_ms, status, error_code, context_manifest typed JSONB, output typed JSONB nullable), plus these fields authorized by 13.1 ("enforced from llm_runs totals"): tier, max_output_tokens, reserved_cost_usd numeric(10,6), cost_usd numeric(10,6) nullable until settled, attempt (1 or 2), repair_of_run_id nullable (composite FK to llm_runs), created_at, settled_at. status CHECK ('reserved','succeeded','failed','refused' only if you record refusals; pick and justify). Index (user_id, created_at). No raw prompt text column.
- review_items (user-owned, state machine): the spec's ReviewItem fields (source CHECK per the frozen spec, proposal_type CHECK per the frozen spec, proposed_payload typed JSONB, confidence, rationale, evidence_ref_id, status CHECK ('pending','confirmed','rejected','expired'), decided_at), plus provenance and concurrency per spec 4.1: llm_run_id nullable (composite FK to llm_runs), state_version, decided_payload typed JSONB nullable (what was actually applied after Edit + Confirm), decision_note nullable, created_at, updated_at. evidence_ref_id points at tables that do not exist yet (ExternalRef, Message): plain uuid, no FK, always re-resolved through a user-scoped repository before use (INV-18).
- Grants to career_os_app: llm_runs SELECT, INSERT, UPDATE (settlement); review_items SELECT, INSERT, UPDATE. No DELETE on either (removed only by account-deletion cascade). Tests prove it.
- If the frozen spec's enum lists differ from what you expect, use the spec's lists exactly.

B. Gateway (app/llm/)
- ModelGateway is the only entry point for model work. Methods: structured(...) returns a validated Pydantic object; stream(...) yields text deltas and ends with a completed run. Both require: user_id, purpose, prompt id (resolved via the registry), tier, input variables, context_manifest (typed list of {entity_type, entity_id, version}; may be empty), max_output_tokens.
- Provider boundary: a ModelProvider protocol with AnthropicProvider and FakeProvider. Only app/llm/providers/anthropic.py may import the anthropic SDK (add it via uv). A test fails if any other module imports it.
- Tiers by configuration: LLM_MODEL_FAST and LLM_MODEL_REASONING map tiers to model ids. Prices by configuration: LLM_MODEL_PRICES (JSON: model id → input and output USD per million tokens), labeled as assumptions until verified. No model ids or prices hard-coded in Python. LLM_PROVIDER defaults to fake, so nothing calls a real API unless I configure it. For the Anthropic provider, look up current model ids and prices from https://docs.claude.com and put them only in .env.example as placeholders with a comment-free note in the docs; never in code.
- Settings: LLM_PROVIDER (fake|anthropic), ANTHROPIC_API_KEY (SecretStr, optional, passed to api and worker only), LLM_MODEL_FAST, LLM_MODEL_REASONING, LLM_MODEL_PRICES, LLM_REQUEST_TIMEOUT_SECONDS, LLM_DEFAULT_MAX_OUTPUT_TOKENS, plus the existing LLM_DAILY_COST_CAP_USD. Startup fails clearly if LLM_PROVIDER=anthropic and the key or a tier's price is missing.
- Structured output: ask the provider for JSON matching the prompt's Pydantic schema (use the provider's structured/tool mechanism where available). Validate. On failure, make exactly one repair call that includes the validation errors (a new llm_runs row with attempt=2 and repair_of_run_id). If that fails too, raise a typed llm_output_invalid error. Never return unvalidated output.
- Streaming: reserve before the call; on completion settle from provider usage; if the stream errors or is cancelled without usage, settle at the reserved amount (conservative). The fake provider streams deterministic chunks.
- Untrusted content (T3): a helper that wraps untrusted text (JDs, emails, resumes later) in clearly delimited blocks, and prompts state that delimited content is data, not instructions. Test the wrapper escapes or neutralizes an embedded closing delimiter.
- INV-07 and INV-11: the gateway returns data only; it never writes domain tables. app/llm must not import app.auth.tokens, session or credential modules, or any repository other than its own llm_runs repository; add an import-boundary test.
- INV-17: no model call happens outside an explicit purpose; there is no scheduler or job in this task that calls the model.

C. Prompt registry
- Prompts are code: app/llm/prompts/ with entries (prompt_id, version, purpose, tier, system template, user template, output schema or None for streaming). The registry rejects duplicate (id, version) and unknown ids. Changing a prompt's text means a new version (a test fails if a registered version's content hash changes without a version bump: keep a small committed lock file of id, version and hash).
- This task ships only generic test prompts needed to exercise the gateway (no real extraction prompts; those come with Tasks 6 and 9).

D. Daily cost cap (spec 13.1)
- Budget day is the UTC calendar day. Spent today = sum over the user's llm_runs created today of coalesce(cost_usd, reserved_cost_usd) for every status that consumed or holds budget.
- Reservation: in one short transaction, take a per-user transaction-scoped advisory lock (pg_advisory_xact_lock on a stable 64-bit hash of the user id), compute spent, compute worst case = conservative input-token estimate (document the heuristic) plus max_output_tokens at the model's configured prices, refuse if spent + worst case > cap, otherwise insert the llm_runs row as reserved and commit. The provider call happens outside that transaction. Settlement updates cost_usd, tokens, latency, status and settled_at in a second transaction.
- Refusal: typed llm_budget_exhausted error; the provider is never called. API maps it to 429 with code llm_budget_exhausted. Decide whether refused attempts are recorded as rows and justify.
- A crashed call leaves a reserved row that keeps counting at its reserved cost (conservative); document this.
- Concurrency test: two simultaneous reservations whose combined worst case exceeds the remaining budget must result in exactly one success and one refusal (use real Postgres and threads).
- Budget endpoint: GET /api/v1/llm/budget → spent_usd, cap_usd, remaining_usd, resets_at (next 00:00 UTC). Money as strings or decimals, never floats.

E. Review framework (app/review/)
- A ReviewHandlerRegistry maps proposal_type → handler {payload model, confirm(ctx, payload)}. confirm runs the SAME domain command a manual action would run (INV-14); the framework never writes domain state itself.
- Commands: Confirm (apply proposed_payload), Edit + Confirm (validate the user's edited payload with the same model, then apply it; store it in decided_payload), Reject / Ignore (status rejected, optional decision_note). Each is one transaction: optimistic state_version check (client sends expected state_version; stale → 409 conflict), handler command, status change, decided_at. Confirm or edit on a non-pending item → 409 invalid_transition. A proposal_type with no registered handler cannot be confirmed (422 no_handler) but can be rejected.
- A pure transition function for pending → confirmed / rejected / expired with exhaustive tests. Expiry automation is not built in this task (no producer needs it yet); the state exists.
- A ReviewItemRepository.create(...) used by future producers; it validates the payload against the registered model when one exists.
- Tests use a test-only registry with a synthetic proposal type and a recording handler; prove rollback when the handler raises (item stays pending, nothing applied).

F. API (prefix /api/v1; typed errors; foreign ids → 404; every route gets an isolation case)
- GET /api/v1/llm/budget
- GET /api/v1/review-items?status=pending (caller's only, newest first), GET /api/v1/review-items/{id}
- POST /api/v1/review-items/{id}/confirm {expected_state_version}
- POST /api/v1/review-items/{id}/edit-confirm {expected_state_version, payload}
- POST /api/v1/review-items/{id}/reject {expected_state_version, note?}
- No public endpoint calls the model in this task (no producer exists). The gateway is exercised by tests and the optional live check only.
- Isolation harness: add a case for every new route.

G. Frontend (minimal; design is Task 10)
- Settings page: AI budget indicator "spent of cap today, resets 00:00 UTC", using the budget endpoint, with a plain message when exhausted.
- Review page (nav link): pending items with source, proposal type, rationale and confidence; payload shown as plain text (never HTML, T5); Confirm, Edit + Confirm (a JSON textarea is acceptable until producers bring typed editors) and Reject with an optional note; a stale-version conflict shows a plain message and refreshes.
- Regenerate backend/openapi.json and src/api/schema.d.ts. Vitest tests for the budget indicator, review actions and the conflict message.

H. Config, Compose, CI, docs
- .env.example placeholders (LLM_PROVIDER=fake by default; Anthropic values as placeholders). Compose passes LLM settings and ANTHROPIC_API_KEY to api and worker only. CI uses the fake provider and needs no secrets; a test asserts no test touches the network.
- docs/architecture/llm.md: gateway and provider boundary, tiers and prices, structured output and repair, streaming, budget reserve and settle with the lock and the race test, refusal behavior, prompt registry and versioning, manifests, untrusted-content delimiting, logging rules, what is deferred.
- docs/architecture/review.md: review item lifecycle, command framework, optimistic concurrency, how a future producer registers a handler.
- Update README (configuration rows and a short section) and docs/architecture/database.md (new tables, grants).

ACCEPTANCE CHECKS YOU MUST RUN
1. Backend: ruff check, ruff format --check, mypy, full pytest with Postgres and REQUIRE_DB_TESTS=1 (all earlier tests still pass).
2. Migrations on an empty DB: upgrade head → alembic check → downgrade base → upgrade head.
3. Frontend: lint, typecheck, test, build; generated OpenAPI types up to date.
4. Stack: docker compose up --build -d; migrate exits 0; /healthz 200 on 127.0.0.1. With a synthetic user and session created as owner (deleted afterwards): GET /api/v1/llm/budget shows 0 spent of the cap; then, using a small script that calls the gateway with the FAKE provider against the running database for that synthetic user, show an llm_runs row reserved then settled, the budget endpoint reflecting the spend, a refusal once a tiny test cap is exceeded (set via a test override, not by changing my .env), and a synthetic review item confirmed and rejected through the API with a test handler registered by the script or a test-only path that is not reachable in production.
5. OPTIONAL live call (ask me first; only if I provide an ANTHROPIC_API_KEY in .env): one tiny structured call through the gateway with a synthetic prompt and max_output_tokens ≤ 200, showing the llm_runs row with real token counts and a cost under $0.01. If I decline or have no key, record it as not run.
6. Push the branch (ask me first) and confirm GitHub Actions is green for backend, frontend and secrets.

ESCALATION
If you find a spec contradiction, a required architecture change, a required scope change, a security issue affecting the frozen design, a schema requirement beyond llm_runs and review_items and the authorized extra columns above, or a missing prerequisite that changes architecture: STOP that part and report:
PROBLEM / EVIDENCE / WHY THE CURRENT SPEC CANNOT BE FOLLOWED / SMALLEST OPTIONS / RECOMMENDATION / WHAT IS BLOCKED
Continue only with work that does not depend on the outcome. Do not silently redesign.

GIT AND FINISH
- Commit in logical steps on task-05-model-gateway with clear messages and no attribution trailers.
- Push (ask first). gh is not authenticated; give me the compare URL. Do NOT merge.
- Write docs/checkpoints/task-05.md in this format, commit and push it (ask first):
  What was implemented (mapped to each acceptance criterion) / Evidence / Changes outside the expected file set (file, change, reason) or none / Important things I learned (4 to 8 bullets, specific) / Checks run and results (table) / Deviations from the frozen spec or none / Unresolved issues / Git state (branch, commits, PR URL, CI status) / Recommendation: approve or not, with reason
- Then STOP. Do not start Task 6.

Begin with Step 0.
