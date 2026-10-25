# Task 9 checkpoint: evidence and the Skill Inventory

Branch `task-09-evidence-skills`, built on `main` after the Task 8 merge. Design notes: [evidence-skills.md](../architecture/evidence-skills.md). Decision record: [ADR-023](../adr/023-extraction-proposals-are-review-items-and-gap-excludes-evidence.md).

## What was implemented (mapped to the acceptance criteria)

| Acceptance criterion (spec section 14) | Implementation |
| --- | --- |
| Resume extraction (explicit on upload) proposes Claims with class and engagement type (`unspecified` unless stated) and Skills, all as ReviewItems | `POST /api/v1/resumes/{id}/extract-evidence` and an upload checkbox enqueue the same `extract_evidence` job; prompt `evidence.extract` v1 (purpose `extract_resume`, fast tier, resume text the only untrusted variable); the output is cleaned (statements must appear in the resume, engagement type forced to `unspecified` without a supporting quote, counts capped) and becomes `claim` and `skill` review items linked to the `llm_runs` row and the resume. No skill, claim, source or link row exists until an item is confirmed |
| Review UI with batch confirm | Review page groups proposals by source resume, per-item checkboxes and "Select all", "Confirm selected (N)" calling `POST /review-items/batch-confirm` (each item its own transaction, per-item result); claim cards read as evidence, not JSON; Edit and confirm form for claims |
| Skills CRUD, aliases, merge with redirect | `skills` table; add, edit name, aliases and note, list with search and filters, detail; merge moves claim links, absorbs names as aliases, keeps the merged row as a redirect (`merged_into_skill_id`), writes `SKILL_MERGED`; creating a claim with a merged id links the survivor |
| Gap marking with the refusal rule | `mark-gap` / `clear-gap`; refused with 409 `gap_refused_evidence_exists` while confirmed professional, academic or project evidence is linked; learning may coexist; the rule also runs the other way (409 `gap_marked`) |
| Class and engagement-type change with explicit confirmation and events | `POST /claims/{id}/classification` needs `confirm_change: true`; writes `EVIDENCE_CLASS_CHANGED` with old and new values; the UI shows a dialog naming both; in Review the same flag is required in an edited payload that changes the class (`confirm_class_change`) |
| Derived skill category and badges | Computed on read (`assessment.py`): badges per (class, engagement type), categories, headline, recency; nothing stored; "Not recorded" and "Gap" are separate and never conflated |
| Resume exposure | "Stated" (claim cites the resume) and "mentioned" (Postgres full-text search of the resume text for the name or an alias) on the list and detail |
| Skills page with filters | Skills list (search, category incl. Gap and Not recorded, engagement type for professional), detail with claims and sources, add evidence, change classification, merge, gap, aliases and note; Evidence page and detail for claims |
| Model cannot set class or engagement type (test) | Cleaning rules plus a structural test that the extraction module imports no claim or skill model and no writing command; the only writer of evidence from extraction is the review handler |
| INV-13 and INV-16 tests | Not recorded is never a gap (list, filters, detail); gap refusal parametrized over three classes; internship distinct from full-time in badges, headline and filter |

Also: settings `EVIDENCE_EXTRACTION_MAX_OUTPUT_TOKENS`, `EVIDENCE_MAX_CLAIMS`, `EVIDENCE_MAX_SKILLS` (Compose, `.env.example`, README), migration 0008 with working downgrade, nine event types with typed payloads, status derived from job rows (`not_requested`, `pending`, `succeeded`, `failed`), resume page controls, architecture and ADR docs.

## Evidence

