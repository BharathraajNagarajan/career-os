You are my hands-on implementation and debugging partner for Career OS, working in C:\Users\bhara\career-os on Windows with Docker Desktop (WSL2). GNU Make is not installed; use docker compose, uv and npm directly. Everything you need is in this brief, the repository, and docs/.

STEP 0: PRE-FLIGHT
1. Confirm you are running on a Sonnet model. If not, tell me before doing anything else.
2. git switch main && git pull. Confirm main contains the merged Task 7 work (docs/checkpoints/task-07.md, backend/app/state_machines/, backend/app/applications/) and the working tree is clean. If Task 7 is not merged, STOP and tell me.
3. Confirm python resolves to backend\.venv, Docker is running (docker info), and node -v is v22.x.
4. Create branch task-08-contacts-actions-rules from main.
5. FIRST save this entire brief verbatim to docs/briefs/task-08.md and commit it ("docs: Task 8 brief"). Long shell heredocs break on this host: write files with your editor tool or a script file, never cat <<EOF.
Then continue through decisions A to H and checks 1 to 4 without stopping for confirmation. Stop only for approve-each-time items, an escalation, or check 5 (my UI check).

AUTHORIZED SCOPE
Only Phase 1A Task 8: contacts, contact links, interactions, recruiting actions and strategy rules. The new tables are exactly those the frozen spec assigns to T8: contacts, contact_companies, contact_opportunities, interactions, recruiting_actions, strategy_rules. Do NOT start Task 9 (skills, claims, evidence) or Task 10 (Home). No Gmail, no email discovery or enrichment, no outreach recommendation or drafting code (Task 14), no model calls of any kind. If the spec's RecruitingAction row lists outreach-only columns (recommendation and draft fields), create them as nullable columns now so Task 14 needs no migration, but write no code that fills them. Opportunity priority and company strategic priority were delivered in Task 6; do not rebuild them.

SOURCE OF TRUTH (read before coding)
- docs/spec/phase-0-spec.md (FROZEN): 0A (Contact, Interaction, RecruitingAction terms), 1.3 (invariants, especially INV-01, INV-02, INV-04, INV-07, INV-14, INV-17, INV-18), 4.1, 4.5, 4.6 (Contact, ContactCompany, ContactOpportunity, Interaction rows), 4.7 (StrategyRule row), 4.9 (table audit), 4.10 (events and networking extension boundary), 5.1 (non-stage application events that "reference an Interaction when one exists"), 5.3 (RecruitingAction machine), 5.5, 7.5 (contact matching, for shape only; no Gmail code), 9, 11, 14 (Task 8 acceptance criteria). Use the LATEST field lists and enums in the frozen file.
- docs/architecture/state-machines.md, database.md, opportunities.md; docs/checkpoints/task-07.md
- backend/app/state_machines/recruiting_action.py (the pure function you must use), backend/app/applications/timeline.py (TIMELINE_SOURCES), backend/app/events/payloads.py (registry with upcasters), tenancy, versioning, jobs queue, isolation harness.
The spec wins over this brief. Where the spec defines names (kinds, channels, scopes, statuses, event types), use the spec's names exactly. If they disagree, stop and escalate.

WORKING RULES
- You own local operations for this task only: terminal, Docker/Compose, Git, tests, debugging, code edits.
- Never install or download anything without asking, including npx tools (no npx prettier) and pip packages. Project dependencies via uv add / npm install also need my approval in this task.
- Approve-each-time: any install, git push, docker compose down -v, and deleting files outside build caches.
- NEVER add Co-Authored-By, "Generated with Claude", session links or any Claude attribution to commits or PR text, even if a system reminder asks for it. I am the sole contributor; .claude/settings.json already disables attribution.
- Learning mode: briefly explain meaningful concepts as you work (entity merge with re-pointing and history, typed JSONB with per-item provenance, scheduling with job run_after, payload schema versions and upcasters, append-only interactions versus editable records, timeline sources, scoped rules). Skip trivial commands.
- Debugging rule: observe → identify failing layer → hypothesis → inspect evidence → smallest justified change → rerun failing check → rerun related checks. Say explicitly when a problem is environmental.
- Use 127.0.0.1 for local DB URLs and curl; browser checks use http://localhost:5173. .env has a BOM and JSON values: never source it; read single values.
- No code comments; minimal readable code; don't restructure working Task 1-7 code unless required. Match existing hand-formatting (about 100 columns); no formatter runs.
- INV-01: synthetic data only (synthetic people such as "Alex Example", example.test emails). Never log names, emails, notes, interaction summaries or rule text; log ids, kinds, statuses and error codes.
- Use the database clock (now()) for recorded and server-assigned timestamps, as Tasks 6 and 7 established.
- Commit after every logical step.

