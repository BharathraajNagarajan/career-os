# Opportunities: JD ingestion, extraction, companies, duplicates, editing

Spec references: 0A, 1.3 (INV-01, INV-02, INV-07, INV-17, INV-18), 2.1, 2.2, 4.1, 4.4, 5.2, 6.2c, 8 (T1, T3, T5, T14, T17), 9, 11, 14 (Task 6). Tables: `companies`, `opportunities`, `qualifications` (migration 0005; see [database.md](database.md)).

A job description (JD) is pasted by the user, stored as an immutable artifact, and turned into an Opportunity with a company, fields and verbatim qualifications by one model call. Everything the model produced is user-editable.

## Ingest pipeline

`POST /api/v1/opportunities/ingest` (authenticated, CSRF) with `jd_text` and an optional `source_url`.

1. Normalize the text: CRLF and CR become LF, NUL characters are removed, the ends are trimmed. Then check the length against `JD_MIN_CHARS` (default 200, `jd_too_short`) and `JD_MAX_CHARS` (default 50,000, `jd_too_long`). The request model also has an absolute ceiling so a huge body is refused before any work.
2. Hash the normalized UTF-8 bytes with SHA-256. If this user already has a `jd_snapshot` artifact with that hash that belongs to an opportunity, respond `409 duplicate_jd` with the existing `opportunity_id`. Hashes are per user, so another user pasting the same text is unaffected.
3. Write the bytes through the storage adapter, then in **one transaction** insert the `jd_snapshot` artifact (text stored in `extracted_text`, `extraction_status = succeeded`), the opportunity (`status = new`, `extraction_status = pending`), the `OPPORTUNITY_INGESTED` event and the `extract_jd` job (`user_id` = owner, payload `{opportunity_id}`, `unique_key = extract_jd:<id>`). If anything fails the transaction rolls back and the stored object is removed. A unique-constraint race on the hash re-checks and answers `duplicate_jd`.
4. Respond `202` with the opportunity summary.

`source_url` must be http or https, at most 2,048 characters, with no whitespace or control characters. It is stored and shown as text. **Nothing fetches it** (spec T17): there is no URL-fetching code in the application, so there is no SSRF surface to defend yet. The frontend shows it as plain text, not a link, so a hostile string cannot be clicked into a `javascript:` navigation.

`discovered_at` and `content_updated_at` come from the database clock (`now()`), not from Python. The database and the API can run on machines whose clocks differ (a Docker VM on a laptop drifts by about a second), and staleness (6.2c) compares `content_updated_at` with Evaluation `created_at`, which is also a database timestamp.

INV-17: pasting is the explicit user action that authorizes the one model call. No other path calls the model in this task except the explicit retry below.

## Extraction (worker job `extract_jd`)

The job re-resolves the opportunity and its artifact through user-scoped repositories (INV-18); a missing or foreign id is logged and ignored. It runs only when `extraction_status` is `pending`, so a duplicate job, a retried job or a job for something already extracted does nothing.

The handler ends its read transaction, then calls `ModelGateway.structured` with prompt `jd.extract` (purpose `extract_jd`, tier `fast`, max output tokens `JD_EXTRACTION_MAX_OUTPUT_TOKENS`, manifest entry for the JD artifact). The gateway reserves the budget, calls the provider, validates the output with Pydantic, and makes one repair call at most (see [llm.md](llm.md)). Every call is an `llm_runs` row; no JD text or model output is logged anywhere.

### The prompt and its untrusted delimiting (T3)

`app/llm/prompts/jd_extract.py` holds the prompt, registered in the catalog and pinned in `prompts.lock.json`. Its text is generic: it names no person, company or career data (INV-01), and a test checks that. The JD is the single untrusted variable, so the gateway wraps it in `<untrusted_content label="jd">…</untrusted_content>`, neutralizes any delimiter the text contains (so a posting cannot close its own block), and appends the standing notice that delimited content is data, not instructions. The system text also says to ignore instructions inside the posting. A test pastes a JD containing "ignore all previous instructions" and a forged closing tag and asserts that exactly one real closing tag reaches the provider.

Delimiting lowers risk but does not stop injection. The real controls are structural: the output is a closed schema, the model has no tools, it cannot change a status, priority or application, and everything it returns is checked by deterministic code before anything is written.

### The INV-07 exception and its safeguards

INV-07 says the model never writes domain state directly, and names this exception: JD extraction may populate Opportunity, Qualification and Company fields as `extracted` origin, because those fields describe the posting, not the user, and each is user-editable. No review item is created. The safeguards:

