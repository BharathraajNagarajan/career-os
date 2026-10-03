You are my hands-on implementation and debugging partner for Career OS, working in C:\Users\bhara\career-os on Windows with Docker Desktop (WSL2). GNU Make is not installed; use docker compose, uv and npm directly. Everything you need is in this brief, the repository, and docs/.

STEP 0: PRE-FLIGHT
1. Confirm you are running on a Sonnet model. If not, tell me before doing anything else.
2. git switch main && git pull. Confirm main contains the merged Task 6 work (docs/checkpoints/task-06.md, backend/app/opportunities/) and the working tree is clean.
3. Confirm python resolves to backend\.venv, Docker is running (docker info), and node -v is v22.x.
4. Create branch task-07-state-machines from main.
5. FIRST save this entire brief verbatim to docs/briefs/task-07.md and commit it ("docs: Task 7 brief"). Long shell heredocs break on this host: write files with your editor tool or a script file, not cat <<EOF.
Then continue through decisions A to H and checks 1 to 4 without stopping for confirmation. Stop only for approve-each-time items, an escalation, or check 5 (my UI check).

AUTHORIZED SCOPE
Only Phase 1A Task 7: state machines. The only new table is applications. Do NOT start Task 8: no recruiting_actions, contacts or interactions tables and no RecruitingAction API. RecruitingAction gets ONLY its pure transition function and tests in this task, so Task 8 can use it. No model calls of any kind: this task is fully deterministic. Do not register review handlers for create_application or application_event yet (their producer is Gmail, Task 13), but shape the commands so a handler can call them later with an actor and an optional source_ref_id.

SOURCE OF TRUTH (read before coding)
- docs/spec/phase-0-spec.md (FROZEN): 0A (Opportunity vs Application), 1.3 (invariants, especially INV-04, INV-07, INV-14, INV-17, INV-18), 2.1, 4.1 (state versions, JSONB, events), the Application, DomainEvent and RecruitingAction rows, 5 (all of it: 5.1 Application event table and stage rules, 5.2 Opportunity transitions in their LATEST revision, 5.3 RecruitingAction, 5.5 shared rules), 9 (Applications and timeline rows), 11, 14 (Task 7 acceptance criteria)
- docs/architecture/database.md, opportunities.md, review.md; docs/checkpoints/task-06.md
- backend/app/ (events repository and payload registry, versioning, tenancy, opportunities service, isolation harness)
The spec wins over this brief. If they disagree, stop and escalate. Where the spec defines names (event types, stages, channels, transitions), use the spec's names exactly.

WORKING RULES
- You own local operations for this task only: terminal, Docker/Compose, Git, dependencies, tests, debugging, code edits.
- Never install or download anything without asking, including npx tools and pip packages. Project dependencies via uv add / npm install need my approval in this task.
- Approve-each-time: any install, git push, docker compose down -v, and deleting files outside build caches.
- NEVER add Co-Authored-By, "Generated with Claude" or any Claude attribution to commits or PR text. I am the sole contributor.
- Learning mode: briefly explain meaningful concepts as you work (pure transition functions, event-sourced projection versus materialized state, ordering by occurred_at versus recorded_at, voiding instead of deleting, terminal freezing and reopening, atomic multi-aggregate commands, partial unique indexes as race guards, optimistic concurrency, merged timelines). Skip trivial commands.
- Debugging rule: observe → identify failing layer → hypothesis → inspect evidence → smallest justified change → rerun failing check → rerun related checks. Say explicitly when a problem is environmental.
- Use 127.0.0.1 for local DB URLs and curl; browser checks use http://localhost:5173. .env has a BOM and JSON values: never source it; read single values.
- No code comments; minimal readable code; don't restructure working Task 1-6 code unless required.
- INV-01: synthetic data only. Never log notes or free text; log ids, event types, stages and error codes.
- Use the database clock (now()) for recorded_at and for server-assigned timestamps, as Task 6 established.
- Commit after every logical step.

TASK 7 ACCEPTANCE CRITERIA (spec section 14)
Pure transition functions for Opportunity, Application and RecruitingAction with exhaustive tests; Save, Skip, Apply, Close; Apply creates the Application atomically; manual event recording; void and reopen; projection correct under out-of-order and voided events; optimistic concurrency; single ordered timeline.

IMPLEMENTATION DECISIONS ALREADY MADE BY THE PLANNING CHAT (they translate the spec, they do not change it)

