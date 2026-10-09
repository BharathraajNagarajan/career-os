# Task 8 checkpoint: contacts, interactions, recruiting actions and strategy rules

Branch `task-08-contacts-actions-rules`, built on `main` after the Task 7 merge. Design notes: [contacts-actions-rules.md](../architecture/contacts-actions-rules.md).

## What was implemented (mapped to the acceptance criteria)

| Acceptance criterion (spec section 14) | Implementation |
| --- | --- |
| Contacts CRUD and merge with manual email entry and per-address source | `contacts` table (migration 0007); `GET/POST/PATCH /api/v1/contacts`, `GET /contacts/{id}`; emails are typed JSONB `{schema_version, items: [{address, source, added_at}]}` with `manual`/`gmail`/`provider` sources, only `manual` written; one contact per address per user (`409 contact_email_taken`, race-safe with an advisory lock); merge `POST /contacts/{survivor_id}/merge` re-points links, interactions and actions, unions emails (survivor wins a clash), writes `CONTACT_MERGED`, deletes the merged row; merged id then answers 404 |
| Contact-company and contact-opportunity links | `contact_companies`, `contact_opportunities`; `POST/DELETE /contacts/{id}/companies/{company_id}` and `/opportunities/{opportunity_id}`; targets re-resolved as the caller's; `CONTACT_LINKED` / `CONTACT_UNLINKED` |
| Interactions on any channel with application-linked events | `interactions` table (insert-only); `POST/GET /api/v1/interactions`; five channels, two directions; optional `application_event_type` (six non-stage types) recorded through `ApplicationService.record_event` in the same transaction; application note payload bumped to v2 with `interaction_id` and a v1 upcaster |
| RecruitingActions including attend_interview and complete_assessment with scheduled times | `recruiting_actions` table with all spec kinds and the nullable outreach columns; `POST/GET/PATCH /api/v1/actions`; both scheduled kinds require `due_at` (API and database check) |
| Snooze, complete, dismiss | `POST /actions/{id}/snooze\|complete\|dismiss` through `recruiting_action_transition`; `allowed_actions` on every response; snooze enqueues a `wake_action` job (`run_after = until`, `unique_key wake_action:<id>:<version>`) whose handler wakes the action only if it is still snoozed at that version |
| Strategy rules with scope | `strategy_rules` table; `GET/POST/PATCH/DELETE /api/v1/strategy-rules`; scope `global`/`company`/`lane` with a database check and a 422; target re-resolved as the caller's; typed optional `condition` |

Also: timeline sources for interactions and recruiting-action events; frontend pages Contacts, Contact detail, Actions, Strategy rules, an interaction form (on a contact and on the opportunity page) and opportunity panels for linked contacts and open actions; `GET /contacts?opportunity_id=` to feed the panel.

## Evidence

