You are my hands-on implementation and debugging partner for Career OS, working in C:\Users\bhara\career-os on Windows with Docker Desktop (WSL2). GNU Make is not installed; use docker compose, uv and npm directly. Everything you need is in this brief, the repository, and docs/.

STEP 0: PRE-FLIGHT
1. Confirm you are running on a Sonnet model. If not, tell me before doing anything else.
2. git switch main && git pull. Confirm main contains the merged Task 3 work (docs/checkpoints/task-03.md, backend/app/auth/) and the working tree is clean.
3. Confirm python resolves to backend\.venv, Docker is running (docker info), and node -v is v22.x.
4. Create branch task-04-profile-resumes from main.
5. FIRST save this entire brief verbatim to docs/briefs/task-04.md and commit it ("docs: Task 4 brief").

AUTHORIZED SCOPE
Only Phase 1A Task 4: Profile, artifacts, resume upload and text parsing, resume lanes. Do NOT start Task 5 (model gateway, LLM runs, review framework) or Task 9 (claims, skills, any resume extraction by a model). The only new tables are profiles, artifacts, resumes and resume_lanes.

SOURCE OF TRUTH (read before coding)
- docs/spec/phase-0-spec.md (FROZEN): 0A, 1.3 (invariants, especially INV-01, INV-02, INV-05, INV-17, INV-18), 2.1 (object storage row), 3 (artifact storage and document parsing rows), 4.1, 4.3 (Profile, Artifact, Resume, ResumeLane rows only), 6.2c (staleness inputs: constraints_updated_at, lane updated_at, resume creation/archiving/reassignment), 8 (threats T1, T5, T6, T16), 9 (Profile, Resumes and lanes rows), 11, 14 (Task 4 acceptance criteria)
- docs/architecture/database.md, docs/architecture/auth.md (including the account-deletion hook registry), docs/checkpoints/task-03.md
- backend/app/ (db conventions, tenancy, jobs, auth deps, error handling, isolation harness in backend/tests/db/test_isolation.py)
The spec wins over this brief. If they disagree, stop and escalate.

WORKING RULES
- You own local operations for this task only: terminal, Docker/Compose, Git, dependencies, tests, debugging, code edits.
- Never install anything system-wide without asking. Project dependencies via uv add / npm install are fine.
- Approve-each-time: git push, docker compose down -v, deleting files outside build caches.
- NEVER add Co-Authored-By, "Generated with Claude" or any Claude attribution to commits or PR text. I am the sole contributor.
- Learning mode: briefly explain meaningful concepts as you work (multipart uploads, magic-byte sniffing vs Content-Type, streaming size limits, zip bombs, content hashing and dedup, storage adapters, atomic file writes, column-level grants, circular foreign keys, process isolation with timeouts, idempotent jobs, root causes of errors). Skip trivial commands.
- Debugging rule: observe → identify failing layer → hypothesis → inspect evidence → smallest justified change → rerun failing check → rerun related checks. Say explicitly when a problem is environmental.
- On this Windows host use 127.0.0.1, not localhost, for local DB URLs and curl checks (localhost adds an IPv6 fallback delay).
- No code comments; minimal readable code; don't restructure working Task 1-3 code unless required.
- INV-01: all test resumes, names, companies and text must be synthetic. Never use my real resume or career data in code, fixtures or prompts.
- Commit after every logical step so work is recoverable if usage limits interrupt the session.

TASK 4 ACCEPTANCE CRITERIA (spec section 14)
Profile with constraints (and constraints_updated_at), target roles and communication preferences; resume upload with MIME, size and page limits; original stored immutably with SHA-256 dedup; worker extracts text and a parsed outline without any model call; lanes CRUD and resume-to-lane assignment; UI never offers to edit a resume file.

IMPLEMENTATION DECISIONS ALREADY MADE BY THE PLANNING CHAT (they translate the spec, they do not change it)

