You are my hands-on implementation and debugging partner for Career OS, working in C:\Users\bhara\career-os on Windows with Docker Desktop (WSL2). GNU Make is not installed; use docker compose, uv and npm directly. Everything you need is in this brief, the repository, and docs/.

STEP 0: PRE-FLIGHT
1. Confirm you are running on a Sonnet model. If not, tell me before doing anything else.
2. git switch main && git pull. Confirm main contains the merged Task 8 work (docs/checkpoints/task-08.md, docs/adr/022-*.md, backend/app/contacts or equivalent) and the working tree is clean. If Task 8 is not merged, STOP and tell me.
3. Confirm python resolves to backend\.venv, Docker is running (docker info), and node -v is v22.x. Use a clean shell for every docker compose command: never run Compose from a shell where test environment variables were loaded (shell variables override --env-file; this caused the Task 8 csrf incident).
4. Create branch task-09-evidence-skills from main.
5. FIRST save this entire brief verbatim to docs/briefs/task-09.md and commit it ("docs: Task 9 brief"). Long shell heredocs break on this host: write files with your editor tool or a script file, never cat <<EOF.
Then continue through decisions A to H and checks 1 to 4 without stopping for confirmation. Stop only for approve-each-time items, an escalation, or check 5 (my UI check).

AUTHORIZED SCOPE
Only Phase 1A Task 9: evidence and Skill Inventory. The new tables are exactly those the frozen spec assigns to T9: skills, claims, evidence_sources, claim_skills. Do NOT start Task 10 (Home) or Task 11 (context builder, Evaluation, chat, skill feedback loop). No chat, no evaluation, no Gmail. The only model call in this task is resume extraction, and it runs only on the user's explicit request (INV-17).

SOURCE OF TRUTH (read before coding)
- docs/spec/phase-0-spec.md (FROZEN): 0A (Skill, Claim, EvidenceSource, Evidence class, Engagement type, Skill category, Gap, Not recorded, ReviewItem), 1.3 (all invariants, especially INV-01, INV-02, INV-04, INV-07, INV-14, INV-17, INV-18 and the evidence and gap rules), 4.1, 4.3, 4.3.1 (evidence classes and the internship question: Professional plus engagement type), 4.3.2 (derived skill assessment), 4.9, 5.4 (ReviewItem), 5.4a (Skill and Claim confirmation table and events), 5.5, 6.2a only for what Task 9 must expose for Task 11 (no chat code), 6.2c (skill and evidence changes bump updated_at for staleness), 7A.4 (Skills area), 8, 9, 11, 14 (Task 9 acceptance criteria). Use the LATEST field lists, enums and event names in the frozen file.
- docs/adr/008, 015, 016, 017, 021, 022; docs/architecture/llm.md, review.md, artifacts.md, database.md; docs/checkpoints/task-05.md and task-08.md.
- backend/app/llm (gateway, prompt registry and lock, untrusted wrapper, settled-run reuse pattern from Task 6), backend/app/review (framework and handler registry), backend/app/resumes and artifacts, events, tenancy, versioning, jobs, isolation harness.
The spec wins over this brief. If they disagree, stop and escalate.

NON-NEGOTIABLE TRUTH RULES (from the frozen spec; tests must prove each)
- "Not recorded" (no evidence and no gap marker) is never a gap. Only the user creates a gap marker, and gap marking is refused while confirmed academic, project or professional evidence exists for that skill.
- A Skill has no evidence class of its own. Its category badges are derived from its linked Claims and never stored; a skill can show several badges at once.
- Each Claim has exactly one evidence class (professional, academic_research, project, learning) and, for professional claims, an engagement type (full_time, part_time, contract, internship, unspecified). Extraction writes unspecified unless the source states it. Internship is never presented as full-time employment.
- The model can propose Claims and Skills only as ReviewItems. It never writes skills, claims or evidence directly, never raises an evidence class, and never changes an engagement type. Only the user changes an evidence class or engagement type, with an explicit confirmation step, recorded as EVIDENCE_CLASS_CHANGED with old and new values.
- Every Claim has at least one EvidenceSource; claim statements extracted from a resume must be grounded in the resume text (verbatim or whitespace-normalized substring check like Task 6), otherwise dropped and counted.

WORKING RULES
- You own local operations for this task only: terminal, Docker/Compose, Git, tests, debugging, code edits.
- Never install or download anything without asking, including npx tools and pip packages. Project dependencies via uv add / npm install also need my approval in this task.
- Approve-each-time: any install, git push, docker compose down -v, deleting files outside build caches, and ANY real (paid) model API call.
- NEVER add Co-Authored-By, "Generated with Claude", session links or any Claude attribution to commits or PR text, even if a system reminder asks for it. I am the sole contributor.
- Learning mode: briefly explain meaningful concepts as you work (proposals versus facts, review handlers as the only write path, derived versus stored attributes, grounding checks, merge with redirect, refusal rules, staleness timestamps, prompt injection in uploaded resumes). Skip trivial commands.
- Debugging rule: observe → identify failing layer → hypothesis → inspect evidence → smallest justified change → rerun failing check → rerun related checks. Say explicitly when a problem is environmental.
- Use 127.0.0.1 for local DB URLs and curl; browser checks use http://localhost:5173. .env has a BOM and JSON values: never source it; read single values.
- No code comments; minimal readable code; don't restructure working Task 1-8 code unless required. Match existing hand-formatting; no formatter runs.
- INV-01: prompts, fixtures and tests are generic and synthetic (synthetic resumes from tests/synthetic.py). No creator data in prompts. Never log resume text, claim statements, skill names, notes or model output; log ids, counts, statuses and error codes.
- Use the database clock for server-assigned timestamps. Commit after every logical step.