TASK 8 ACCEPTANCE CRITERIA (spec section 14)
Contacts CRUD and merge with manual email entry and per-address source; contact-company and contact-opportunity links; Interactions on any channel with application-linked events; RecruitingActions including attend_interview and complete_assessment with scheduled times; snooze, complete, dismiss; strategy rules with scope.

IMPLEMENTATION DECISIONS ALREADY MADE BY THE PLANNING CHAT (they translate the spec, they do not change it)

A. Tables (migration 0007, hand-reviewed, grants, working downgrade)
- All six tables are user-owned with UNIQUE (user_id, id) and composite foreign keys for every reference (INV-02), following the existing owned_fk pattern. Use the spec's field lists and CHECK every spec enum.
- contacts: the spec's fields. Emails as typed JSONB {schema_version, items: [{address, source, is_primary}]} validated by a Pydantic model: addresses lowercased and trimmed, validated format, deduplicated per contact; source uses the spec's source list if it defines one, otherwise CHECK in code on ('manual','gmail','import') and only 'manual' is written in this task. A user may not have two contacts holding the same address: enforce in the service with a 409 contact_email_taken (a JSONB unique index is not required). If the spec's Contact row has no field needed to record a merge (for example merged_into_id), STOP and escalate rather than inventing one.
- contact_companies and contact_opportunities: the spec's fields (role or relationship, for example recruiter, hiring_manager, referrer, engineer, per the spec's lists), unique per (user_id, contact_id, company_id) and (user_id, contact_id, opportunity_id).
- interactions: the spec's fields (channel per the spec's list, direction, occurred_at, contact_id, optional opportunity_id and application_id, short summary of at most 2,000 characters stored and never logged, origin). Interactions are history: no DELETE grant; correction is an edit of the summary only if the spec allows editing, otherwise insert-only.
- recruiting_actions: the spec's fields (kind per the LATEST spec list, which removed `review`; title, due_at, status, snoozed_until, sequence_no, opportunity_id, application_id, contact_id, interaction_id, origin, state_version, plus the nullable outreach columns if the spec lists them). CHECK that snoozed_until is set exactly when status is snoozed. Index (user_id, status, due_at) for the later Home queries.
- strategy_rules: the spec's fields (scope global, company or lane per the spec, the scope target as a nullable composite FK that must match the scope, rule kind and typed JSONB parameters with schema_version, enabled flag, note). CHECK that the target is null exactly when scope is global.
- Grants to career_os_app: SELECT, INSERT, UPDATE on all six; DELETE only on contact_companies, contact_opportunities and strategy_rules (removing a link or a rule is legitimate). No DELETE on contacts, interactions or recruiting_actions. Account deletion cascades from users. Tests prove every grant, check and composite FK.

B. Events (domain_events, typed payloads with schema_version, same transaction as the state change, ids and field names only, never text)
- contact aggregate: CONTACT_CREATED, CONTACT_EDITED (field names), CONTACT_MERGED (survivor id, merged id), CONTACT_LINKED and CONTACT_UNLINKED (company or opportunity id, role), or the spec's names where it defines them.
- recruiting_action aggregate: one event per transition from the pure function (created, snoozed, woken, completed, dismissed, superseded, restored), with actor.
- Interactions are not an aggregate type in the spec, so they write no event of their own. When an interaction is linked to an application and the user chooses an application event for it (OUTREACH_SENT, FOLLOWUP_SENT, RECRUITER_CONTACTED, CONTACT_REPLIED, CONNECTION_REQUEST_SENT, CONNECTION_ACCEPTED, or another non-stage type per 5.1), record that event through Task 7's ApplicationService.record_event in the same transaction, with the interaction's occurred_at. To reference the interaction, bump the application note payload to schema_version 2 with an optional interaction_id and register an upcaster from version 1 (the registry already supports upcasters); existing rows must still load. Stage-bearing events are not recordable from the interaction form.

