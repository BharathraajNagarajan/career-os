# Contacts, interactions, recruiting actions and strategy rules

Spec references: 0A, 1.3 (INV-01, INV-02, INV-04, INV-07, INV-14, INV-17, INV-18), 4.1, 4.5, 4.6, 4.7, 4.9, 4.10, 5.1, 5.3, 5.5, 9, 11, 14 (Task 8). Tables: migration 0007 (see [database.md](database.md)). Code: `backend/app/contacts/`, `interactions/`, `actions/`, `strategy/`. The pure RecruitingAction machine is in `backend/app/state_machines/recruiting_action.py` ([state-machines.md](state-machines.md)).

## Tables

All six are user-owned: `UNIQUE (user_id, id)` and a composite foreign key for every reference (INV-02), so a cross-user link cannot be written even by a buggy query. Every enum is `text` with a `CHECK`.

| Table | Purpose | Notes |
| --- | --- | --- |
| `contacts` | A person in the user's network | `full_name`, `emails` (typed JSONB), `linkedin_url`, `headline`, `notes`, `source` (`manual`, `gmail`, `import`). GIN index on `emails`. No `state_version` (the spec lists none) |
| `contact_companies` | Contact to company | `relation` (`employee`, `recruiter`, `former_employee`, `agency_recruiter`, `other`), `title`, `is_current`. Unique per `(user, contact, company)` |
| `contact_opportunities` | Contact to opportunity | `role` (`recruiter`, `hiring_manager`, `referrer`, `interviewer`, `team_member`, `other`). Unique per `(user, contact, opportunity, role)` as the spec says |
| `interactions` | One communication, any channel | `channel` (`email`, `linkedin`, `phone`, `in_person`, `other`), `direction` (`inbound`, `outbound`), `occurred_at`, `summary` (at most 2,000 characters), optional `company_id`, `opportunity_id`, `application_id`, `artifact_id`, `external_ref_id` (no FK until Task 12) |
| `recruiting_actions` | To-do, follow-up, scheduled commitment | `kind`, `title`, `due_at`, `status`, `snoozed_until`, `sequence_no`, links, `origin`, `state_version`, and the five nullable outreach columns Task 14 fills |
| `strategy_rules` | User-authored decision rule | `scope` (`global`, `company`, `lane`), `company_id`, `lane_id`, `statement`, `rule_type`, `condition`, `active` |

Checks worth knowing: `snoozed_until` is set exactly when `status = 'snoozed'`; `attend_interview` and `complete_assessment` must have `due_at`; the outreach columns must be null unless `kind = 'outreach'`; a rule's target must match its scope (global has none, company has only `company_id`, lane has only `lane_id`).

Grants to `career_os_app`: `contacts` and `recruiting_actions` SELECT, INSERT, UPDATE (plus DELETE on `contacts`, see Merge). `interactions` SELECT, INSERT and `UPDATE (contact_id)` only: interactions are history, the summary cannot change, and the one column update exists so a merge can re-point them. `contact_companies`, `contact_opportunities` and `strategy_rules` also allow DELETE (removing a link or a rule is legitimate). Account deletion cascades from `users`.

## Contact emails