A. Tables (migration 0003, hand-reviewed, grants, working downgrade)
- profiles (user-owned, one per user): id, user_id UNIQUE, headline, summary, current_location, relocation_preference CHECK ('open','not_open','unspecified') default 'unspecified', remote_preference CHECK ('remote_only','hybrid','onsite','no_preference') default 'no_preference', work_authorization typed JSONB (list of {country (ISO 3166-1 alpha-2), status (short free text), sponsorship_needed (bool or null)}), constraints_updated_at, target_roles typed JSONB (list of {name, priority 'high'|'normal'|'low', notes}), communication_preferences typed JSONB ({tone, length, sign_off, avoid: list of strings}), created_at, updated_at. All JSONB payloads carry schema_version and are validated by Pydantic. No default values containing career data (INV-01).
- artifacts (user-owned, immutable): id, user_id, kind CHECK ('resume_file','jd_snapshot','email_excerpt','reference'), storage_key, sha256 bytea (32 bytes), mime_type, byte_size, original_filename, extracted_text NULL, extraction_status CHECK ('pending','succeeded','failed') default 'pending', extraction_error_code NULL, created_at. UNIQUE (user_id, sha256, kind). UNIQUE (user_id, id).
- resumes (user-owned): id, user_id, artifact_id (composite FK to artifacts), label, lane_id NULL (composite FK to resume_lanes), parsed_outline typed JSONB NULL, status CHECK ('active','archived') default 'active', created_at, archived_at NULL.
- resume_lanes (user-owned): id, user_id, name, description, emphasis_notes, target_role_labels text[], default_resume_id NULL (composite FK to resumes), status CHECK ('active','archived') default 'active', created_at, updated_at. UNIQUE (user_id, lower(name)) among non-archived lanes is optional; pick one and justify.
- The resumes↔resume_lanes foreign keys are circular. Create both tables first, then add the default_resume_id FK with a separate ALTER. Use NO ACTION (not RESTRICT) so account-deletion cascades still work; prove it with a test. Explain why.
- Grants to career_os_app:
  - profiles: SELECT, INSERT, UPDATE
  - artifacts: SELECT, INSERT, and UPDATE only on (extracted_text, extraction_status, extraction_error_code) via a column-level grant, so storage_key, sha256, byte_size, mime_type and original_filename are immutable by database privilege (INV-05). No DELETE.
  - resumes: SELECT, INSERT, UPDATE. No DELETE (archive only).
  - resume_lanes: SELECT, INSERT, UPDATE. No DELETE (archive only).
  - Tests prove the column-level immutability and the missing DELETE privileges.

B. Object storage (spec 2.1 and 3; hosting is deferred, so local only)
- A StorageAdapter interface (put, open for reading, delete_prefix) with a FilesystemStorage implementation rooted at ARTIFACT_STORAGE_DIR. The S3-compatible adapter is deferred until deployment (O-6); note this in the checkpoint.
- Storage keys are generated by us: users/{user_id}/artifacts/{artifact_id}. Never derived from the uploaded filename. Reject any key that escapes the root (defense in depth).
- Writes are atomic (temp file + rename) and never overwrite an existing key.
- Compose: a named volume artifact-data mounted at /srv/artifacts in api and worker. The containers run as a non-root user, so create /srv/artifacts owned by that user in the Dockerfile before USER (Docker copies image ownership into an empty named volume on first mount). Verify the API can write.

C. Upload (POST /api/v1/resumes, multipart, authenticated + CSRF)
- Add python-multipart via uv.
- Read the stream in chunks and stop at RESUME_MAX_BYTES + 1 (default 5 MiB): 413 resume_too_large. Never buffer an unbounded body.
- Sniff magic bytes, do not trust the client Content-Type or extension. Accept only PDF (%PDF-) and DOCX (a ZIP that contains word/document.xml). Anything else: 415 unsupported_file_type.
- DOCX zip-bomb guards before accepting: cap total uncompressed size and member count; reject on violation (415 or 422 with a clear code).
- Compute SHA-256. If the same user already has a resume_file artifact with that hash: 409 duplicate_resume including the existing resume id. Never store a second copy.
- Store the file, create artifact (pending) + resume (label defaults to the original filename without extension; editable), and enqueue job parse_resume (user_id = owner, payload {artifact_id, resume_id}, unique_key parse_resume:<artifact_id>) in one transaction. If storage succeeded but the transaction fails, remove the orphan file. Respond 202 with the resume id and extraction_status.
- original_filename is stored for display only, sanitized (strip path components and control characters, cap length).