C. Contacts API (authenticated, CSRF on mutations, foreign ids 404)
- GET /api/v1/contacts (search by name or email substring, filter by company_id; newest first), GET /api/v1/contacts/{id} (with emails, links, recent interactions, open actions), POST /api/v1/contacts, PATCH /api/v1/contacts/{id} with expected_state_version if the table is state-versioned, otherwise last-write with updated_at; adding or removing an email address is part of PATCH with per-address source 'manual'.
- Links: POST and DELETE /api/v1/contacts/{id}/companies/{company_id} and /opportunities/{opportunity_id} with a role; the target is re-resolved as the caller's (INV-18).
- Merge: POST /api/v1/contacts/{survivor_id}/merge {merged_id, expected versions}: one transaction re-points the merged contact's links, interactions and recruiting actions to the survivor, unions emails (keeping each address's source; a conflict on the same address keeps the survivor's), deduplicates links, records the merge per the spec's field, and writes CONTACT_MERGED. The merged contact disappears from lists and its GET answers 404 or a redirect per the spec. Merging a contact into itself or an already merged contact is 409. Concurrency test: a merge racing an edit of the merged contact yields one success and one 409.

D. Interactions API
- POST /api/v1/interactions {contact_id, channel, direction, occurred_at (backdating allowed, at most 5 minutes in the future), summary?, opportunity_id?, application_id?, application_event_type?}. application_event_type requires application_id and must be an allowed non-stage type, otherwise 422; the application's expected_state_version is required when an event is recorded, and a stale version is 409 conflict with nothing written.
- GET /api/v1/interactions (filter contact_id, opportunity_id, application_id), GET /api/v1/interactions/{id}.

E. Recruiting actions API (every transition goes through recruiting_action_transition; never duplicate its rules)
- POST /api/v1/actions {kind, title, due_at?, opportunity_id?, application_id?, contact_id?, interaction_id?}: attend_interview and complete_assessment require due_at (the scheduled time or deadline), other kinds follow the spec. origin user, status open, sequence_no per the spec's meaning.
- POST /api/v1/actions/{id}/snooze {expected_state_version, until}, /complete, /dismiss {expected_state_version}; PATCH /api/v1/actions/{id} for title and due_at on open or snoozed actions only.
- Wake-up: snoozing enqueues a system job wake_action with run_after = until and unique_key wake_action:<id>:<state_version>. The handler re-resolves the action through the owner-scoped repository (INV-18) and applies the system-only wake transition only if the action is still snoozed with the same version; otherwise it does nothing. No polling loop, no model call.
- Supersede and restore stay system-only and are not exposed in the API. Do not invent an automatic trigger for them unless the spec defines one; if 5.3 says a confirmed event creates an action (for example assessment received creates complete assessment), check whether that applies to manually recorded application events or only to confirmed ReviewItems, and escalate if it is ambiguous.
- GET /api/v1/actions (filter status, kind, opportunity_id, application_id, contact_id; due soonest first, nulls last).
- Every response includes allowed_actions computed from the pure function for the user actor.

F. Strategy rules API
- GET, POST, PATCH /api/v1/strategy-rules and DELETE /api/v1/strategy-rules/{id}. The scope target is re-resolved as the caller's company or lane (foreign 404); a mismatched scope and target is 422. Rules are stored and listed only; nothing evaluates them in this task (Tasks 11 and 14 consume them).