- **Extracted origin and provenance.** Extracted companies have `origin = extracted`; extracted qualifications have `origin = extracted` and `llm_run_id`; the opportunity stores `llm_run_id`. The user can always see which values came from the model.
- **Verbatim grounding.** A qualification is kept only if its `text_verbatim`, after collapsing whitespace, is a substring of the JD (also whitespace-collapsed). Anything else is dropped (the model invented or paraphrased it), repeated lines are kept once, and only the dropped **count** is logged and recorded in the event. The stored text is the grounded, whitespace-collapsed span. `text_verbatim` is then immutable by database privilege (see below).
- **Deterministic cleaning.** Skill keys are trimmed, lowercased, de-duplicated, capped at 40 characters and 10 keys. `min_years` is rounded and clamped to 0..50. A company domain must be a valid hostname after normalization. Country codes must be ISO 3166-1 alpha-2 (a built-in list). Invalid values are discarded, not turned into a failure of the whole extraction.
- **Fill-empty-only.** Extraction sets a field only if it is still empty: company only when `company_id` is null, title, team, job ID and location text only when null, places only when there are none, workplace type only when `unspecified`. Qualifications are inserted only if the opportunity has none. A value the user typed while extraction was running is never overwritten. The opportunity row is locked with `SELECT … FOR UPDATE` before applying, and the apply is skipped if the status is no longer `pending`.
- **No automatic retries.** `llm_budget_exhausted`, `llm_output_invalid` and `llm_provider_error` mark `extraction_status = failed` with that code, and the job finishes as succeeded: it is not re-queued, because a retry would be hidden model work (INV-17, T14). Only infrastructure errors (database, storage) propagate and use the job queue's retries; the handler's idempotence check keeps those safe.
- **Explicit re-run.** `POST /api/v1/opportunities/{id}/extract` re-queues the job only when the status is `failed` (otherwise `409 invalid_state`), clears the error and sets `pending`. It is a user click, so it is allowed to spend the budget.
- A job id that would violate the partial unique index is left empty, so the new posting simply appears as a duplicate (below).

The apply is one transaction: company resolution or creation, filled fields, qualifications, `extraction_status = succeeded`, `llm_run_id`, `content_updated_at` bump, `OPPORTUNITY_EXTRACTED`.

## Company normalization and resolution

`normalized_name`: Unicode NFKC, lowercase, every punctuation and symbol character removed, whitespace collapsed, then trailing legal-suffix words removed while more than one word remains. The list (whole words, end only): `inc`, `llc`, `ltd`, `limited`, `corp`, `corporation`, `co`, `gmbh`, `plc`, `sa`, `ag`, `bv`, `pvt`, `private`. So "Example, Inc." and "EXAMPLE Corporation" normalize to `example`, "AT&T Inc" to `att`, "Private Example" stays `private example`, and a company literally named "Corp" stays `corp`. A name that normalizes to nothing is rejected (422 `invalid_name`) or, in extraction, leaves the company empty.

Domains: lowercased, scheme, userinfo-free host only, path, query, port and a leading `www.` removed, IDNA-encoded, and validated (labels of letters, digits and hyphens, alphabetic top-level domain). Anything else is invalid.