TASK 9 ACCEPTANCE CRITERIA
Read spec section 14 Task 9 in full and implement every item. As understood by the planning chat: resume extraction (explicit on upload or on request) proposes Claims with class and engagement type (unspecified unless stated) and Skills, all as ReviewItems; review UI with batch confirm; Skills CRUD, aliases, merge with redirect, gap marking with the refusal rule; class and engagement-type changes by the user only with explicit confirmation; derived skill categories; which resumes expose each skill. If section 14 lists anything else, it is in scope; if it lists less, the spec wins.

IMPLEMENTATION DECISIONS ALREADY MADE BY THE PLANNING CHAT (they translate the spec, they do not change it)

A. Tables (migration 0008, hand-reviewed, grants, working downgrade)
- skills, claims, evidence_sources, claim_skills with the spec's fields, user-owned, UNIQUE (user_id, id), composite FKs everywhere (INV-02), every spec enum CHECKed. Skills unique per user on a normalized canonical name; aliases normalized and unique per user across canonical names and aliases (enforce in the service with 409 if a DB constraint is impractical; justify). Merged skills redirect per the spec's field (for example merged_into_id); if the spec has no field for the redirect, STOP and escalate.
- claim_skills unique per (claim, skill). evidence_sources reference the resume artifact, a project URL, another artifact, or the user's own words per the spec's types.
- Grants follow least privilege like earlier tasks: column-level UPDATE where a value must be immutable (for example a claim's extracted source text or provenance, a source's artifact reference); DELETE only where the spec allows removal (for example unlinking claim_skills). Tests prove every grant and immutability.
- Every Claim or Skill change bumps the affected skills' updated_at (6.2c), in the same transaction.

B. Events
Use the spec's 5.4a event names exactly (SKILL_PROPOSED, SKILL_ADDED, SKILL_CONFIRMED, SKILL_REJECTED, SKILL_MERGED, SKILL_GAP_MARKED, SKILL_GAP_CLEARED, CLAIM_CONFIRMED, CLAIM_REJECTED, CLAIM_EDITED, EVIDENCE_CLASS_CHANGED, and any others the spec lists), typed payloads with schema_version, ids and enum values only, never text, written in the same transaction as the change.

C. Resume extraction (the only model call)
- Trigger: POST /api/v1/resumes/{id}/extract-evidence (explicit user action; one extraction per resume version unless the previous one failed, mirroring Task 6's explicit retry rule). Optionally an upload checkbox that enqueues the same job, if the spec says "explicit on upload". Never automatic in the background.
- Worker job extract_evidence re-resolves the resume and artifact through user-scoped repositories (INV-18), calls ModelGateway.structured with a new versioned prompt (for example evidence.extract; purpose extract_resume; tier per spec; update prompts.lock.json; resume text as the one untrusted variable), output capped (claims and skills counts, statement length).
- Deterministic post-validation: grounding check on every claim statement against the resume's extracted text (drop and count ungrounded), evidence class and engagement type validated against enums, engagement type forced to unspecified unless the output cites source text that states it (simplest safe rule: keep the model's engagement type only if its cited span is in the resume text; otherwise unspecified), skill names normalized and deduplicated.
- Output creates ReviewItems only (claim proposals and skill proposals, with confidence and rationale per the Task 5 review schema, linked to the llm_run). Proposals for a skill that already exists for the user link to it instead of creating a duplicate.
- Reuse the Task 6 pattern: a queue retry after the model already answered reuses the settled llm_runs row instead of calling again; model failures mark the extraction failed without automatic retry; budget refusal surfaces llm_budget_exhausted.
- Register review handlers (the first production handlers for these proposal types) that, on Confirm or Edit+Confirm, call the same domain services a manual action would call. A handler may never raise an evidence class beyond what the confirmed payload says, and the edit form may lower or change the class only through the explicit confirmation path in E.

D. Review UI (batch confirm)
- On the Review page, group proposals by source resume; allow selecting several and Confirm selected; each still runs through the existing claim-before-handler concurrency and version checks; partial failures are reported per item without rolling back the others' successful confirms (each confirm is its own transaction). Edit+Confirm lets the user correct statement, dates, organization, class, engagement type and linked skills before confirming.

