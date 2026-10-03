You are my hands-on implementation and debugging partner for Career OS, working in C:\Users\bhara\career-os on Windows with Docker Desktop (WSL2). GNU Make is not installed; use docker compose, uv and npm directly. Everything you need is in this brief, the repository, and docs/.

STEP 0: PRE-FLIGHT
1. Confirm you are running on a Sonnet model. If not, tell me before doing anything else.
2. git switch main && git pull. Confirm main contains the merged Task 5 work (docs/checkpoints/task-05.md, backend/app/llm/, backend/app/review/) and the working tree is clean.
3. Confirm python resolves to backend\.venv, Docker is running (docker info), and node -v is v22.x.
4. Create branch task-06-jd-ingestion from main.
5. FIRST save this entire brief verbatim to docs/briefs/task-06.md and commit it ("docs: Task 6 brief"). Long shell heredocs break on this host: write files with your editor tool, not cat <<EOF.

AUTHORIZED SCOPE
Only Phase 1A Task 6: JD ingestion and priorities. The only new tables are companies, opportunities and qualifications. Do NOT start Task 7 (opportunity state transitions Save/Skip/Apply/Close, applications) or Task 11 (evaluation). Company merge is NOT in this task (record it as deferred). No URL fetching of any kind (spec T17): a source URL is stored and displayed only.

SOURCE OF TRUTH (read before coding)
- docs/spec/phase-0-spec.md (FROZEN): 0A, 1.3 (invariants, especially INV-01, INV-02, INV-07, INV-17, INV-18), 2.1, 2.2, 4.1 (provenance columns, state versions, JSONB rules), 4.4 (Company, Opportunity, Qualification rows; use the latest field lists in the frozen file), 5.2 (Opportunity states; only the initial New state is created in this task), 6.2c (content_updated_at as a staleness input), 8 (T1, T3, T5, T14, T17), 9 (Companies and Opportunities rows, boundary rules), 11, 14 (Task 6 acceptance criteria)
- docs/architecture/llm.md, review.md, artifacts.md, database.md; docs/checkpoints/task-05.md
- backend/app/ (gateway, prompt registry and lock, untrusted wrapper, storage adapter, artifacts, tenancy, versioning, events, jobs, isolation harness)
The spec wins over this brief. If they disagree, stop and escalate.

