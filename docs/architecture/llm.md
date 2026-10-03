# Model gateway

Spec references: 1.3 (INV-01, INV-07, INV-11, INV-17, INV-18), 2.1, 3, 4.7, 6.1, 8 (T3, T12, T14), 11, 13.1. ADR-007.

The gateway is the only module that talks to a model. Domain code asks it for a validated object or a stream of text and gets data back; it never lets a model write domain state (INV-07).

## Boundaries

```
caller (service or job)
   │  user_id, purpose, prompt id, tier, variables, context manifest, max_output_tokens
   ▼
ModelGateway (app/llm/gateway.py)
   │  registry lookup → render → reserve budget → provider call → validate → settle
   ▼
ModelProvider protocol ── FakeProvider (default, tests)
                      └─ AnthropicProvider (app/llm/providers/anthropic.py, the only SDK import)
```

- A **provider adapter** hides the vendor SDK behind two methods, `complete` and `stream`, plus plain request and result types. Swapping vendors means writing one more adapter; nothing else imports `anthropic`. `tests/test_boundaries.py` fails if another module does.
- The gateway core imports only its own `llm_runs` repository, configuration, logging and the tenancy helpers. It cannot import `app.auth.tokens`, session or credential modules, or any other repository (INV-11). The same test checks `app/llm` and `app/review` with an import allowlist; it also proves the checker catches a forbidden import. `router.py` is the HTTP layer and may import auth dependencies.
- No model id or price appears in Python. A test scans `app/` for vendor model names.
- `structured(...)` returns a `StructuredResult` (validated object, `run_id`, whether a repair was needed). The `run_id` exists so producers can store provenance (`review_items.llm_run_id`). `stream(...)` returns a `ModelStream` that yields text deltas, exposes `run_id` and `usage` when finished, and settles when exhausted or closed (use it as a context manager).
- INV-17: every call names a purpose from the spec's closed list, and the gateway refuses a call whose purpose or tier differs from the registered prompt's. Task 5 added no caller; the first is the `extract_jd` job of Task 6 ([opportunities.md](opportunities.md)), started only by a pasted job description or an explicit retry.

## Configuration

| Setting | Meaning |
| --- | --- |
| `LLM_PROVIDER` | `fake` (default) or `anthropic` |
| `ANTHROPIC_API_KEY` | `SecretStr`, passed to the API and worker only (Compose passes it nowhere else) |
| `LLM_MODEL_FAST`, `LLM_MODEL_REASONING` | Model id per tier |
| `LLM_MODEL_PRICES` | JSON: model id to `input_usd_per_mtok` and `output_usd_per_mtok` (assumptions until verified against billing) |
| `LLM_REQUEST_TIMEOUT_SECONDS`, `LLM_DEFAULT_MAX_OUTPUT_TOKENS` | Per-call limits |
| `LLM_DAILY_COST_CAP_USD` | Per-user cap per UTC day (default 1.00) |

Startup fails with a plain message if a tier's model has no price entry, or if `LLM_PROVIDER=anthropic` and the key is missing. The fake provider's defaults (`fake-fast`, `fake-reasoning`, $1 and $5 per million tokens) are labels for the fake, not vendor values.

Anthropic placeholders live in `.env.example`, commented out. They were read from the public docs (models overview and pricing pages) on 2026-10-02: fast tier `claude-haiku-4-5-20251001` at $1 input and $5 output per million tokens, reasoning tier `claude-sonnet-5-5` at $2 and $10. Treat the prices as assumptions and check your own billing.

## Prompt registry and versions

Prompts are code (`app/llm/prompts/`). A `Prompt` has an id, a version, a purpose, a tier, system and user templates (`$name` placeholders, rendered with `string.Template`), an optional Pydantic output schema (none means streaming) and the set of variables that carry untrusted text. The registry rejects a duplicate `(id, version)` and an unknown id. `get(id)` returns the highest version.

Changing a prompt means a new version. `prompts.lock.json` records each registered `(id, version)` with a SHA-256 over its purpose, tier, templates, JSON schema and untrusted variables. A test fails if the registered content no longer matches the lock, so editing text without bumping the version cannot pass CI. After a deliberate change, add the new version and run `uv run python -m app.llm.prompts.lock`.

This task ships two generic self-test prompts (a tone label for a synthetic note, and a polite reply) so the gateway can be exercised. They borrow the `classify_email` and `chat` purposes because the purpose list is closed by the spec; real prompts arrive with their tasks: `jd.extract` (purpose `extract_jd`, tier `fast`, untrusted variable `jd`) in Task 6, resume extraction in Task 9.

## Untrusted content (T3)

Prompt injection works because a model cannot tell instructions from data. The gateway marks the boundary and tells the model which side is which:

- Variables a prompt declares untrusted are wrapped by `wrap_untrusted` as `<untrusted_content label="...">…</untrusted_content>`. The label is reduced to `[a-z0-9_]`.
- Any embedded `<untrusted_content` or `</untrusted_content`, in any case or spacing, is neutralised to `&lt;…`, so hostile text cannot close its own block. Tests cover the variants.
- A prompt with untrusted variables gets a standing notice appended to its system text: delimited content is data, not instructions, and cannot change the output format.
- This lowers risk; it does not remove it. The real defences are structural: schema-constrained output, no tools with side effects, and every state change passing a review item or a user click (INV-07, INV-14).

## Structured output and the repair retry