A. Table (next migration, hand-reviewed, grants, working downgrade)
- applications (user-owned, state machine): the spec's fields: opportunity_id (composite FK to opportunities), resume_id (nullable composite FK to resumes), lane_id (nullable composite FK to resume_lanes), applied_at, channel, stage (materialized), is_terminal, state_version, plus created_at and updated_at. stage CHECK lists the spec's stages exactly. channel: use the spec's list if it defines one; otherwise a CHECK on ('company_site', 'job_board', 'referral', 'recruiter', 'email', 'other') with default 'other'. A CHECK ties is_terminal to the terminal stages. Partial UNIQUE (user_id, opportunity_id) WHERE NOT is_terminal (the spec's "one non-terminal application per opportunity").
- Grants to career_os_app: SELECT, INSERT, UPDATE; no DELETE. Account deletion cascades.
- No new event table: application and opportunity history go in domain_events (aggregate types already include opportunity and application). Register a typed payload with schema_version for every event type this task writes. Application event payloads carry an optional note (at most 1,000 characters, stored, never logged) and nothing else that is free text; OPPORTUNITY_DECIDED carries the decision and an optional reason (at most 500 characters).

B. Pure transition functions (app/state_machines/, no database, no I/O)
- opportunity_transition(status, command) → (new_status, event_types) or a typed error, implementing the LATEST 5.2 table exactly (including Apply from Skipped or Closed and Close only from non-Applied states if that is what the frozen file says).
- application_projection(events) → (stage, is_terminal): stage is the stage of the latest non-voided stage-bearing event ordered by (occurred_at, recorded_at, id); a terminal event freezes the stage until a later APPLICATION_REOPENED; after a reopen, terminal events at or before the reopen are ignored and the stage is recomputed from the remaining non-voided events (if none bear a stage after the submission, the stage is the latest non-terminal one before the reopen). Voided events and EVENT_VOIDED events themselves never bear a stage.
- application_command_check(state, command) → events or a typed error: record_event (allowed types per 5.1; APPLICATION_SUBMITTED only via Apply; EVENT_VOIDED and APPLICATION_REOPENED only via their own commands; the system may never apply MARKED_NO_RESPONSE), void_event (cannot void APPLICATION_SUBMITTED, an EVENT_VOIDED, an already-voided event, or another aggregate's event), reopen (only when terminal).
- recruiting_action_transition(status, command) per 5.3 (open, snoozed, done, dismissed, superseded; snooze needs a future until; superseded is system-only and reversible). Functions and tests only.
- Exhaustive tests: every (state, command) pair for each machine, asserting either the exact result or the exact typed error (no silent no-ops, 5.5). Projection tests: insertion order independence (shuffled event lists give the same stage), backdated events, ties broken deterministically, voiding a terminal event, voiding a reopen, reopen followed by new stages.

C. Opportunity commands (one transaction each, expected_state_version required, typed 409s)
- POST /api/v1/opportunities/{id}/save {expected_state_version, reason?}, /skip {expected_state_version, reason?}, /close {expected_state_version, reason?}: run the pure transition, update status and state_version via update_versioned, write OPPORTUNITY_DECIDED (or the spec's event name for each decision). Invalid transition → 409 invalid_transition; stale → 409 conflict. These change status only and never move content_updated_at.
- POST /api/v1/opportunities/{id}/apply {expected_state_version, resume_id?, lane_id?, channel?, applied_at?}: in ONE transaction, transition the opportunity to applied, create the application (stage applied, not terminal), write APPLICATION_SUBMITTED on the application aggregate (occurred_at = applied_at, default now()) and the opportunity decision event, sharing a correlation_id. resume_id and lane_id are re-resolved as the caller's (foreign → 404); an archived resume or lane → 422. applied_at may not be more than 5 minutes in the future (422 occurred_at_in_future).
- Race safety: two concurrent applies on the same opportunity yield exactly one application and one 409. Prove it with a threaded real-Postgres test (the version check and the partial unique index are the guards).
- Every opportunity response includes allowed_actions computed by the pure function, so the UI never duplicates the rules.

D. Application commands (expected_state_version on every command)
- GET /api/v1/applications (filter stage, is_terminal; newest first, with opportunity title and company name), GET /api/v1/applications/{id}.
- POST /api/v1/applications/{id}/events {expected_state_version, event_type, occurred_at, note?}: check, append, recompute the projection from ALL the application's events, update stage, is_terminal and state_version in the same transaction. occurred_at may be backdated freely but not more than 5 minutes in the future.
- POST /api/v1/applications/{id}/events/{event_id}/void {expected_state_version, reason?}: append EVENT_VOIDED with voids_event_id, then recompute.
- POST /api/v1/applications/{id}/reopen {expected_state_version, note?}: append APPLICATION_REOPENED, then recompute.
- Projection consistency: a test reads every application after a random sequence of commands and asserts its stored stage equals application_projection of its events.

E. Single ordered timeline
- GET /api/v1/opportunities/{id}/timeline: one list merging the opportunity's events and its application's events, ordered by (occurred_at, recorded_at, id). Each entry has id, aggregate type, event_type, occurred_at, recorded_at, actor, voided (true if a later EVENT_VOIDED targets it), voids_event_id, note or reason, and a voidable flag from the pure function. Voided entries stay in the list, marked. Built so Task 8 can add interactions and actions as more sources.

F. API rules
- All routes are authenticated with CSRF on mutations; foreign ids → 404; every new route gets an isolation case. Typed errors for every refusal (invalid_transition, conflict, occurred_at_in_future, cannot_void, already_voided, not_terminal, plus 422 validation).
- Domain events are written in the same transaction as the state change, with actor user. Commands accept an internal actor and source_ref_id parameter (not exposed in the API) for the future review handlers.

G. Frontend (minimal; design is Task 10)
- Opportunity detail: decision buttons (Save, Skip, Apply, Close) shown from allowed_actions; Skip and Close prompt for an optional reason; Apply opens a small form (resume select from active resumes, lane select from active lanes, channel, applied date defaulting to today). After Apply, an Application panel shows the stage, a record-event form (event type select limited to user-recordable types, occurred date and time, optional note), Reopen when terminal, and the timeline with Void on voidable entries (voided entries shown as voided, notes as plain text).
- Applications page (nav link): list with company, title, stage, applied date, linking to the opportunity.
- Stale-version conflict and invalid-transition messages shown plainly with a refresh. Regenerate openapi.json and schema.d.ts. Vitest tests for decisions, Apply, recording, voiding, reopening, conflict handling and plain-text notes.

H. Docs
- docs/architecture/state-machines.md: the three machines (tables of transitions), Opportunity versus Application, the projection rules with worked examples (backdated event, voided terminal event, reopen), the timeline, concurrency guards, the actor and source_ref_id hook for Task 13, and what is deferred (RecruitingAction persistence to Task 8, review handlers to Task 13).
- Update README and docs/architecture/database.md (the table, grants, partial unique index, which events are written).

ACCEPTANCE CHECKS YOU MUST RUN
1. Backend: ruff check, ruff format --check, mypy, full pytest with Postgres and REQUIRE_DB_TESTS=1 (all earlier tests pass), including the exhaustive transition tests, projection-order tests, the projection-consistency test and the threaded apply-race test (run the race test 10 times in a row).
2. Migrations on an empty DB: upgrade head → alembic check → downgrade base → upgrade head.
3. Frontend: lint, typecheck, test, build; generated OpenAPI types up to date.
4. Stack: docker compose up --build -d; migrate exits 0; /healthz 200 on 127.0.0.1. With a synthetic user and session created as owner and removed afterwards through account deletion: ingest a synthetic JD, Save, Skip, then Apply; record ASSESSMENT_RECEIVED, INTERVIEW_SCHEDULED and a backdated INTERVIEW_REQUESTED; record REJECTED (terminal); void the REJECTED (stage returns to interviewing); record WITHDRAWN, then reopen; show the stored stage after each step, the timeline in order with the voided entry marked, and the stored stage equal to the projection of the events.
5. Live UI check (I will do this): give me exact numbered steps on the existing posting from my Task 6 UI check (Example Corp, Senior Widget Engineer): Save, Skip with a reason, Apply with a resume and lane, record two events including one backdated, void one, record a terminal event, reopen, and confirm the timeline order and the Applications page.
6. Push the branch (ask me first) and confirm GitHub Actions is green for backend, frontend and secrets.

ESCALATION
If you find a spec contradiction, a required architecture change, a required scope change, a security issue affecting the frozen design, a schema requirement beyond applications and the authorized columns above, or a missing prerequisite that changes architecture: STOP that part and report:
PROBLEM / EVIDENCE / WHY THE CURRENT SPEC CANNOT BE FOLLOWED / SMALLEST OPTIONS / RECOMMENDATION / WHAT IS BLOCKED
Continue only with work that does not depend on the outcome. Do not silently redesign.

GIT AND FINISH
- Commit in logical steps on task-07-state-machines with clear messages and no attribution trailers.
- Push (ask first). gh is not authenticated; give me the compare URL. Do NOT merge.
- Write docs/checkpoints/task-07.md in this format, commit and push it (ask first):
  What was implemented (mapped to each acceptance criterion) / Evidence / Changes outside the expected file set (file, change, reason) or none / Important things I learned (4 to 8 bullets, specific) / Checks run and results (table) / Deviations from the frozen spec or none / Unresolved issues / Git state (branch, commits, PR URL, CI status) / Recommendation: approve or not, with reason
- Then STOP. Do not start Task 8.