`contacts.emails` is `{schema_version: 1, items: [{address, source, added_at}]}`, validated by the Pydantic model `ContactEmails` (`app/contacts/emails.py`). The per-address `source` is `manual`, `gmail` or `provider` (the spec's list). This task only writes `manual`. Addresses are trimmed, lowercased, validated and deduplicated.

The spec says the service enforces one contact per address per user inside the write transaction. The service takes a per-user transaction advisory lock, then looks up each new address with a JSONB containment query (served by the GIN index); a clash is `409 contact_email_taken`. Two concurrent creates of the same address yield one contact and one 409 (tested). `PATCH` takes the desired list of addresses: retained addresses keep their original source and `added_at`, new ones are `manual`.

Contacts have no `state_version`, so optimistic concurrency uses `updated_at`: `PATCH` and `merge` carry the `updated_at` the client loaded, compared under a row lock. A stale value is `409 conflict`.

## Merge

`POST /api/v1/contacts/{survivor_id}/merge` runs in one transaction:

1. Both contacts are resolved as the caller's (foreign is 404), then locked `FOR UPDATE` in id order; both `updated_at` values must match.
2. Emails are unioned. If the same address appears on both, the survivor's entry (and source) wins. Empty `linkedin_url`, `headline` and `notes` on the survivor are filled from the merged contact.
3. Company and opportunity links are re-pointed; a link the survivor already has is dropped from the merged side first. Interactions and recruiting actions are re-pointed.
4. `CONTACT_MERGED` (survivor id, merged id, counts) is written on the survivor's aggregate.
5. The merged contact row is deleted.

The Contact row in spec 4.6 has no field to record a merge, and the owner chose to hard-delete the merged row rather than add a column (spec 4.1: user deletion is hard delete; spec 4.4: merge "records a merge event"). History is the event. A `GET` for the merged id is `404`. A merge into itself is `409 cannot_merge_into_self`. A merge involving a contact that an earlier `CONTACT_MERGED` event shows was merged away is `409 contact_already_merged`.

A merge racing an edit of the merged contact: both take the row lock. If the edit wins, the merge sees a changed `updated_at` and gets 409. If the merge wins, the edit finds the row gone under its lock and also gets 409. A threaded test runs the race ten times: always one 200 and one 409.

## Interactions and application events

`POST /api/v1/interactions` records an interaction for a contact, optionally tied to an opportunity or application (an application fills in its opportunity and the opportunity's company; a mismatch is 422). `occurred_at` may be backdated and at most 5 minutes in the future. There is no edit and no delete: correction is a new record.

Interactions have no aggregate type in the spec, so they write no event of their own. Spec 4.6/5.1: an interaction linked to an application also writes a referencing application event. When `application_event_type` is given, `ApplicationService.record_event` runs in the same transaction with the interaction's `occurred_at`. Only six non-stage types are accepted (`OUTREACH_SENT`, `FOLLOWUP_SENT`, `RECRUITER_CONTACTED`, `CONTACT_REPLIED`, `CONNECTION_REQUEST_SENT`, `CONNECTION_ACCEPTED`); stage-bearing types are 422. The application's `expected_application_state_version` is required; a stale one is `409 conflict` and nothing is written (tested: no interaction row, no event).

To reference the interaction, the application note payload moved to `schema_version` 2 with an optional `interaction_id`. The v1 to v2 upcaster adds `interaction_id: null`. Stored v1 rows are never rewritten; they load through the upcaster (tested against a real v1 row and for every note event type).

## RecruitingAction lifecycle

Every transition goes through `recruiting_action_transition`; the service never duplicates its rules. The API exposes create, edit, snooze, complete and dismiss. `wake`, `supersede` and `restore` are system-only and have no endpoint. Each transition appends one event (`RECRUITING_ACTION_CREATED`, `_SNOOZED`, `_WOKEN`, `_COMPLETED`, `_DISMISSED`, `_SUPERSEDED`, `_RESTORED`, plus `_EDITED` for title or due-time edits) in the same transaction as the state change, with the actor. Payloads carry ids, statuses and field names, never titles.

Creating: `outreach` is refused in this task (it belongs to Task 14's accept-a-recommendation flow). `attend_interview` and `complete_assessment` require `due_at`. Origin is `user`. `sequence_no` counts `follow_up` actions per application (or opportunity, or contact) so the n-th follow-up is numbered; every other kind is 1.

Every response carries `allowed_actions`, computed by calling the pure function for the user actor, so the UI offers exactly what the machine allows.

Editing (`PATCH`) changes `title` and `due_at` on open or snoozed actions only, under the row lock. It does not bump `state_version`: an edit is not a state change, and a bump would invalidate the pending wake job and leave a snoozed action stuck.

### Wake job

Snoozing enqueues a system `wake_action` job with `run_after = until` and `unique_key = wake_action:<id>:<state_version>`, in the same transaction. When the worker claims it, the handler re-resolves the action through the owner-scoped repository (INV-18) and applies the system `wake` transition only if the action is still snoozed at the same `state_version`. Otherwise it does nothing and the job still succeeds. Tests cover: fires once; a stale version is ignored (including a re-snooze, which queues a newer job); a completed or dismissed action is ignored; a second job for an already woken action is ignored; a missing action is ignored. No polling loop and no model call.

## Strategy rules

`GET/POST/PATCH/DELETE /api/v1/strategy-rules`. The scope target is re-resolved as the caller's company or lane (foreign is 404); a scope that does not match its target is 422 (and the database check backs it). `PATCH` changes `statement`, `rule_type`, `condition` and `active`; the scope is fixed at creation. `condition` is optional typed JSONB: `{schema_version: 1, kind: application_cooldown | outreach_cooldown, days: 1..365}`. Rules are stored and listed only. Tasks 11 and 14 consume them.

## Timeline sources

`TIMELINE_SOURCES` gained two sources, registered at app start, without touching the merge or the endpoint: interactions linked to the opportunity or its applications (shown as `INTERACTION` with channel, direction and the summary as plain text; never voidable) and recruiting-action events for actions linked to the opportunity or its applications (the action's title is shown as the note).

## Extension boundary (spec 4.10)

Enums stay `text` with `CHECK` lists, all cross-links are nullable and interactions never assume email, so the later Events module is additive: a `networking_events` table, a nullable `networking_event_id` on interactions and recruiting actions, `event` added to the `contacts.source` check, and a `REFERRAL_SUBMITTED` application event type. People met later fit as a contact, an `in_person` interaction and a follow-up action linked to that contact.

## Deferred

Gmail matching and contact discovery (7.5), enrichment providers, outreach recommendation and drafting (Task 14, including the `outreach` kind), evaluating strategy rules (Tasks 11 and 14), and any automatic creation, supersede or restore of actions. Action creation is decided by [ADR 022](../adr/022-recruiting-actions-only-from-user-or-confirmed-review.md): a manually recorded application event never creates a RecruitingAction automatically. In Phase 1A the user creates the action explicitly (Home, Task 10, may offer a one-click suggestion that still needs the user's confirmation). In Phase 1B (Task 13) a confirmed Gmail ReviewItem may create the matching action as part of the confirmed operation, with deduplication and state rules; never from an unconfirmed email, a raw application event or model inference. Supersede and restore triggers stay deferred until their owning workflow exists.