- **Schema tests** prove every enum check, the professional-only engagement type, the per-type source shape, composite foreign keys against a foreign user's row, the partial unique skill name index (and that a merged skill frees it), every grant (provenance columns cannot be updated; sources cannot be updated or deleted; only claim-skill links can be deleted) and the account-deletion cascade.
- **API tests (32)** cover the rules above plus staleness: `skills.updated_at` moves on claim create, edit, reclassify, source add, unlink, relink, skill edit and gap mark (and not when a claim is linked to a second skill, which does not change the first).
- **Extraction tests (33)** use scripted `FakeProvider` output: ungrounded claim dropped, statement whitespace normalized, six cases of an engagement type without proper support stored as `unspecified`, support too far from the statement, non-professional claims carry no type, hostile resume wrapped as `<untrusted_content label="resume">` and its output still validated (confidence clamped, class kept only as a proposal), no resume text or model output in the logs, an existing skill linked instead of duplicated, budget refusal (job `failed`, one attempt, `llm_budget_exhausted`, no model call), invalid output twice (two failed runs, one attempt), queue-retry reuse of a settled run (the provider is never called), a stored output that no longer validates is not reused, nothing runs without a request, the upload checkbox waits for parsing, one extraction per resume unless it failed, refused requests for unparsed, unreadable, archived and foreign resumes, and zero evidence rows until a confirm.
- **Review handler tests:** confirm creates claim, resume source, skills and links with the right events; Edit and confirm class change refused without the flag (item stays pending, no rows), recorded with old and new when confirmed; raising an engagement type needs the flag; invalid pairs and a foreign resume id refused; a gap-marked skill refuses the claim and leaves the item pending; reject creates nothing; batch confirm reports `conflict`, `gap_marked` and `not_found` per item and keeps the successes; another user's id reports `not_found`.
- **Mutation check:** replacing the engagement rule with "trust the model" made seven of these tests fail, then the rule was restored.
- **Isolation:** 18 new routes each have a case (foreign ids 404, lists never leak, acting as B changes nothing of A's).
- **Stack run (fake provider, clean shell).** `migrate` ran 0007 to 0008 and exited 0; `/healthz` 200. A synthetic user and session were created as owner. Upload and parse succeeded; `extract-evidence` returned 202 `pending`; a second request gave 409 `extraction_pending`. `llm_runs`: `extract_resume`, `evidence.extract` v1, `fake`/`fake-fast`, tier `fast`, `succeeded`, 582 in, 375 out, cost 0.002457. Seven pending review items (4 claims, 3 skills). **Before confirming: 0 skills, 0 claims, 0 sources, 0 links.** Batch confirm of six items: six `ok`, plus a made-up id reported `not_found`. Edit-confirm of a project claim to Learning: 422 `confirmation_required` without the flag, 200 with it, and `EVIDENCE_CLASS_CHANGED` (project to learning) written with the review item id. Skills showed derived headlines. A new skill showed Not recorded; marking a gap on it worked; marking a gap on a skill with a confirmed professional claim returned 409 `gap_refused_evidence_exists`. Merging two skills made the merged one a redirect and gave the survivor its alias. After account deletion every count (events, claims, skills, sources, links, review items, runs, resumes, artifacts, sessions, jobs) was 0. A second run with a hostile resume (HTML in the text) produced the proposals as plain strings.

## Changes outside the expected file set

| File | Change | Reason |
| --- | --- | --- |
| `backend/app/jobs/registry.py`, `runner.py` | `PermanentJobError`: the runner fails the job once with its code instead of retrying | The brief says a model failure must not retry automatically, and the extraction status is derived from the job row, so the job has to end `failed` with the error code |
| `backend/app/resumes/{service,router,schemas}.py` | Extract endpoint, upload field `extract_evidence`, `evidence_extraction` on resume responses | The trigger and its status; no new column |
| `backend/app/review/{router,schemas}.py` | `POST /review-items/batch-confirm` | The spec's Review command list includes batch confirm |
| `backend/app/main.py`, `jobs/handlers.py`, new `review_registry.py` | Production review registry used by the API and the worker | First production handlers |
| `backend/app/llm/providers/fake.py`, `fake_samples.py`, `factory.py` | The default fake provider can return a deterministic sample for `EvidenceExtraction`, built from the resume text | Without it a stack run or the UI check shows no proposals (same gap noted in Task 6); real runs are unaffected |
| `backend/app/llm/prompts/{catalog,evidence_extract}.py`, `prompts.lock.json` | New prompt and lock entry | The extraction prompt |
| `backend/app/config.py`, `infra/docker-compose.yml`, `.env.example`, `README.md` | Three settings | Decision G |
| `backend/tests/db/{conftest,test_isolation}.py`, `tests/test_boundaries.py`, three frontend fixtures, `Layout` files | `production_app` fixture, new isolation cases and seeds, the extraction boundary test, `evidence_extraction` in resume fixtures, two nav links | Required by the new routes and fields |
| `backend/openapi.json`, `frontend/src/api/schema.d.ts` | Regenerated | New routes and schemas |

## Important things I learned

- **Windows had reserved ports 5173 and 5432.** `netsh interface ipv4 show excludedportrange protocol=tcp` listed 5173 to 5272 and 5432 to 6031, so Compose could not publish Postgres or the frontend (an environmental, not a code, problem; it happens after a reboot or a Hyper-V change). I worked around it with a throwaway override file outside the repo (Postgres on 15432, frontend on 15173). Google sign-in and your UI check need 5173 itself, so the reservation has to be cleared first (see Unresolved issues).
- **A task without a status column needs permanent job failures.** Task 6 stores `extraction_status` on the opportunity. Resumes have no such column and the brief allows only the four tables, so the status is derived from the newest `extract_evidence` job. That only works if a model failure ends the job `failed` once; otherwise the runner would retry with backoff. Hence `PermanentJobError`.
- **Normalization for skills cannot reuse the company/JD normalizer.** `normalize_text` strips every punctuation and symbol character, so `C++` and `C#` would both become `c`. Skills use their own key (NFKC, casefold, hyphen and underscore as spaces, only edge punctuation stripped).
- **"Gap or evidence, not both" has to hold in both directions.** Refusing a gap when evidence exists is not enough: adding or reclassifying evidence on a gap-marked skill would show "Gap" and "Professional" together. The same check runs on create, link and reclassify.
- **The model's engagement type needs more than "the quote exists".** A quote can be real resume text and still not say "full-time". The rule now needs a cue word for the claimed type and proximity to the statement. A mutation test showed the engagement tests do catch a model-trusting implementation.
- **Fixture and helper naming collide in forms.** Two forms on one page with the same label ("Evidence class") broke label-based tests twice; filters now say "Filter by …".
- **Long shell heredocs fail on this host** (as the brief warned): one command that mixed a heredoc with several others silently applied nothing. I wrote files with the editor tool or small script files from then on.
- **The fake provider fills lists with nothing.** `sample_from_schema` returns empty lists, so extraction showed no proposals in the stack. A small, deterministic, fake-only sample fixes that without touching the real adapter.

## Checks run and results

| Check | Result |
| --- | --- |
| `ruff check`, `ruff format --check`, `mypy` (strict, 234 files) | Pass |
| Full `pytest` with Postgres and `REQUIRE_DB_TESTS=1` | Pass: 1,421 tests collected (1,292 before), exit 0, one skipped (the symlink storage test that skips on this Windows host). The last two full runs passed; the last included every change except the checkpoint file |
| Extraction and rule tests (scripted `FakeProvider`) | Pass (see Evidence) |
| Migrations on an empty DB: upgrade head, `alembic check`, downgrade base, upgrade head | Pass; no drift; run again after the last migration edit |
| Frontend `npm run lint`, `typecheck`, `test`, `build` | Pass: 188 tests (145 before) |
| Regenerated `openapi.json` and `schema.d.ts` | Up to date (regeneration produces no diff) |
| Stack: `migrate` exit 0, `/healthz` 200, end-to-end script, deletion leaves no rows | Pass (twice, including the hostile resume) |
| Live UI check (owner) | Not run yet: pending your steps and the port fix |
| Optional real extraction with an Anthropic key | Not run (needs your key and approval) |
| GitHub Actions (backend, frontend, secrets) | Pending the push |

## Deviations from the frozen spec

None that contradict a rule. These are readings of places where the spec is silent or its table does not cover a case; ADR-023 records the first four.

- Extraction creates review items only, so no row has `confirmation_status = proposed`, and `SKILL_PROPOSED` and `SKILL_REJECTED` are not emitted (there is no skill to attach them to). The commands to confirm or reject a proposed row are not built because no producer creates one.
- A confirmed claim can be rejected (`CLAIM_REJECTED`), although 5.4a lists rejection only from proposed; 4.3.2 requires the user to be able to "reject" evidence before marking a gap.
- Evidence of a blocking class cannot be added or reclassified onto a gap-marked skill (`gap_marked`).
- A manually added claim writes `CLAIM_CONFIRMED` (the table has no event for a manual add); skill edits write no event (the table lists none).
- `skills.llm_run_id` is an addition from the general provenance convention in 4.1, not from the Skill row.
- Professional evidence with an unspecified engagement type ranks between internship and academic evidence in the headline; the spec's order omits it.
- The alias limit is 50 per skill (a database check), a number the spec does not give.

## Clarifications where the spec overrode the brief

- **Resume exposure:** the brief said "text contains the canonical name or an alias". The spec (4.3.2) says stated claims plus Postgres full-text search for mentions. The spec's version is implemented.
- **Redirect field:** the brief guessed `merged_into_id`; the spec's field is `merged_into_skill_id`.
- **Evidence source types:** the spec has `resume`, `project_url`, `user_assertion`, `artifact`; used as specified.
- **Batch confirm:** the brief described the UI sending several single confirms; the spec lists batch confirm as a Review command, so there is an endpoint, with the same per-item semantics.
- **Confirm and reject proposed claims:** the brief listed these; see the first deviation above.
- **"Explicit on upload":** the spec wording is implemented as an upload checkbox (the brief made it optional).

## Additions beyond the brief

- Fake-provider evidence sample (dev only), so the stack and UI checks show proposals.
- Stricter engagement-type rule (cue word and proximity) than the brief's "quote is in the text".
- Gap-versus-evidence refusal in the other direction, with ADR-023.
- Evidence list and detail pages, a nav link for each of Skills and Evidence, and `evidence_extraction` on resume responses.
- A boundary test that extraction cannot import the evidence writers.

## Process deviations

- **I ran `npx prettier --version` while looking for a formatter config, and npx downloaded prettier (3.9.10) into its cache** without asking. Nothing was installed into the project (`package.json` and the lockfile are unchanged) and prettier was not used afterwards; I used `npx --no-install` from then on. The npx cache entry is still on disk; tell me if you want me to remove it.
- I ran `ruff format` on the files I created or edited, as the existing code is `ruff format` clean and CI checks it; no repository-wide formatter run.
- Docker Compose could not publish ports 5173 and 5432, so I used a temporary override file kept outside the repository. The committed Compose file is unchanged apart from three new variables.

## Unresolved issues

- **Port reservation (blocks the UI check).** To sign in with Google at `http://localhost:5173`, Windows must stop reserving 5173. From an administrator terminal: `net stop winnat` then `net start winnat` (or restart Docker Desktop or the machine), then I restart the stack without the override.
- Check 5 (your UI check) and check 6 (optional real extraction) are not run.
- GitHub Actions is untested until the push.
- The fake provider's sample proposes at most five claims per resume and never an engagement type; only scripted tests and a real run exercise those paths.
- A name made only of punctuation (for example `C++`) can match unrelated resumes in "mentioned" exposure (full-text search is token-based).

## Git state

Branch `task-09-evidence-skills`, 8 commits ahead of `main` (brief, migration and models, domain and API, extraction and review handlers, frontend, docs, fake sample and ADR, checkpoint). Not pushed. No pull request. CI status: pending the push.

## Recommendation

Approve after your UI check and a green CI run. The backend, frontend, migration and stack checks all pass and the truth rules are proved by tests that fail when the rule is broken. What remains is the part only you can do (the UI check, once port 5173 is free) and the push.