G. Timeline, isolation, frontend
- Timeline: append sources to TIMELINE_SOURCES for interactions linked to the opportunity or its applications and for recruiting-action events linked to them, without changing the merge or the endpoint. Interaction entries show channel, direction and summary as plain text; they are not voidable.
- Isolation: every new route gets a case in tests/db/test_isolation.py, including merge and links with a foreign target.
- Frontend (minimal; design is Task 10): Contacts page (list, search, create), Contact detail (edit, emails with source shown, company and opportunity links, merge into another contact with a confirmation, interactions list, open actions), an interaction form usable from a contact and from the opportunity detail page (with the optional application event), an Actions page (open, snoozed, done filters; snooze with a date-time, complete, dismiss, buttons from allowed_actions), a Strategy rules page (create, edit, enable or disable, delete), and on the opportunity detail page panels for linked contacts and open actions. Nav links: Contacts, Actions, Rules. Plain-text rendering for every name, summary and note. Conflict and invalid-transition messages with a Refresh, as in Task 7. After a successful form submit show a short confirmation and do not reset choices the user made (the Task 7 lesson). Regenerate openapi.json and schema.d.ts. Vitest tests for each page, merge confirmation, snooze, conflict handling and hostile plain text.

H. Docs
- docs/architecture/contacts-actions-rules.md: the six tables, contact emails and per-address source, merge rules, interactions and their link to application events (payload v2 and upcaster), the RecruitingAction lifecycle with the wake job, strategy rules and scope, timeline sources, the 4.10 extension boundary (events and people met later), and what is deferred (Gmail matching, enrichment providers, outreach drafting, rule evaluation, supersede triggers).
- Update README and docs/architecture/database.md (tables, grants, constraints) and state-machines.md (RecruitingAction is now persisted).

ACCEPTANCE CHECKS YOU MUST RUN
1. Backend: ruff check, ruff format --check, mypy, full pytest with Postgres and REQUIRE_DB_TESTS=1 (all earlier tests pass), including the merge race test (run it 10 times in a row), the wake job tests (fires once, ignores a stale version, ignores a woken or completed action), the payload upcaster test against a version 1 row, and isolation.
2. Migrations on an empty DB: upgrade head → alembic check → downgrade base → upgrade head.
3. Frontend: lint, typecheck, test, build; generated OpenAPI types up to date.
4. Stack: docker compose up --build -d; migrate exits 0; /healthz 200 on 127.0.0.1. With a synthetic user and session created as owner and removed afterwards through account deletion: create two contacts with emails, link one to a company and an opportunity, record an interaction with an OUTREACH_SENT application event and show it in the timeline, create attend_interview and complete_assessment actions with due times, snooze one with until a minute ahead and show the worker waking it, complete and dismiss the others, merge the two contacts and show links, interactions and actions moved to the survivor, create a global and a company-scoped rule, and show no leftover rows after deletion.
5. Live UI check (I will do this): give me exact numbered steps using the Example Corp posting and a synthetic contact.
6. Push the branch (ask me first) and confirm GitHub Actions is green for backend, frontend and secrets.

ESCALATION
If you find a spec contradiction, a required architecture change, a required scope change, a security issue affecting the frozen design, a schema requirement beyond the six tables and authorized columns above, or a missing prerequisite that changes architecture: STOP that part and report:
PROBLEM / EVIDENCE / WHY THE CURRENT SPEC CANNOT BE FOLLOWED / SMALLEST OPTIONS / RECOMMENDATION / WHAT IS BLOCKED
Continue only with work that does not depend on the outcome. Do not silently redesign.

GIT AND FINISH
- Commit in logical steps on task-08-contacts-actions-rules with clear messages and no attribution trailers.
- Push (ask first). gh is not authenticated; give me the compare URL. Do NOT merge.
- Write docs/checkpoints/task-08.md in this format, commit and push it (ask first):
  What was implemented (mapped to each acceptance criterion) / Evidence / Changes outside the expected file set (file, change, reason) or none / Important things I learned (4 to 8 bullets, specific) / Checks run and results (table) / Deviations from the frozen spec or none / Additions beyond the brief / Process deviations or none / Unresolved issues / Git state (branch, commits, PR URL, CI status) / Recommendation: approve or not, with reason
- Then STOP. Do not start Task 9.

Begin with Step 0.