WORKING RULES
- You own local operations for this task only: terminal, Docker/Compose, Git, dependencies, tests, debugging, code edits.
- Never install anything system-wide without asking. Project dependencies via uv add / npm install are fine.
- Approve-each-time: git push, docker compose down -v, deleting files outside build caches, and ANY real (paid) model API call.
- NEVER add Co-Authored-By, "Generated with Claude" or any Claude attribution to commits or PR text. I am the sole contributor.
- Learning mode: briefly explain meaningful concepts as you work (INV-07's extraction exception, verbatim grounding checks, entity resolution and normalization, partial unique indexes, fuzzy duplicate detection, optimistic concurrency on edits, staleness timestamps, prompt injection in pasted content, job retries vs explicit re-runs). Skip trivial commands.
- Debugging rule: observe → identify failing layer → hypothesis → inspect evidence → smallest justified change → rerun failing check → rerun related checks. Say explicitly when a problem is environmental.
- Use 127.0.0.1 for local DB URLs and curl; browser checks use http://localhost:5173.
- .env has a BOM and JSON values: never source it in a shell; read single values.
- No code comments; minimal readable code; don't restructure working Task 1-5 code unless required.
- INV-01: prompts, fixtures and test data are generic and synthetic (synthetic companies such as "Example Corp", synthetic JDs). No real people, companies or career data; the prompt contains no creator-specific content.
- Never log JD text, prompts or model output. Log ids, counts, statuses and error codes only.
- Commit after every logical step.

TASK 6 ACCEPTANCE CRITERIA (spec section 14)
Paste JD text with optional source URL; immutable JD artifact; extraction of company, title, team, job ID, location, workplace type and verbatim qualifications with categories and skill keys, applied as `extracted` origin; company resolution by normalized name, alias or domain; duplicate detection; opportunity priority and company strategic priority; every field user-editable and edits bump `content_updated_at`; no creator data in prompts (reviewed).

IMPLEMENTATION DECISIONS ALREADY MADE BY THE PLANNING CHAT (they translate the spec, they do not change it)

A. Tables (migration 0005, hand-reviewed, grants, working downgrade)
- companies (user-owned): the spec's fields (name, normalized_name, aliases text[], domains text[], careers_url, strategic_priority CHECK ('high','normal','low') default 'normal', notes) plus origin CHECK ('user','extracted'), created_at, updated_at. UNIQUE (user_id, normalized_name). GIN or btree support for alias/domain lookup as you judge (justify).
- opportunities (user-owned, state machine): the spec's fields. company_id nullable until resolved (composite FK to companies). title nullable until extracted or entered. status CHECK ('new','saved','skipped','applied','closed') default 'new' (only 'new' is created in this task). priority CHECK ('high','normal','low') default 'normal'. extraction_status CHECK ('pending','succeeded','failed') plus extraction_error_code nullable. workplace_type CHECK ('onsite','hybrid','remote','unspecified') default 'unspecified'. locations typed JSONB ({schema_version, items: [{city, region, country (ISO alpha-2 or null)}]}). source CHECK ('manual_paste'). source_url nullable. jd_artifact_id composite FK to artifacts. llm_run_id nullable (composite FK to llm_runs) for provenance. latest_evaluation_id nullable plain uuid with NO FK yet (the table arrives in Task 11; add the FK then). content_updated_at, discovered_at, created_at, updated_at, state_version. Partial UNIQUE (user_id, company_id, external_job_id) WHERE external_job_id IS NOT NULL AND company_id IS NOT NULL.
- qualifications (user-owned): the spec's fields (opportunity_id composite FK, kind CHECK ('minimum','preferred'), ordinal, text_verbatim, category CHECK per spec, skill_keys text[], min_years nullable, is_hard_constraint bool) plus origin CHECK ('extracted','user'), llm_run_id nullable composite FK, created_at, updated_at.
- Grants to career_os_app: companies SELECT, INSERT, UPDATE; opportunities SELECT, INSERT, UPDATE; qualifications SELECT, INSERT, DELETE, and UPDATE only on (kind, ordinal, category, skill_keys, min_years, is_hard_constraint, updated_at) so text_verbatim is immutable by privilege ("verbatim text always kept"). No DELETE on companies or opportunities. Tests prove grants and immutability.
- Domain events (written in the same transaction as the state change, payloads hold ids and field names only, never text): OPPORTUNITY_INGESTED, OPPORTUNITY_EXTRACTED, OPPORTUNITY_CONTENT_EDITED (changed field names), OPPORTUNITY_PRIORITY_CHANGED, COMPANY_CREATED, COMPANY_PRIORITY_CHANGED. Register payload schemas with schema_version.

B. Ingest (POST /api/v1/opportunities/ingest, authenticated + CSRF)
- Body: jd_text (required, trimmed, 200 to 50,000 characters), source_url (optional; http or https only, max 2,048 chars; stored, never fetched).
- Store the JD as an immutable artifact (kind jd_snapshot, UTF-8 text object through the storage adapter, extracted_text = the text, extraction_status succeeded). Per-user SHA-256 dedup: an identical paste returns 409 duplicate_jd with the existing opportunity id.
- One transaction: artifact, opportunity (status new, extraction_status pending, content_updated_at = now), OPPORTUNITY_INGESTED event, job extract_jd (user_id = owner, payload {opportunity_id}, unique_key extract_jd:<opportunity_id>). Remove the stored object if the transaction fails. Respond 202 with the opportunity.
- INV-17: the paste is the explicit user action that authorizes this one model call.

C. Extraction (worker job extract_jd; the only automatic model call in this task)
- Re-resolve the opportunity and its artifact through user-scoped repositories (INV-18). Run only when extraction_status is pending; otherwise do nothing (idempotent).
- Call ModelGateway.structured with a new versioned prompt (prompt id jd.extract, purpose extract_jd, tier fast; update prompts.lock.json). The JD text is an untrusted variable. Output schema: company_name, company_domain (optional), title, team, external_job_id, location_text, locations, workplace_type, qualifications [{kind, text_verbatim, category, skill_keys, min_years, is_hard_constraint}] with sensible caps (for example at most 80 qualifications, 10 skill keys each).
- Deterministic post-validation before applying anything:
  - verbatim grounding: keep a qualification only if its text_verbatim, after whitespace normalization, occurs in the JD text; drop the rest and log only the dropped count;
  - normalize skill keys (trimmed, lowercase, deduplicated, length-capped), clamp min_years to 0..50, validate the domain format and ISO country codes, and discard invalid values instead of failing the whole extraction.
- Apply as extracted origin in one transaction: resolve or create the company (D), fill only opportunity fields that are still empty (never overwrite a value the user already set), insert qualifications only if the opportunity has none (origin extracted, llm_run_id set), set extraction_status succeeded and llm_run_id, bump content_updated_at, write OPPORTUNITY_EXTRACTED. No review items: INV-07 explicitly allows JD extraction to populate Opportunity, Qualification and Company fields as extracted origin, because they describe the posting, not the user.
- Failures: llm_budget_exhausted, llm_output_invalid or a provider error mark extraction_status failed with that error code and do not retry automatically (a retry would be hidden model work). Infrastructure errors (database, storage) may retry through the job queue.
- POST /api/v1/opportunities/{id}/extract re-runs extraction only when extraction_status is failed (explicit user action); otherwise 409 invalid_state.

D. Company resolution
- normalized_name: lowercase, Unicode NFKC, punctuation removed, whitespace collapsed, common legal suffixes stripped (inc, llc, ltd, limited, corp, corporation, co, gmbh, plc, sa, ag, bv, pvt, private; whole words at the end only). Document the list; test it.
- Domains: lowercase, strip scheme, path and a leading www.; validated hostname.
- Resolution order: an existing company whose domains contain the extracted domain; then one whose normalized_name equals the normalized extracted name; then one whose normalized aliases contain it; otherwise create a company (origin extracted) and record COMPANY_CREATED. Each match path is tested, including cross-user isolation (never match another user's company).

E. Duplicate detection (on read; deterministic; no model)
- GET /api/v1/opportunities/{id}/duplicates returns the caller's other opportunities that are: exact (same company and same external_job_id), same JD (same artifact sha256 is already blocked at ingest), or likely (same company and normalized-title similarity of 0.9 or more using difflib, with a matching or empty location). Each result carries a reason (exact_job_id or similar_title).
- If extraction finds a job ID that would violate the partial unique index, leave external_job_id empty on the new opportunity; it then appears as a duplicate. Test it.

F. Editing (all fields user-editable)
- PATCH /api/v1/opportunities/{id} {expected_state_version, title, team, external_job_id, location_text, locations, workplace_type, company_id (must be the caller's company), source_url}: optimistic version check (stale → 409 conflict), unique-index conflict → 409 duplicate_job_id, bumps content_updated_at and state_version, writes OPPORTUNITY_CONTENT_EDITED with field names. A no-op edit changes nothing.
- PATCH /api/v1/opportunities/{id}/priority {priority}: does NOT bump content_updated_at; writes OPPORTUNITY_PRIORITY_CHANGED.
- Qualifications: POST /api/v1/opportunities/{id}/qualifications (origin user, the user's own text), PATCH /api/v1/qualifications/{id} (kind, category, skill_keys, min_years, is_hard_constraint, ordinal only; text_verbatim is never editable), DELETE /api/v1/qualifications/{id}. Every qualification change bumps the parent opportunity's content_updated_at.
- Companies: GET /api/v1/companies, GET /api/v1/companies/{id} (with opportunity counts by status), POST /api/v1/companies (origin user), PATCH /api/v1/companies/{id} (name with normalized_name recomputed and uniqueness 409 company_name_taken, aliases, domains, careers_url, notes, strategic_priority with COMPANY_PRIORITY_CHANGED).
- Reads: GET /api/v1/opportunities (filters status, priority, company_id; newest first), GET /api/v1/opportunities/{id} (with company, qualifications in ordinal order, JD text from the artifact, extraction status).
- Foreign ids → 404 everywhere; every new route gets an isolation case.

G. Frontend (minimal; design is Task 10)
- Opportunities page: paste form (JD textarea and optional source URL), list with company, title, status, priority, extraction status; bounded polling while extraction is pending.
- Opportunity detail page: editable fields, priority select, qualifications table (edit normalized fields, add, delete; verbatim text shown read-only), duplicates panel, JD text rendered as plain text, source URL shown as plain text (full URL visible, never a fetched preview), "Retry extraction" only when failed, with plain messages for llm_budget_exhausted and other error codes, and a stale-version conflict message.
- Companies page: list and edit (name, aliases, domains, careers URL, notes, strategic priority).
- Nav links: Opportunities and Companies. Regenerate openapi.json and schema.d.ts and use the generated types. Vitest tests for paste, polling, editing, conflict, retry visibility, plain-text rendering of hostile JD content, and company priority.

H. Config, docs
- Settings: JD_MIN_CHARS, JD_MAX_CHARS, JD_EXTRACTION_MAX_OUTPUT_TOKENS (sensible defaults), passed to the services that need them.
- docs/architecture/opportunities.md: ingest pipeline, the INV-07 extraction exception and its safeguards (extracted origin, verbatim grounding, fill-empty-only, no automatic retries), the prompt and its untrusted delimiting, company normalization and resolution, duplicate rules, editing and content_updated_at, events, what is deferred (company merge, URL fetching, state transitions in Task 7, evaluation in Task 11).
- Update README (configuration and a short section) and docs/architecture/database.md (tables, grants, partial unique index, the latest_evaluation_id FK deferral).

ACCEPTANCE CHECKS YOU MUST RUN
1. Backend: ruff check, ruff format --check, mypy, full pytest with Postgres and REQUIRE_DB_TESTS=1 (all earlier tests pass). Extraction tests use FakeProvider with scripted outputs, including: a qualification not present in the JD (dropped), a hostile JD containing instructions (wrapped as untrusted; output still validated), a job ID that collides (left empty, shown as duplicate), budget refusal (failed with llm_budget_exhausted, no automatic retry), invalid output twice (failed with llm_output_invalid), and the explicit retry endpoint.
2. Migrations on an empty DB: upgrade head → alembic check → downgrade base → upgrade head.
3. Frontend: lint, typecheck, test, build; generated OpenAPI types up to date.
4. Stack with the fake provider: docker compose up --build -d; migrate exits 0; /healthz 200 on 127.0.0.1. With a synthetic user and session created as owner (deleted afterwards), ingest a synthetic JD through the API; show the 202, the worker logs, extraction_status succeeded, the llm_runs row, the opportunity, company and qualifications in the database; ingest the same JD again (409); edit a field and show content_updated_at moved while a priority change does not move it.
5. Live UI check (I will do this, fake provider): give me exact steps for pasting a synthetic JD you provide, seeing it extract (fake values), editing fields and a qualification, changing priority and company strategic priority, and viewing duplicates.
6. OPTIONAL real extraction (ask me first; only if I add an ANTHROPIC_API_KEY and the Anthropic settings to .env): one extraction of your synthetic JD with the real provider; show the llm_runs row (tokens, cost under $0.02) and the extracted fields and qualifications. If I decline or have no key, record it as not run.
7. Push the branch (ask me first) and confirm GitHub Actions is green for backend, frontend and secrets.

ESCALATION
If you find a spec contradiction, a required architecture change, a required scope change, a security issue affecting the frozen design, a schema requirement beyond companies, opportunities and qualifications and the authorized extra columns above, or a missing prerequisite that changes architecture: STOP that part and report:
PROBLEM / EVIDENCE / WHY THE CURRENT SPEC CANNOT BE FOLLOWED / SMALLEST OPTIONS / RECOMMENDATION / WHAT IS BLOCKED
Continue only with work that does not depend on the outcome. Do not silently redesign.

GIT AND FINISH
- Commit in logical steps on task-06-jd-ingestion with clear messages and no attribution trailers.
- Push (ask first). gh is not authenticated; give me the compare URL. Do NOT merge.
- Write docs/checkpoints/task-06.md in this format, commit and push it (ask first):
  What was implemented (mapped to each acceptance criterion) / Evidence / Changes outside the expected file set (file, change, reason) or none / Important things I learned (4 to 8 bullets, specific) / Checks run and results (table) / Deviations from the frozen spec or none / Unresolved issues / Git state (branch, commits, PR URL, CI status) / Recommendation: approve or not, with reason
- Then STOP. Do not start Task 7.

Begin with Step 0.