D. Parsing (worker job parse_resume; no model call, INV-17)
- Add pypdf and python-docx via uv.
- Re-resolve artifact and resume through the user-scoped repositories with ctx.user_id (INV-18).
- Run extraction in a child process with a hard timeout (PARSE_TIMEOUT_SECONDS, default 30). Use a spawn-context multiprocessing process (or equivalent) that is terminated on timeout. Explain why a thread cannot enforce this.
- Enforce RESUME_MAX_PAGES (default 10) for PDFs; DOCX has no reliable page count, so enforce the byte and text-length limits instead and document this.
- Cap extracted_text at EXTRACTED_TEXT_MAX_CHARS (default 200000).
- Outcomes set artifacts.extraction_status and extraction_error_code: succeeded, or failed with too_many_pages, encrypted, unreadable, parse_timeout. Parse failures are permanent (mark failed, do not retry); infrastructure errors may retry through the job queue.
- parsed_outline (typed JSONB, schema_version 1): deterministic, generic heuristics only, for example {line_count, char_count, sections: [{heading, start_line, end_line}]}. Detect headings from DOCX heading styles, or from short standalone lines (title case, upper case or ending with a colon). Generic section words such as "Experience", "Education", "Skills" and "Projects" may be used; no person-, company- or career-specific content. Test with synthetic resumes.
- The job is idempotent: re-running it for an already-succeeded artifact does nothing.

E. Account deletion hook (carried from Task 3)
- Register a deletion hook that deletes the user's storage prefix (users/{user_id}/). It runs before delete_user_account, is idempotent, and is covered by a test proving files are removed and other users' files remain.

F. Profile API (single profile per user, created lazily)
- GET /api/v1/profile returns the caller's profile, creating an empty row on first access.
- PUT /api/v1/profile replaces the editable fields (validated by Pydantic, sensible length limits).
- constraints_updated_at is bumped only when current_location, relocation_preference, remote_preference or work_authorization actually change value; edits to headline, summary, target_roles or communication_preferences do not bump it. Test both directions.