- **Escalation, answered:** the spec's Contact row has no field to record a merge. Options were hard delete or a new `merged_into_id` column. The owner chose hard delete (option A), which adds a DELETE grant on `contacts` only.
- **Schema tests** prove every enum check (including that `review` is no longer an action kind), the snooze, scheduled-kind, outreach-column and scope checks, every composite foreign key against a foreign user's row, the uniqueness rules, the GIN index, every grant (an interaction summary cannot be updated; interactions and recruiting actions cannot be deleted; `TRUNCATE` is denied) and the account-deletion cascade over all six tables.
- **Merge race:** a merge racing an edit of the merged contact, run 10 times (10 of 10): exactly one 200 and one 409 every time.
- **Wake job tests:** fires once; a stale version is ignored (including after a re-snooze); a completed or dismissed action is ignored; a second job for an already woken action is ignored; a missing action succeeds quietly. System-only supersede and restore work through the service and have no endpoint.
- **Upcaster:** a version 1 note payload row loads, shows in the timeline and upcasts to v2 with `interaction_id: null`, for every note event type.
- **Isolation:** every new route has a case in `test_isolation.py` (foreign ids 404, lists never leak, acting as B changes nothing of A's); body-borne foreign ids (interaction, action, rule, merge) are covered in `test_relationship_isolation.py`.
- **Stack** (`docker compose up --build -d`): `migrate` exited 0 (0006 to 0007), `/healthz` 200. A script created a synthetic user and session as owner and showed through the API: a duplicate address refused with `contact_email_taken`; Sam linked to a company and an opportunity; an interaction with `OUTREACH_SENT` returned the application's new version 2 and the timeline listed `INTERACTION` (linkedin) next to `OUTREACH_SENT`; a stale application version gave 409; `attend_interview` without a time gave 422 `due_at_required`; a snoozed action was woken by the worker (events `CREATED user`, `SNOOZED user`, `WOKEN system`, job `succeeded`); the other two actions were completed and dismissed; merging Alex into Sam moved the company and opportunity links, the interaction and all three actions to the survivor, kept both addresses, made the merged id 404, and a repeat merge gave `contact_already_merged`; a global and a company-scoped cooldown rule were created. After account deletion (202) every count was 0 for all new tables, `domain_events`, `applications`, `opportunities`, `companies` and `sessions`.
- **Live UI check:** pending the owner.

## Changes outside the expected file set

| File | Change | Reason |
| --- | --- | --- |
| `backend/app/db/models.py` | New enums and the six models | Mirror migration 0007 |
| `backend/app/applications/events.py` | `ApplicationNoted` v2 with `interaction_id`, `noted_v1_to_v2`, registrations at version 2 | Spec 5.1: application events reference an Interaction |
| `backend/app/applications/service.py` | `record_event(..., interaction_id=None)` | Pass the interaction into the payload |
| `backend/app/applications/timeline.py`, `schemas.py` | Optional `interaction_channel` and `interaction_direction` on timeline entries | Show interaction entries as plain text with channel and direction |
| `backend/app/main.py`, `backend/app/jobs/handlers.py` | Include the four routers, register the timeline sources and the `wake_action` handler | Wiring |
| `backend/tests/db/test_isolation.py` | New cases, seeds and assertions | Every new route needs a case |
| `frontend/src/app/Layout.tsx`, `router.tsx`, `routes/OpportunityDetail.tsx`, `routes/OpportunityWorkflow.tsx` | Nav links, routes, the relationship panels, interaction rows in the timeline | Brief section G |
| `frontend/src/app/Layout.test.tsx`, `routes/OpportunityDetail.test.tsx`, `routes/OpportunityWorkflow.test.tsx` | Expected nav links; the mock servers answer the two new list requests with empty lists | The opportunity page now also loads contacts and actions |
| `backend/openapi.json`, `frontend/src/api/schema.d.ts` | Regenerated | New routes and schemas |
| `README.md`, `docs/architecture/database.md`, `state-machines.md` | Updated | Brief section H |

## Important things I learned

- The spec's field lists differ from the brief in places (email `added_at` not `is_primary`; rules use `statement`, `rule_type`, `condition`, `active`; the opportunity link is unique per role; interactions have no `origin`). Reading the frozen spec first and following it avoided inventing columns.
- A merge with no merge field is a real design gap, not a coding detail. Hard-deleting the merged row works only because the history lives in the event, and that needs the DELETE grant on exactly one table.
- Without a `state_version`, `updated_at` makes a workable optimistic token, but both the edit and the merge must take the row lock first and treat a vanished row as a conflict, or the race gives a 404 on one side and a 409 on the other.
- A wake job is only safe if every change that is not a transition leaves `state_version` alone. Editing a snoozed action must not bump it, or the pending job would be ignored and the action would stay snoozed forever.
- A column-level grant (`UPDATE (contact_id)`) lets interactions stay history while still allowing a merge to re-point them. A test that tries to update `summary` proves it.
- `dict(result.tuples())` on a SQLAlchemy result is not a mapping of rows; the opportunity timeline returned 500 until a test across the new source caught it.
- Postgres JSONB containment (`@>`) with the GIN index gives the "one contact per address" lookup without a separate table, and an advisory lock per user closes the check-then-insert race.
- The structured logger drops fields that are not on its allow-list (`dropped_field_count` shows in the worker log), which is why the wake handler's log line carries no ids. That is safe, but it means the line is less useful than intended.

## Checks run and results

| Check | Result |
| --- | --- |
| `ruff check`, `ruff format --check`, `mypy` (strict, 212 files) | Pass |
| Full `pytest` with Postgres and `REQUIRE_DB_TESTS=1` | Pass: 1,292 tests collected, exit 0, one skipped (the symlink storage test that skips on this Windows host) |
| Merge-vs-edit race test, 10 runs | 10 of 10: one 200 and one 409 each time |
| Wake job, upcaster and isolation tests | Pass (inside the full run) |
| Migrations on an empty DB: upgrade, `alembic check`, downgrade base, upgrade | Pass; no drift |
| Frontend `npm run lint`, `typecheck`, `test`, `build` | Pass: 21 files, 145 tests |
| Regenerated `openapi.json` and `schema.d.ts` | No diff |
| Stack: migrate exit 0, `/healthz` 200, end-to-end script, deletion leaves no rows | Pass |
| Live UI check | Pending the owner |
| GitHub Actions (backend, frontend, secrets) | Pending the push |

## Deviations from the frozen spec

None. Where the brief and the spec differed, the spec was followed (see "Additions beyond the brief" and "Process deviations").

## Additions beyond the brief

- `GET /api/v1/contacts?opportunity_id=` for the opportunity page panel.
- `RECRUITING_ACTION_EDITED` event for title and due-time edits.
- Interaction timeline entries carry channel and direction as two optional fields.
- `conflict` handling by `updated_at` (`expected_updated_at`) on contact edit and merge, because the spec gives contacts no `state_version`.

## Process deviations

- The brief's field lists were overridden by the spec's (brief: "the spec wins"): email items without `is_primary`; rule fields `statement`, `rule_type`, `condition`, `active`; `contact_opportunities` unique per role; no `origin` on interactions; `contact_companies` kept unique per contact and company as the brief says.
- `outreach` actions cannot be created through the API in this task.
- The merge record follows the owner's answer to the escalation (hard delete).
- The Task 7 `ApplicationNoted` v1 rows were not migrated; they load through the upcaster, as the spec requires for immutable rows.

## Unresolved issues

- Spec 5.3 says the system creates "complete assessment" and "attend interview" actions from a confirmed event. It is not clear whether an event the user records by hand counts, or only a confirmed ReviewItem from Gmail. Nothing was built; please decide before Task 12 or 14. Supersede and restore likewise have no trigger.
- The wake handler's log line loses its fields to the logger allow-list.

## Git state

- Branch: `task-08-contacts-actions-rules`, from `main` at the merge of PR #6.
- Commits: brief; migration and models; payload v2; services and API; backend tests; OpenAPI and types; pages; docs; this report.
- PR: none opened (`gh` is not authenticated). Compare URL: https://github.com/BharathraajNagarajan/career-os/compare/main...task-08-contacts-actions-rules
- CI: not yet pushed.

## Recommendation

Approve once the live UI check passes and CI is green. The backend gates, the stack run and the frontend gates are clean; the one open design question (automatic action creation) does not block this task because it is deferred and documented.
