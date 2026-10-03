# State machines: opportunity decisions, applications, recruiting actions

Spec references: 0A, 1.3 (INV-03, INV-04, INV-07, INV-14, INV-17, INV-18), 2.1, 4.1, 4.5, 5 (5.1, 5.2, 5.3, 5.5), 9, 11, 14 (Task 7). Table: `applications` (migration 0006; see [database.md](database.md)). Code: `backend/app/state_machines/` (pure), `backend/app/opportunities/decisions.py`, `backend/app/applications/` (service, repository, timeline, router).

Every state machine is a pure function `(current state, command) → events | typed error` with no database and no I/O (spec 5.5). Services load state, call the function, then write the state change and its events **in one transaction**. A test (`test_state_machine_modules_stay_pure`) fails if a state-machine module imports anything beyond the standard library and the enums in `app.db.models`.

No model call exists anywhere in this task (INV-07, INV-17).

## Opportunity versus Application

An **Opportunity** is a posting you may act on and exists whether or not you apply. An **Application** is the fact that you applied to one Opportunity (0A); its stage is not a status on the Opportunity. After Apply the Opportunity stays `applied` forever, and everything that happens next lives on the Application's events.

## The three machines

### Opportunity (spec 5.2, latest revision)

Commands: `save`, `skip`, `apply`, `close`. Any pair not listed is refused with `409 invalid_transition`; nothing is a silent no-op.

| From | save | skip | apply | close |
| --- | --- | --- | --- | --- |
| new | saved | skipped | applied | closed |
| saved | refused | skipped | applied | closed |
| skipped | saved | refused | applied | closed |
| closed | refused | refused | applied | refused |
| applied | refused | refused | refused | refused |

Each transition writes one `OPPORTUNITY_DECIDED` event (payload: `decision`, `from_status`, `to_status`, optional `reason` of at most 500 characters). Apply additionally writes `APPLICATION_SUBMITTED` on the new application. Decisions change `status` and `state_version` only; they never move `content_updated_at`, so they do not make an Evaluation stale (6.2c). `allowed_actions` on every opportunity response is computed from this table, so the UI never copies the rules.

After a terminal application the Opportunity cannot be applied to again (spec 5.2: "Applied stays Applied"). Correcting a mistaken terminal event is Reopen, not a second Apply. The partial unique index below still allows a second application row for an opportunity once the first is terminal, which is the shape a confirmed Gmail ReviewItem needs later.

### Application (spec 5.1)

The materialized `stage` and `is_terminal` columns are a cache of a projection of the application's events. They are recomputed from **all** the events on every command, in the same transaction, so history and state cannot disagree.

Stages: `applied`, `assessment`, `interviewing`, `offer` (active) and `rejected`, `withdrawn`, `accepted`, `declined`, `no_response` (terminal). Active stages move in any direction.

| Event type | Stage effect | Who may record it |
| --- | --- | --- |
| APPLICATION_SUBMITTED | applied | Apply command only |
| ASSESSMENT_RECEIVED, ASSESSMENT_COMPLETED | assessment | user, system, gmail |
| INTERVIEW_REQUESTED, INTERVIEW_SCHEDULED, INTERVIEW_COMPLETED | interviewing | user, system, gmail |
| OFFER_RECEIVED | offer | user, system, gmail |
| REJECTED | rejected (terminal) | user, system, gmail |
| WITHDRAWN, OFFER_ACCEPTED, OFFER_DECLINED | withdrawn, accepted, declined (terminal) | user only |
| MARKED_NO_RESPONSE | no_response (terminal) | user only; the system never applies it |
| APPLICATION_ACKNOWLEDGED, CONNECTION_REQUEST_SENT, CONNECTION_ACCEPTED, OUTREACH_SENT, FOLLOWUP_SENT, RECRUITER_CONTACTED, CONTACT_REPLIED, NOTE_ADDED | none | user, system, gmail |
| APPLICATION_REOPENED | recomputes (below) | `reopen` command only, user only |
| EVENT_VOIDED | removes the target from the projection | `void` command only, user only |

The "user only" column comes from spec 5.1; the brief only called out `MARKED_NO_RESPONSE`, and the spec is stricter, so the spec wins.

Commands and their refusals (`application_command_check`):