G. Resumes and lanes API (foreign IDs → 404 via resolve_owned; every route gets an isolation case)
- GET /api/v1/resumes (caller's, with extraction status, lane, archived flag), GET /api/v1/resumes/{id} (includes parsed_outline and extraction status, not the full extracted text).
- PATCH /api/v1/resumes/{id}: label and lane_id only. lane_id must be an active lane of the same user.
- POST /api/v1/resumes/{id}/archive and /unarchive. Archiving a resume clears it as default of any lane.
- GET /api/v1/resumes/{id}/file streams the original bytes with Content-Disposition: attachment, the stored mime type, and X-Content-Type-Options: nosniff (spec T6).
- There is no endpoint that modifies or replaces a stored file (INV-05). Replacement = a new upload.
- Lanes: GET /api/v1/lanes, POST /api/v1/lanes, PATCH /api/v1/lanes/{id} (name, description, emphasis_notes, target_role_labels, default_resume_id), POST /api/v1/lanes/{id}/archive and /unarchive. default_resume_id must be an active resume of the same user that is assigned to that lane.
- Staleness inputs (spec 6.2c): bump resume_lanes.updated_at whenever the lane is edited, archived or unarchived, AND whenever a resume is assigned to it, removed from it, created in it or archived while in it. Test it.
- Isolation harness: add a case for every new route. No new route may be PUBLIC.

H. Frontend (minimal, functional, no design work; design tokens are Task 10)
- Profile page: form for the profile fields (work authorization and target roles as small repeatable rows).
- Resumes page: upload (file input accepting .pdf and .docx), list with extraction status (pending/succeeded/failed with a plain message), label edit, archive/unarchive, lane select, and a Download link. There is NO edit-file action anywhere (acceptance: UI never offers to edit a resume file); add a Vitest test that asserts no edit/replace control exists for a resume.
- Lanes page: list, create, edit, archive/unarchive, choose a default resume among the lane's resumes.
- Poll a pending resume until its status changes (bounded polling, no tight loop).
- Regenerate backend/openapi.json and frontend src/api/schema.d.ts; use the generated types.
- Navigation links to Profile, Resumes, Lanes and Settings in the Layout header.

I. Config, Compose, CI, docs
- Settings: ARTIFACT_STORAGE_DIR, RESUME_MAX_BYTES, RESUME_MAX_PAGES, PARSE_TIMEOUT_SECONDS, EXTRACTED_TEXT_MAX_CHARS (sensible defaults; storage dir passed to api and worker only).
- .env.example placeholders, Compose volume and env allowlists, CI values. CI needs no secrets for this task.
- docs/architecture/artifacts.md: storage adapter and key layout, upload pipeline (stream limit → sniff → zip guard → hash/dedup → store → transaction → job), parsing isolation and limits, outline format, immutability by column grants, deletion hook, what is deferred (S3 adapter, OCR for scanned PDFs).
- Update README (configuration table) and docs/architecture/database.md (new tables, grants, circular FK note).

ACCEPTANCE CHECKS YOU MUST RUN
1. Backend: ruff check, ruff format --check, mypy, full pytest with Postgres and REQUIRE_DB_TESTS=1 (all Task 2 and 3 tests still pass).
2. Migrations on an empty DB: upgrade head → alembic check → downgrade base → upgrade head.
3. Frontend: lint, typecheck, test, build; generated OpenAPI types up to date.
4. Stack: docker compose up --build -d; migrate exits 0; /healthz 200. With a synthetic test account (not mine; create a session as owner like your Task 3 perf check, and delete it afterwards), upload a small synthetic PDF and a synthetic DOCX via the API; show 202, the worker logs, extraction_status = succeeded, a sensible parsed_outline, and that the file exists under the storage volume. Then upload the same PDF again → 409; upload a renamed .txt → 415; an oversized file → 413. Finally run account deletion for that synthetic user and show their DB rows and storage prefix are gone.
5. Live UI check (I will do this): I sign in, upload a synthetic resume you generate for me (not my real resume), see it parse, assign it to a lane, set it as the lane default, download it, and confirm there is no edit-file option. Give me exact steps and the file when you reach this check.
6. Push the branch (ask me first) and confirm GitHub Actions is green for backend, frontend and secrets.

ESCALATION
If you find a spec contradiction, a required architecture change, a required scope change, a security issue affecting the frozen design, a schema requirement beyond the four tables, or a missing prerequisite that changes architecture: STOP that part and report:
PROBLEM / EVIDENCE / WHY THE CURRENT SPEC CANNOT BE FOLLOWED / SMALLEST OPTIONS / RECOMMENDATION / WHAT IS BLOCKED
Continue only with work that does not depend on the outcome. Do not silently redesign.

GIT AND FINISH
- Commit in logical steps on task-04-profile-resumes with clear messages and no attribution trailers.
- Push (ask first). gh is not authenticated; give me the compare URL. Do NOT merge.
- Write docs/checkpoints/task-04.md in this format, commit and push it:
  What was implemented (mapped to each acceptance criterion) / Evidence / Changes outside the expected file set (file, change, reason) or none / Important things I learned (4 to 8 bullets, specific) / Checks run and results (table) / Deviations from the frozen spec or none / Unresolved issues / Git state (branch, commits, PR URL, CI status) / Recommendation: approve or not, with reason
- Then STOP. Do not start Task 5.

Begin with Step 0.
