# ADR-022: Recruiting actions only from the user or a confirmed review

- Status: Accepted
- Date: 2026-10-08
- Source: docs/spec/phase-0-spec.md (5.3, INV-07, INV-14, INV-17)

## Context

Spec 5.3 says the system creates a RecruitingAction "from a confirmed event" (for example assessment received creates "complete assessment", interview scheduled creates "attend interview"). It did not say whether an application event the user records by hand counts as such an event. Task 8 built the actions without any automatic trigger and reported the question. The owner and the control chat have now decided it.

## Decision

- A manually recorded application event (for example `ASSESSMENT_RECEIVED`) never creates a RecruitingAction automatically.
- Phase 1A: the user creates the action explicitly. Home (Task 10) may offer a one-click suggestion, but creating the action still requires the user's confirmation.
- Phase 1B (Task 13): a confirmed Gmail ReviewItem may create the matching RecruitingAction as part of the confirmed operation, subject to deduplication and state rules.
- An action is never created from an unconfirmed email, a raw application event or model inference.
- Supersede and restore triggers stay deferred until the workflow that owns them exists.

## Alternatives considered

- Create actions from every recorded event: surprising side effects from a plain history entry, duplicates when the same fact is recorded and later confirmed from email, and it makes a user-entered note behave like a command.
- Create actions from model output or unconfirmed email: breaks INV-07 and INV-14 (the model never writes domain state; proposals are confirmed first).

## Consequences

- Creation has one explicit path in each phase, so the timeline of an action always has a user decision behind it.
- Task 10 and Task 13 each need a confirm step and a deduplication rule; the confirmed ReviewItem command is the only automatic creator.
- Users record an event and create its action as two steps until Home offers the shortcut.