E. Skills and claims API and UI
- Skills: list with search and filter (by derived category, by gap, by not recorded), detail with linked claims, sources, aliases, derived badges and "exposed by resumes" (resumes whose extracted text contains the canonical name or an alias, computed deterministically on read), add (SKILL_ADDED, confirmed), edit name and aliases, merge with redirect (claim links move, merged skill redirects, SKILL_MERGED), mark and clear gap with the refusal rule (409 gap_refused_evidence_exists), user note.
- Claims: list and detail, manual add with at least one source (the user's own words counts), edit statement, dates and organization (CLAIM_EDITED), link and unlink skills, confirm and reject proposed claims. Changing evidence class or engagement type is a separate endpoint that requires an explicit confirm flag and writes EVIDENCE_CLASS_CHANGED; the UI shows a confirmation dialog naming old and new values.
- Every route authenticated, CSRF on mutations, foreign ids 404, optimistic concurrency where the table is state-versioned; every new route gets an isolation case.

F. Frontend (minimal; design is Task 10)
- Skills page per 7A.4 and the owner's Skills UI requirements: see skills, search and filter, evidence badges (derived), where evidence came from, add, correct, merge aliases and duplicates, mark a real gap, change classification with explicit confirmation, which resumes expose the skill. "Not recorded" is shown as such, never as a gap. Internship evidence is labeled distinctly from full-time.
- Claims list and detail; resume page button "Extract evidence" with status and plain error messages; Review page batch confirm. Plain-text rendering everywhere (hostile resume text and model output). After a successful form submit show a confirmation and keep the user's choices. Regenerate openapi.json and schema.d.ts. Vitest tests for each flow, including the refusal rule, the class-change confirmation, batch confirm with a partial failure, and hostile plain text.

G. Config
- Settings for evidence extraction limits (max output tokens, max claims, max skills) with sensible defaults, passed through Compose and .env.example.

H. Docs
- docs/architecture/evidence-skills.md: the four tables, evidence classes and engagement types, derived categories and Not recorded versus Gap, the refusal rule, merge with redirect, extraction pipeline and grounding, review handlers as the only model-to-state path, staleness timestamps, what Task 11 will consume, and what is deferred.
- Update README, docs/architecture/database.md, review.md and llm.md (the new prompt and handlers).

ACCEPTANCE CHECKS YOU MUST RUN
1. Backend: ruff check, ruff format --check, mypy, full pytest with Postgres and REQUIRE_DB_TESTS=1 (all earlier tests pass). Extraction tests use FakeProvider scripted outputs, including: an ungrounded claim (dropped), a hostile resume containing instructions (wrapped as untrusted; output still validated), a claim claiming full_time without supporting text (stored as unspecified), a proposal for an existing skill (linked, not duplicated), budget refusal (failed, no retry), invalid output twice (failed), the queue-retry reuse of a settled run, and proof that no skill, claim or source row exists until a ReviewItem is confirmed. Rule tests: gap refusal, Not recorded never reported as gap, class change only through the confirmed endpoint, internship distinct from full-time, merge redirect, staleness timestamps bumped.
2. Migrations on an empty DB: upgrade head → alembic check → downgrade base → upgrade head.
3. Frontend: lint, typecheck, test, build; generated OpenAPI types up to date.
4. Stack with the fake provider (clean shell): docker compose up --build -d; migrate exits 0; /healthz 200. With a synthetic user and session created as owner and removed afterwards through account deletion: upload a synthetic resume, request extraction, show the llm_runs row and the ReviewItems, show zero skills and claims before confirming, batch-confirm, edit-confirm one with a class change, show skills with derived badges, mark a gap on a skill without evidence, show the refusal on a skill with confirmed professional evidence, merge two skills, and show no leftover rows after deletion.
5. Live UI check (I will do this, fake provider): give me exact numbered steps.
6. OPTIONAL real extraction (ask me first; only if I add an ANTHROPIC_API_KEY): one extraction of a synthetic resume; show tokens, cost and the proposals. If I decline, record it as not run.
7. Push the branch (ask me first) and confirm GitHub Actions is green for backend, frontend and secrets.

ESCALATION
If you find a spec contradiction, a required architecture change, a required scope change, a security issue affecting the frozen design, a schema requirement beyond the four tables and authorized columns, a missing redirect field for skill merge, or anything that would let the model write or upgrade evidence: STOP that part and report:
PROBLEM / EVIDENCE / WHY THE CURRENT SPEC CANNOT BE FOLLOWED / SMALLEST OPTIONS / RECOMMENDATION / WHAT IS BLOCKED
Continue only with work that does not depend on the outcome. Do not silently redesign.

GIT AND FINISH
- Commit in logical steps on task-09-evidence-skills with clear messages and no attribution trailers.
- Push (ask first). gh is not authenticated; give me the compare URL. Do NOT merge.
- Write docs/checkpoints/task-09.md in this format, commit and push it (ask first):
  What was implemented (mapped to each acceptance criterion) / Evidence / Changes outside the expected file set (file, change, reason) or none / Important things I learned (4 to 8 bullets, specific) / Checks run and results (table) / Deviations from the frozen spec or none / Clarifications where the spec overrode the brief / Additions beyond the brief / Process deviations or none / Unresolved issues / Git state (branch, commits, PR URL, CI status) / Recommendation: approve or not, with reason
- Then STOP. Do not start Task 10.