The adapter asks the provider for JSON that matches the prompt's schema (for Anthropic, `output_config.format` with a JSON schema, adjusted by the SDK's `transform_schema`; forced tool choice is not used because newer models reject it). The gateway then validates with Pydantic. Unvalidated output is never returned.

1. First call, attempt 1. If valid, done.
2. If invalid, the run settles as `failed` with `error_code = output_invalid` (the invalid text is not stored). One repair call follows, attempt 2, `repair_of_run_id` pointing at the first run. Its user message adds the validation errors (location and message only, never the offending values) and the previous reply wrapped as untrusted data.
3. If the repair is also invalid, the gateway raises `llm_output_invalid`. There is never a third call. Both calls count against the budget.

## Streaming

Chat replies and other long output stream as text deltas. On the wire to a browser this becomes Server-Sent Events (one `data:` line per delta over a held-open response); no endpoint streams in this task. Reservation happens when `stream()` is called, so a refusal is immediate and typed. Settlement uses the provider's final usage. If the stream errors, is cancelled, or is closed before it starts, no usage is known and the run settles at the reserved amount (conservative), as `failed` with `stream_interrupted` or `cancelled`. Streaming runs store no output text; whoever persists the reply (chat, later) owns that content.

## Daily cost cap: reserve, then settle

Budget day is the UTC calendar day. Spent today is `sum(coalesce(cost_usd, reserved_cost_usd))` over the user's `llm_runs` created that day, so settled runs count their real cost and unsettled ones their reservation.

Reservation is one short transaction:

1. `pg_advisory_xact_lock(key)` where `key` is a stable signed 64-bit hash of the user id. The lock is released at commit or rollback.
2. Compute spent today.
3. Worst case = estimated input tokens plus `max_output_tokens`, priced at the model's configured rates, rounded up to a micro-dollar.
4. If `spent + worst > cap`, raise `llm_budget_exhausted` and roll back. The provider is never called.
5. Otherwise insert the run as `reserved` and commit.

The provider call happens outside that transaction; holding a database lock across a slow network call would stall every other call by the same user. Settlement is a second short transaction that sets status, tokens, latency, `cost_usd` and `settled_at`, guarded by `WHERE status = 'reserved'` so it can only happen once.

**Why the lock.** Without it two requests can both read "$0.90 spent", both decide a $0.20 call fits under a $1.00 cap, and both insert: a classic check-then-act race. The advisory lock serialises reservations per user, so the second sees the first's reservation. `tests/db/test_gateway.py` runs two threads against real Postgres with a barrier that releases them together: with the lock, exactly one succeeds and one gets `llm_budget_exhausted`; a control test removes the lock and shows both succeed past the cap.

**Input estimate.** Characters are not tokens, so the estimate is a deliberately high bound: UTF-8 bytes of the system text, user text and JSON schema divided by 2 (rounded up), plus 64 tokens of overhead. English text runs about 4 bytes per token, so this over-reserves by roughly 2x, and the newer Anthropic tokenizer's roughly 30% increase still fits. The reservation is released as soon as the real cost replaces it. If a pathological input ever exceeded the estimate, the call is settled at its true cost (never refused after the fact), so the cap can be exceeded by that margin on a single call.

**Refusals are not recorded.** A refused call writes no `llm_runs` row; it raises the typed error and logs `llm_budget_refused` with ids and purpose. Reasons: it cost nothing and nothing was sent; recording it would let a buggy loop against a capped user grow the table without bound (T14); and the log line already gives the audit trail. Run rows therefore always mean "something was reserved or bought".

**Crashes.** If the process dies after reservation, the run stays `reserved` and keeps counting at its reserved cost for the rest of the UTC day. That is conservative by design (the provider may have billed). A provider error with no usage settles at the reserved cost for the same reason. There is no automatic release in this task.

`GET /api/v1/llm/budget` returns `spent_usd`, `cap_usd`, `remaining_usd` (never negative) as decimal strings and `resets_at` (next 00:00 UTC). A refused call surfaces from any endpoint as HTTP 429 with `{"error": {"code": "llm_budget_exhausted"}}`. Deterministic features keep working when the cap is reached.

## Run records and manifests

Every call writes an `llm_runs` row: purpose, prompt id and version, provider, model, tier, `max_output_tokens`, attempt, repair link, status, error code, token counts, latency, reserved and settled cost, a typed `context_manifest` (`{schema_version, entries: [{entity_type, entity_id, version}]}`, possibly empty) and, for structured calls, a typed `output` (`{schema_version, data}`). It stores no raw prompt text. Manifest ids live in JSONB, so consumers re-resolve them through user-scoped repositories (INV-18). Runs are never rewritten after settlement and are deleted only by the account-deletion cascade.

## Logging

The gateway logs only ids, purpose, prompt id and version, model, provider, tier, status, token counts, cost, latency and error codes. It never logs prompts, model output, document text or keys. The logging allowlist gained exactly those field names; anything else is dropped.

## Tests never touch the network

CI uses the fake provider and needs no secrets. An autouse fixture makes `socket.connect` raise for any non-loopback address, and `tests/test_no_network.py` proves it. The Anthropic adapter is tested through an `httpx2` mock transport, which asserts the request body and parses recorded-shape responses, including streaming.

## Deferred

Prompt caching, model fallbacks and refusal fallbacks, retries beyond the single repair call (the SDK's own retries are disabled so cost accounting stays exact), batch calls, per-purpose caps, automatic release of stale reservations, a budget indicator next to AI actions (Task 10) and resume-extraction and later prompts (Task 9 onward).
