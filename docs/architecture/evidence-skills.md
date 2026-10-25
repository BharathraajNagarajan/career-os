# Evidence and the Skill Inventory

Spec references: 0A, 1.3 (INV-01, INV-02, INV-04, INV-07, INV-08, INV-13, INV-14, INV-16, INV-17, INV-18), 4.3, 4.3.1, 4.3.2, 5.4, 5.4a, 6.2c, 7A.4, 9, 14 (Task 9). ADR-008, ADR-015, ADR-016, ADR-017.

This module holds what the user can truthfully say about themselves. Four user-owned tables, one model call (resume extraction) and one rule above all: the model proposes, the user decides.

## The four tables (migration 0008)

| Table | What it is | Notes |
| --- | --- | --- |
| `skills` | One entry in the Skill Inventory | `canonical_name`, `normalized_key`, `aliases text[]`, `confirmation_status`, `user_marked_gap`, `gap_note`, `user_note`, `origin`, `merged_into_skill_id`, `llm_run_id`, `state_version`, `updated_at`. No evidence class: a skill has none of its own |
| `claims` | One citable statement | `statement`, `evidence_class`, `engagement_type`, `confirmation_status`, `start_date`, `end_date`, `organization_label`, `origin`, `llm_run_id`, `state_version`, `updated_at` |
| `evidence_sources` | Where a claim comes from | `source_type` is `resume`, `project_url`, `user_assertion` or `artifact`; a check makes the other columns match the type (a resume or artifact source has an artifact, a link has a URL, the user's own words are stored verbatim) |
| `claim_skills` | Claim to skill link | Unique per claim and skill |

Every table has `UNIQUE (user_id, id)` and every reference between them is a composite foreign key that includes `user_id`, so a cross-user link cannot be written even by a buggy query (INV-02). Every enum is a `CHECK`. `claims` has a check that ties `engagement_type` to the professional class: a professional claim must have one, any other claim must not.

`skills.llm_run_id` is not in the spec's field list; it follows the general convention in 4.1 that LLM-derived rows carry their run, and it is used when a skill is created by a confirmed extraction.

### Grants (least privilege)

| Table | `career_os_app` can | Why |
| --- | --- | --- |
| `skills` | SELECT, INSERT, and UPDATE on the editable columns only | `origin`, `llm_run_id` and `created_at` are provenance and cannot change. No DELETE: a merged skill stays as a redirect |
| `claims` | SELECT, INSERT, and UPDATE on statement, class, engagement type, status, dates, organization, version and `updated_at` only | Provenance (`origin`, `llm_run_id`) is immutable. No DELETE: a claim is rejected, not erased |
| `evidence_sources` | SELECT, INSERT | A source is a record of where something came from. It is never edited or removed |
| `claim_skills` | SELECT, INSERT, DELETE, and UPDATE on `skill_id` | Unlinking is legitimate; `skill_id` moves only so a merge can re-point links |

Tests prove each denied statement. Account deletion cascades from `users`.

## Evidence classes and engagement types

A claim has exactly one class: `professional`, `academic_research`, `project` or `learning`. A professional claim also has an engagement type: `full_time`, `part_time`, `contract`, `internship` or `unspecified`. An internship is professional evidence with its own engagement type, never "full-time" (INV-16). Wherever the UI or the API describes a professional claim it uses the pair; the Skills page labels it "Professional (Internship)" next to "Professional (Full-time)", and the category filter can narrow professional evidence to one engagement type. `unspecified` is shown as "Type not specified" and is never described as full-time.

Only the user sets or changes a class or engagement type (INV-08). The model's output is a proposal.

## Derived skill assessment (4.3.2)

Nothing about a skill's strength is stored. `app/evidence/assessment.py` computes it on every read from the skill's linked, non-rejected claims:

- **Badges:** one per (class, engagement type) present, each marked confirmed or unverified. A skill can show Professional, Academic / Research and Project at once.
- **Categories:** every class present, plus `gap` when the user marked one, plus `not_recorded` when there are no claims and no marker. The Skills filters use these.
- **Headline:** the strongest confirmed badge in the order professional (full-time, part-time, contract) > professional (internship) > professional (type not specified) > academic / research > project > learning. The spec orders the first five and leaves unspecified professional evidence out; it is ranked after internship so it never outranks counted employment. The headline is `gap` when the user marked a gap and has nothing stronger than learning evidence.
- **Recency:** the latest end date among claims, and whether any claim is open-ended (a start date and no end date).
- **Resume exposure:** resumes that "state" the skill (a claim linked to it cites the resume) and resumes whose extracted text "mentions" its name or an alias. Mentions use Postgres full-text search (`simple` configuration, phrase match) computed on request, so it is token-based: a name made only of punctuation matches nothing, and `C++` matches the token `c`.

### Not recorded is not a Gap (INV-13)

A skill with no evidence and no marker is **Not recorded**: unknown, not negative. Only the user creates a gap marker, and `mark_gap` is refused (409 `gap_refused_evidence_exists`) while a confirmed professional, academic / research or project claim is linked. Learning evidence may coexist with a gap ("learning, not yet able to claim it"). To make the rule hold in both directions the same check runs the other way: creating or linking evidence of a blocking class to a skill that is marked as a gap is refused (409 `gap_marked`), and so is a class change to one. The user clears the gap first. A merge that brings blocking evidence into a gap-marked survivor clears that marker in the same transaction and writes `SKILL_GAP_CLEARED`.

## Changing a classification

`POST /api/v1/claims/{id}/classification` requires `confirm_change: true` (422 `confirmation_required` otherwise), an engagement type when the class is professional, and the claim's `expected_state_version`. It writes `EVIDENCE_CLASS_CHANGED` with the old and new class and engagement type. The UI shows a dialog naming both values and only then sends the request. In the Review page, Edit + Confirm on a proposed claim may change the class or engagement type, but only with `confirm_class_change: true` in the payload (the handler compares against the stored proposal and returns 422 `confirmation_required` otherwise); the confirmed claim is then followed by the same event with the proposed values as "old".

## Merging skills

`POST /api/v1/skills/{survivor}/merge` takes both skills' versions. In one transaction: the claim links of the merged skill move to the survivor (a link both skills had is dropped), the survivor absorbs the merged skill's name and aliases as aliases, the merged row gets `merged_into_skill_id` and stays as a redirect, any gap marker on it is cleared, both `updated_at` values move, and `SKILL_MERGED` is written. Reading a merged skill returns the redirect; creating a claim with a merged skill's id links the survivor. Names and aliases are checked against every other non-merged skill under an advisory lock for the user (409 `skill_exists`); the database enforces the canonical name with a partial unique index and the service enforces aliases, because an alias list cannot carry a unique constraint across rows.

## Events

All events are in `domain_events` with typed payloads at `schema_version` 1 that carry ids and enum values only, never text.

| Event | Aggregate | Written when |
| --- | --- | --- |
| `SKILL_ADDED` | skill | The user adds a skill |
| `SKILL_CONFIRMED` | skill | A confirmed review item creates a skill |
| `SKILL_MERGED` | skill (the survivor) | A merge |
| `SKILL_GAP_MARKED`, `SKILL_GAP_CLEARED` | skill | The user marks or clears a gap (also when a merge clears one) |
| `CLAIM_CONFIRMED` | claim | A claim is created, by the user or by a confirmed review item (`origin` says which) |
| `CLAIM_EDITED` | claim | Statement, dates or organization change; also when a skill is linked or unlinked or a source is added (the `fields` list says what) |
| `CLAIM_REJECTED` | claim | The user rejects evidence |
| `EVIDENCE_CLASS_CHANGED` | claim | Class or engagement type changed, with old and new values |

`SKILL_PROPOSED` and the "proposed" states exist in the spec's table. Here the proposal is the `ReviewItem`, so no skill or claim row exists until the user confirms; the tables keep the `proposed` and `rejected` values for later producers. Rejecting a review item is recorded on the item itself.

## Staleness (6.2c)

Any claim or skill change bumps `skills.updated_at` for every affected skill in the same transaction: creating, editing, reclassifying or rejecting a claim, adding a source, linking or unlinking a skill, editing a skill, marking or clearing a gap, merging. That timestamp is what Task 11 compares against an Evaluation's `created_at`. Nothing here starts model work (INV-17).

## Resume extraction

```
POST /api/v1/resumes/{id}/extract-evidence   (or the upload checkbox)
   │  202; enqueues job extract_evidence, unique per resume
   ▼
worker: extract_evidence
   │  re-resolve resume and artifact through user-scoped repositories (INV-18)
   │  reuse a settled llm_runs row for this artifact if one exists, else
   │  ModelGateway.structured(evidence.extract v1, purpose extract_resume, fast tier)
   ▼
deterministic cleaning (app/evidence/extraction.py)
   ▼
ReviewItems: claim and skill proposals, linked to the llm_run and the resume
   ▼ the user confirms, edits or rejects (single or batch)
review handlers → the same commands a manual action uses
```

**Trigger and states.** Extraction runs only on the user's explicit request: the button on a resume, or the checkbox at upload, which enqueues the same job. Nothing runs automatically (INV-17). The status is derived from the job rows, with no new column: `not_requested`, `pending`, `succeeded` or `failed` (with the error code). One extraction per resume unless the previous one failed; a request while one is pending or done is refused (409), as is one for an archived, still-unparsed or unreadable resume. A job started from the upload checkbox before parsing finishes retries with the queue's normal backoff until the text exists.

**Failures.** A model failure (budget refusal `llm_budget_exhausted`, invalid output twice `llm_output_invalid`, provider error) raises `PermanentJobError`: the job is marked failed with that code and is not retried automatically. The user can request it again. A queue retry after the model already answered reuses the settled run instead of calling again; stored output that no longer validates is ignored and the model is called afresh.

**Cleaning (what the model's output must survive).**

- A claim statement must appear in the resume text (whitespace-normalized substring). Otherwise it is dropped and counted. Duplicates collapse.
- The evidence class must be one of the four. The prompt tells the model to choose `learning` when unsure.
- The engagement type is forced to `unspecified` unless the model cites a quote that (a) is in the resume text, (b) contains a cue word for the claimed type ("full-time", "part-time", "contract/freelance", "intern/internship/co-op"), and (c) sits within 300 characters of the statement. Non-professional claims carry none. This is stricter than the brief's "cited span is in the text" rule.
- Organization is kept only if it appears in the text; dates are parsed from `YYYY`, `YYYY-MM` or `YYYY-MM-DD`, ignored if invalid, implausible or out of order.
- Skill names (per claim and standalone) must appear in the text, are normalized and de-duplicated, and a standalone skill that already exists (by name or alias) creates no proposal. Claims reference skills by name and resolve them when confirmed, so a skill confirmed in the same batch is reused, not duplicated.
- Counts are capped by `EVIDENCE_MAX_CLAIMS` and `EVIDENCE_MAX_SKILLS`.
- Confidence is clamped to 0 to 1. Rationale text is stored and shown as plain text.

**The resume text is the one untrusted variable.** It is wrapped as `<untrusted_content label="resume">`, the system prompt carries the standing notice, and the output is validated by schema and then by the rules above, so an instruction hidden in a resume cannot change the output format or raise a class. A structural test (`test_resume_extraction_can_only_create_review_items`) fails if the extraction module imports the claim or skill models or any command that writes them.

**Logging.** Only ids, counts and error codes: never resume text, statements, skill names, rationales or model output.

## Review handlers: the only model-to-state path

`app/evidence/review_handlers.py` registers the first production handlers (`app/review_registry.py` builds the registry for the API and the worker):

- `claim`: re-resolve the resume (409 `target_missing` if gone), compare the confirmed payload with the stored proposal (class changes need the explicit flag), create or reuse each named skill, create a confirmed claim with a `resume` source, link, bump the skills, write `CLAIM_CONFIRMED` (and `EVIDENCE_CLASS_CHANGED` when the user changed the class).
- `skill`: create the skill, or reuse an existing one, and write `SKILL_CONFIRMED`.

Both call the same `app/evidence/commands.py` functions the manual API calls. A handler never commits, so a failure (a gap-marked skill, a missing resume) rolls the whole item back and leaves it pending.

**Batch confirm.** `POST /api/v1/review-items/batch-confirm` takes up to 100 `{id, expected_state_version}` entries and runs the normal confirm for each in its own transaction. The response lists every item as `ok` or with an `error_code` (`conflict`, `not_found`, `invalid_transition`, `gap_marked`, ...). A failure never undoes another item's success. Another user's id reports `not_found`, the same as a missing one.

## API summary

Skills: `GET/POST /skills`, `GET/PATCH /skills/{id}`, `POST /skills/{id}/merge`, `/mark-gap`, `/clear-gap`. Claims: `GET/POST /claims`, `GET/PATCH /claims/{id}`, `POST /claims/{id}/classification`, `/reject`, `/sources`, `POST /claims/{id}/skills`, `DELETE /claims/{id}/skills/{skill_id}`. Resumes: `POST /resumes/{id}/extract-evidence`. Review: `POST /review-items/batch-confirm`. All require a session, mutations require the CSRF header, foreign ids return 404, and every route has an isolation case.

## What Task 11 will consume

Skills with their derived assessment (the same functions), claims with class and engagement type, `skills.updated_at` for staleness, and `ReviewHandlerRegistry` for the `skill_evidence` proposal type (the `skill_evidence` handler itself, the chat that produces it and the Evaluation are Task 11).

## Deferred

- Chat-produced proposals and the `skill_evidence` handler (Task 11); `message_id` on a source is stored but nothing sets it yet.
- Confirming or rejecting a `proposed` claim or skill row, and rejecting a confirmed skill: no producer creates proposed rows, so these commands are not built. A confirmed claim can be rejected, which is how the user clears evidence before marking a gap.
- Deleting a claim, source or skill (history is kept by design).
- Proficiency levels, endorsements, taxonomies (excluded by 7A.4).
- Per-page locators for resume sources.