- **record_event** `{event_type, occurred_at, note?}`: `APPLICATION_SUBMITTED`, `APPLICATION_REOPENED` and `EVENT_VOIDED` are refused with `422 event_type_not_allowed`. A non-user actor recording a user-only type gets `actor_not_allowed`. Recording a terminal event while the application is already terminal is `409 invalid_transition` (void or reopen first). Non-terminal events, including notes, may still be recorded on a terminal application: they are history and count again after a reopen. A terminal event dated before the latest reopen would be ignored by the projection, so it is refused with `409 terminal_before_reopen` rather than silently dropped.
- **void_event** `{event_id, reason?}`: `409 cannot_void` for `APPLICATION_SUBMITTED`, for an `EVENT_VOIDED`, and for an event that is not on this application (including another aggregate's event); `409 already_voided` for an event already voided. A foreign user's event id is `404` because it is re-resolved through the owner-scoped repository first (INV-18). A reopen can be voided.
- **reopen** `{note?}`: `409 not_terminal` unless the projection is terminal.

`occurred_at` may be backdated without limit and may be at most 5 minutes ahead of the **database** clock (`422 occurred_at_in_future`, which absorbs browser clock drift). It must carry a timezone.

### RecruitingAction (spec 5.3): pure function only

`recruiting_action_transition(status, command, actor, now, until?)` and its tests exist so Task 8 can use it. There is no table, no API and no persistence in this task.

| From | snooze | wake | complete | dismiss | supersede | restore |
| --- | --- | --- | --- | --- | --- | --- |
| open | snoozed (needs a future `until`) | refused | done | dismissed | superseded | refused |
| snoozed | refused | open | done | dismissed | superseded | refused |
| done, dismissed | refused | refused | refused | refused | refused | refused |
| superseded | refused | refused | refused | refused | refused | open |

`wake` (the scheduler), `supersede` and `restore` are system-only; a user actor gets `actor_not_allowed`. A snooze with no `until`, or one that is not after `now`, is `snooze_not_in_future`.

## The projection (`application_projection`)

Events are ordered by `(occurred_at, recorded_at, id)`:

- `occurred_at` is when it happened in the world and is what the user edits when backdating.
- `recorded_at` is when Career OS learned it (database clock) and breaks ties between events that happened at the same instant.
- `id` (UUIDv7) breaks any remaining tie, so the order is deterministic and the result never depends on insertion or read order.

Rules:

1. Drop every `EVENT_VOIDED` event and every event one of them points at. Voiding never deletes (INV-04); the voided row stays in the table and in the timeline, marked.
2. Find the latest remaining `APPLICATION_REOPENED`. Terminal events ordered at or before it are ignored.
3. Walk the remaining stage-bearing events in order. Each sets the stage; the first terminal one **freezes** the stage and later events are ignored.
4. If nothing bears a stage the stage is `applied`.

Worked examples (all in `tests/test_state_machines.py`):

- **Backdated event.** Submitted on day 0, `INTERVIEW_SCHEDULED` on day 10, then `ASSESSMENT_RECEIVED` recorded later but dated day 3. Ordering by `occurred_at` puts the assessment before the interview, so the stage stays `interviewing`.
- **Voided terminal event.** `SUBMITTED`, `INTERVIEW_SCHEDULED` (day 1), `REJECTED` (day 3): stage `rejected`, terminal. Void the rejection: it leaves the projection and the stage returns to `interviewing`, not terminal.
- **Reopen.** `SUBMITTED`, `INTERVIEW_SCHEDULED`, `REJECTED`, then `APPLICATION_REOPENED`: the rejection is at or before the reopen so it is ignored, and the stage is recomputed from what remains, `interviewing`. With only `SUBMITTED` and `WITHDRAWN` before the reopen the result is `applied`. Events recorded after the reopen count normally, including a new terminal event dated after it. Voiding the reopen puts the rejection back in force.

An event dated before the submission is still ordered before it, so a stage event backdated to before `applied_at` is overridden by the submission (the stage reads `applied`). That follows directly from "latest stage-bearing event by `occurred_at`"; the UI date inputs do not stop it.

The reopen event's own `occurred_at` is the database clock, raised to the latest event time already on the application, so a reopen always sorts after the terminal event it clears even when that event was dated a few minutes ahead.

## The single ordered timeline

`GET /api/v1/opportunities/{id}/timeline` merges every source for one opportunity into one list ordered by `(occurred_at, recorded_at, id)`. Today there is one source, `domain_event_source`: the opportunity's own events (ingested, extracted, edited, priority changed, decided) plus the events of each of its applications. `TIMELINE_SOURCES` in `app/applications/timeline.py` is a list of functions `(session, user_id, opportunity_id) → entries`; Task 8 adds interactions and recruiting actions by appending a source, with no change to the merge or the endpoint.

Each entry: `id`, `aggregate_type`, `aggregate_id`, `event_type`, `occurred_at`, `recorded_at`, `actor`, `voided` (a later `EVENT_VOIDED` targets it), `voids_event_id`, `note` (the note or void reason, plain text), and `voidable` from the pure function. Voided entries stay in the list. Opportunity-aggregate entries are never voidable.

## Concurrency guards

- **Optimistic concurrency.** Every command carries `expected_state_version`. The service locks the row (`SELECT … FOR UPDATE`), compares the version, and the write goes through `update_versioned`, so a stale version is `409 conflict` before anything else is evaluated and a lost update is impossible.
- **Two applies, one application.** Two concurrent `apply` requests both lock the same opportunity row; the second waits, then sees a newer version and gets `409 conflict`. The partial unique index `uq_applications_open_per_opportunity` on `(user_id, opportunity_id) WHERE NOT is_terminal` is the second guard for any path that does not hold the opportunity lock. A threaded test against real Postgres proves exactly one application and one 409, and the schema test proves the index rejects a second open application directly.
- **Atomic multi-aggregate command.** Apply updates the opportunity, inserts the application and appends two events (`OPPORTUNITY_DECIDED` and `APPLICATION_SUBMITTED`, sharing one `correlation_id` and one `occurred_at`) in a single transaction; any refusal (foreign or archived resume, future date, invalid transition) rolls all of it back.
- A foreign or unknown id is `404 not_found`, never 403.

## Hook for Task 13 (review handlers)

Every command (`DecisionService.decide`, `DecisionService.apply`, `ApplicationService.record_event`, `void_event`, `reopen`) takes `actor` (`user` by default) and `source_ref_id` (default none), which are written onto the events. They also take `commit` (default true). A review handler for `create_application` or `application_event` will call the same method inside the review transaction with `actor=Actor.GMAIL`, the external reference as `source_ref_id` and `commit=False`, so confirming a proposal runs exactly the command a manual action runs. The API does not expose `actor` or `source_ref_id`. No handler is registered in this task.

## Logging

Notes and reasons are stored in the event payload and never logged (INV-01). Logs carry ids, event types, stages and error codes only; a test asserts a note and a reason never reach the log output.

## Deferred

- Persisting RecruitingActions, contacts and interactions: Task 8 (only the pure transition function exists now).
- Review handlers for `create_application` and `application_event`, and Gmail as an event source: Task 13.
- Design of the Application panel and timeline: Task 10 (the UI here is deliberately minimal).
