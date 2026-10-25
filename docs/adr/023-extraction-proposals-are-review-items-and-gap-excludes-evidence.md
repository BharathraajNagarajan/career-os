# ADR-023: Extraction proposals are review items, and a gap marker excludes confirmed evidence

- Status: Accepted
- Date: 2026-10-25
- Source: docs/spec/phase-0-spec.md (4.3.2, 5.4, 5.4a, INV-07, INV-08, INV-13, INV-14, INV-16, INV-17)

## Context

Spec 5.4a lists `Proposed` states and a `SKILL_PROPOSED` event for skills and claims, which could mean that extraction writes rows with `confirmation_status = proposed`. It also says the model never writes domain state and that a confirmed review item "runs one transaction: create or reuse the Skill, create a confirmed Claim". Two readings were possible, and Task 9 had to choose one before building the first producer.

Separately, 4.3.2 refuses to mark a gap while confirmed academic, project or professional evidence exists, and says the user "must reject or downgrade that evidence first". It does not say what happens when evidence is added to a skill that already carries a gap marker.

## Decision

- A resume extraction creates `ReviewItem`s only. No skill, claim, source or link row exists until the user confirms an item, and the confirm handler creates confirmed rows through the same commands a manual action uses. The `proposed` and `rejected` values stay in the schema for later producers; rejecting a review item is recorded on the item. `SKILL_PROPOSED` is not emitted because there is no skill to attach it to.
- A confirmed claim can be rejected by the user (`CLAIM_REJECTED`). 5.4a lists rejection only from `proposed`, but 4.3.2 requires the user to be able to "reject" confirmed evidence before marking a gap, so the command is allowed from `confirmed` as well.
- The gap rule is enforced in both directions. Creating or linking confirmed academic, project or professional evidence for a skill that is marked as a gap, or reclassifying a claim into one of those classes, is refused with 409 `gap_marked`. Learning evidence may still coexist with a gap. The user clears the gap first. A merge that brings such evidence into a gap-marked survivor clears the marker in the same transaction.
- The model's engagement type is kept only when it quotes text from the resume that contains a cue word for that type and sits near the statement. Everything else is `unspecified`.

## Alternatives considered

- Write `proposed` rows at extraction: simpler status handling, but it puts model output in the evidence tables before any user decision, makes "no rows until confirmed" untestable and invites readers that forget to filter by status (INV-07, INV-14).
- Allow evidence and a gap marker to coexist: avoids a refusal path but lets one skill show "Gap" and "Professional" at once, which contradicts the Skills page's single honest headline and INV-13.
- Auto-clear the gap when evidence is added: removes a decision from the user.

## Consequences

- Review is the only model-to-state path; extraction code cannot import the claim or skill writers (a test enforces this).
- A user who has marked a gap sees a plain refusal when confirming a proposal for that skill and must clear the gap first. Batch confirm reports it per item.
- Task 11's `skill_evidence` handler follows the same shape: create or reuse, create confirmed, link, write events.