Resolution order for an extracted company (always within the user's own rows):

1. an existing company whose `domains` contain the extracted domain;
2. one whose `normalized_name` equals the normalized extracted name;
3. one whose aliases, normalized the same way, contain it;
4. otherwise create a company (`origin = extracted`) and record `COMPANY_CREATED`.

A concurrent creation of the same name is caught by the `(user_id, normalized_name)` unique constraint inside a savepoint and resolves to the winner. Each path, and the refusal to match another user's company by domain, name or alias, is tested. Company **merge is deferred** (spec 4.4); until then a wrong match is fixed by editing the opportunity's company.

Index decision: no GIN index on `aliases` or `domains`. A GIN array index cannot be combined with `user_id` without the `btree_gin` extension, and each user has at most a few hundred companies, so the planner reads that user's rows through the unique `(user_id, normalized_name)` btree and filters. Add one when a measurement says so.

## Duplicate detection

`GET /api/v1/opportunities/{id}/duplicates` is computed on read, deterministically, with no model. Candidates are the caller's other opportunities with the same non-null company (at most 200). A candidate is a duplicate when:

- `exact_job_id`: both have the same non-empty `external_job_id` (the partial unique index normally prevents this, so it is a safety net); or
- `similar_title`: both have titles and the `difflib` ratio of their normalized titles (lowercase, no punctuation, collapsed spaces) is at least 0.9, and the normalized location texts are equal or either is empty.

Results are ordered exact first, then by similarity. Two pastes of the same posting text are already blocked at ingest by the artifact hash. The partial unique index `(user_id, company_id, external_job_id) WHERE external_job_id IS NOT NULL AND company_id IS NOT NULL` makes a second posting with the same job id at the same company impossible, which is why extraction leaves the job id empty on the newcomer instead of failing; the title and company rule then surfaces it.

## Editing and `content_updated_at`

`PATCH /api/v1/opportunities/{id}` takes `expected_state_version` and any of `title`, `team`, `external_job_id`, `location_text`, `locations`, `workplace_type`, `company_id`, `source_url` (only the fields sent are applied; `null` clears the optional ones). `locations` is typed JSONB `{schema_version: 1, items: [{city, region, country}]}` validated by a Pydantic model (country must be ISO alpha-2).

- The row is locked and the version compared; a stale version is `409 conflict`. A violation of the job-id index is `409 duplicate_job_id`. A `company_id` that is not the caller's is `404`.
- A request that changes nothing changes nothing: no version bump, no timestamp, no event.
- A real change updates the fields, bumps `content_updated_at` and `state_version`, and writes `OPPORTUNITY_CONTENT_EDITED` with the **names** of the changed fields.
- `PATCH …/priority` changes `priority` only. It does **not** move `content_updated_at` (priority is the user's judgment, not part of the posting that an Evaluation relied on), and writes `OPPORTUNITY_PRIORITY_CHANGED`. Any row update bumps `state_version`, so the next field edit must use the latest version; the UI re-reads after every change.
- Qualifications: `POST …/qualifications` (origin `user`), `PATCH /qualifications/{id}` (`kind`, `category`, `skill_keys`, `min_years`, `is_hard_constraint`, `ordinal`; sending `text_verbatim` is a 422) and `DELETE`. Each change bumps the parent opportunity's `content_updated_at` and writes `OPPORTUNITY_CONTENT_EDITED` with `fields: ["qualifications"]`. `text_verbatim` cannot be changed even by a buggy query: the app role has no `UPDATE` privilege on that column.

`content_updated_at` is one of the staleness inputs of 6.2c: an Evaluation (Task 11) is stale if it is older than the opportunity's `content_updated_at`. This task only maintains the timestamp; there is no Evaluation yet, and `latest_evaluation_id` is a plain uuid until Task 11 adds the table and its foreign key.

Companies: `GET/POST /companies`, `GET /companies/{id}` (opportunity counts by status), `PATCH /companies/{id}` (`name` recomputes `normalized_name`; a clash is `409 company_name_taken`; aliases, domains, careers URL, notes; `strategic_priority` writes `COMPANY_PRIORITY_CHANGED`).

## Events

Written in the same transaction as the change; payloads carry ids, field names and enum values, never text, and are registered with `schema_version`:

| Event | When | Actor |
| --- | --- | --- |
| `OPPORTUNITY_INGESTED` | ingest | user |
| `OPPORTUNITY_EXTRACTED` | extraction applied (filled field names, counts) | system |
| `OPPORTUNITY_CONTENT_EDITED` | field or qualification edit (changed field names) | user |
| `OPPORTUNITY_PRIORITY_CHANGED` | priority change (from, to) | user |
| `COMPANY_CREATED` | user or extraction creates a company | user or system |
| `COMPANY_PRIORITY_CHANGED` | strategic priority change | user |

## Failure modes and logs

| Situation | Result |
| --- | --- |
| Budget exhausted | `failed`, code `llm_budget_exhausted`, no provider call, no automatic retry; the UI says the budget resets at midnight UTC and offers Retry |
| Output invalid after the repair call | `failed`, code `llm_output_invalid`, two `llm_runs` rows, no third call |
| Provider error | `failed`, code `llm_provider_error` |
| Database or storage error | job queue retry with backoff; extraction stays `pending` |

Logs hold ids, counts, statuses and error codes only (`opportunity_id`, `run_id`, `count`, `dropped_count`, `error_code`). A test pastes a marker string and asserts it, the title and the company name never reach the log output.

## Not in this task

Company merge; any URL fetching (T17); Save, Skip, Apply and Close and the Application they create (Task 7); evaluation, staleness display and `latest_evaluation_id`'s foreign key (Task 11); polished design (Task 10). Only the initial `new` status is ever written.
