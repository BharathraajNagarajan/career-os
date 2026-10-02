# Task 4 checkpoint: Profile, artifacts, resume upload and parsing, lanes

Branch `task-04-profile-resumes`. Brief: [docs/briefs/task-04.md](../briefs/task-04.md). Design: [docs/architecture/artifacts.md](../architecture/artifacts.md).

## What was implemented (mapped to the acceptance criteria)

| Acceptance criterion (spec 14) | Implementation |
| --- | --- |
| Profile with constraints (and `constraints_updated_at`), target roles and communication preferences | `profiles` table (one row per user, created lazily by `GET /api/v1/profile`), `PUT /api/v1/profile` replaces the editable fields. Work authorization, target roles and communication preferences are typed JSONB written from Pydantic models with `schema_version`. `constraints_updated_at` moves only when location, relocation, remote preference or work authorization actually change value (tested in both directions). New rows hold empty lists and strings, no career defaults (INV-01). |
| Resume upload with MIME, size and page limits | `POST /api/v1/resumes` (multipart, authenticated, CSRF). Body is parsed as a stream and rejected at `RESUME_MAX_BYTES` (413); type comes from magic bytes (PDF, or a ZIP containing `word/document.xml`), never the client `Content-Type` or extension (415); DOCX zip-bomb guards (422); PDF page limit `RESUME_MAX_PAGES` enforced in the parser (`too_many_pages`). |
| Original stored immutably with SHA-256 dedup | `FilesystemStorage` behind a `StorageAdapter` interface: generated keys `users/{user_id}/artifacts/{artifact_id}`, key-escape rejection, atomic temp-file-plus-hard-link writes that never overwrite. `artifacts` has `UNIQUE (user_id, sha256, kind)` and a column-level `UPDATE` grant limited to the three extraction columns, so the file's identity is immutable by database privilege (INV-05). Duplicate upload returns 409 `duplicate_resume` with the existing resume id. A failed transaction removes the orphan file. Downloads stream with `Content-Disposition: attachment`, the stored MIME type and `X-Content-Type-Options: nosniff`. No endpoint modifies or replaces a stored file. |
| Worker extracts text and a parsed outline without any model call | `parse_resume` job: `pypdf` and `python-docx` in a spawned child process with a hard timeout (`PARSE_TIMEOUT_SECONDS`), text capped at `EXTRACTED_TEXT_MAX_CHARS`, deterministic outline (`schema_version` 1: line count, char count, sections with line ranges). Outcomes `succeeded` or `failed` with `too_many_pages`, `encrypted`, `unreadable`, `parse_timeout`; parse failures are permanent, infrastructure errors retry through the queue. Idempotent. Re-resolves rows through user-scoped repositories (INV-18). |
| Lanes CRUD and resume-to-lane assignment | `GET/POST /lanes`, `PATCH /lanes/{id}`, `POST /lanes/{id}/archive` and `/unarchive`; `PATCH /resumes/{id}` (label and lane only), `POST /resumes/{id}/archive` and `/unarchive`. A lane's default must be an active resume assigned to that lane; archiving a resume clears it as default. `resume_lanes.updated_at` is bumped by every edit, archive, unarchive, assignment, removal, creation in the lane and archiving while in it (6.2c, tested). |
| UI never offers to edit a resume file | Resumes page offers upload, rename (label only), lane select, archive/unarchive and download. A Vitest test asserts that no control matching edit, replace, overwrite, modify or re-upload exists on any resume, that no file input sits inside a resume row, and that the only buttons are Rename and Archive/Unarchive. A backend test asserts the OpenAPI schema has no `PUT` or `DELETE` on any resume path. |

Also delivered: migration 0003 (four tables, grants, working downgrade, separate `ALTER` for the circular foreign key); account-deletion hook that removes the user's storage prefix before `delete_user_account`; Compose volume `artifact-data` and Dockerfile ownership fix; Profile, Resumes and Lanes pages with bounded polling and header navigation; regenerated OpenAPI contract and frontend types; synthetic PDF and DOCX builders for tests (INV-01).

## Evidence

**Backend (HEAD of this branch before the checkpoint commit):** `ruff check` and `ruff format --check` clean; `mypy` strict, 100 files, no issues; `pytest` with Postgres and `REQUIRE_DB_TESTS=1`: **374 passed, 1 skipped, 0 failed** (Task 2 and 3 tests included). The skip is the symlink-escape test for the storage adapter, which skips when the host forbids creating symlinks (this Windows host does; the Linux CI runner executes it).

**Migrations (empty scratch DB):** bootstrap, `upgrade head`, `alembic check` ("No new upgrade operations detected"), `downgrade base`, `upgrade head`, `alembic check` all exit 0.

**Frontend:** `npm run lint` (max warnings 0), `tsc -b`, `vitest run` (8 files, 36 tests passed), `npm run build` all pass; `npm run generate:api` leaves `schema.d.ts` unchanged after the final OpenAPI export.

**Stack (`docker compose up --build -d`):** `migrate` exited 0 (ran 0002 to 0003 on the local dev database), `/healthz` 200, API healthy. With a synthetic user and session created as owner (never your account):
- `POST /api/v1/resumes` with a synthetic PDF: **202**, `extraction_status: pending`. Same for a synthetic DOCX.
- Worker logs: `job_started`, `resume_parsed` (count 10 for the PDF, 8 for the DOCX), `job_succeeded`; no document text in the logs.
- Both resumes `extraction_status: succeeded`. PDF outline: `SUMMARY` lines 2-3, `Experience` 4-6, `Skills:` 7-8, `Education` 9-10 (10 lines). DOCX outline from heading styles: `Summary`, `Work History`, `Education` (8 lines).
- Inside the API container (user `careeros`): two files under `/srv/artifacts/users/<user id>/artifacts/<artifact id>`, so the non-root process can write to the named volume.
- Same PDF again: **409** `{"error":{"code":"duplicate_resume","resume_id":"<first resume id>"}}`. A text file renamed `.pdf`: **415** `unsupported_file_type`. A 5 MiB + 10 byte file: **413** `resume_too_large`. Upload without the CSRF header: **403**.
- Download: 200, `content-disposition: attachment; filename="synthetic-resume.pdf"; ...`, `x-content-type-options: nosniff`, `content-type: application/pdf`, `cache-control: private, no-store`; the bytes are identical to the original.
- Account deletion for the synthetic user: `POST /api/v1/account/deletion` 202. Before: 2 artifacts, 2 resumes, 2 jobs, 1 session, 1 user, 2 files. After the worker ran: 0, 0, 0, 0, 0 users, 0 files, and the user's directory is gone. Worker log order: `user_objects_deleted`, then `account_deleted`.
- A second synthetic user uploaded through the Vite proxy on `127.0.0.1:5173` (202) and was deleted the same way, confirming the proxy passes multipart bodies. No synthetic rows or files remain.

**Live UI check (check 5, owner): passed.** Run in the browser at `http://localhost:5173`. The browser check must use `localhost`, not `127.0.0.1`: the Google OAuth redirect URI is registered for `localhost`, and the session cookie is host-bound, so `127.0.0.1` would break the sign-in flow (API curl checks still use `127.0.0.1`). Signed in, created lane Platform, uploaded the synthetic `ui-check-resume.docx` (Processing, then Ready), assigned it to Platform, set it as the lane default, downloaded it (saved and opened correctly), and confirmed the resume row offers only the lane select, Rename, Archive and Download, with no edit or replace option. The duplicate upload was not repeated in the browser; it is covered by the live API check (409) and the automated tests.

**GitHub Actions:** run 37052570713 on `111e58e`: completed, success. Jobs backend, frontend and secrets all succeeded (including the symlink-escape storage test on Linux).

## Changes outside the expected file set

| File | Change | Reason |
| --- | --- | --- |
| `backend/app/core/errors.py` | `ErrorBody` and `ApiError` gained an optional `resume_id`; error responses omit null fields | The 409 duplicate response must include the existing resume id; existing error bodies are unchanged |
| `backend/app/jobs/handlers.py`, `backend/app/worker.py` | `register_job_handlers` now requires `storage` and `settings` and registers the `parse_resume` handler and the storage deletion hook | The handler and hook need the storage adapter and limits |
| `backend/app/main.py` | `create_app` takes an optional `storage`, keeps `settings` and `storage` on `app.state`, includes the profile and resumes routers | Routes and dependencies |
| `backend/tests/db/conftest.py` | `db_settings` points `artifact_storage_dir` at a temp directory | Isolated file storage per test |
| `backend/tests/db/test_account_deletion.py` | The `worker()` helper passes storage and settings | New `register_job_handlers` signature |
| `backend/tests/db/test_isolation.py` | Seeds both personas with a lane, resume and profile; generalises path-placeholder sampling; adds a case for every new route | Harness rule: every route gets a case |
| `backend/pyproject.toml`, `uv.lock` | Added `python-multipart`, `pypdf`, `python-docx` (and `lxml`, which `python-docx` needs) | Brief decisions C and D |
| `frontend/src/api/client.ts` | `apiFetch` accepts a `form` (FormData) option | Multipart upload with the CSRF header |
| `frontend/src/app/Layout.tsx`, `router.tsx`, `styles.css`, `Layout.test.tsx` | Navigation links, routes, nav style, nav test | Decision H |
| `frontend/src/test-utils.tsx` | Shared render and fetch-mock helpers | Page tests |
| `infra/Dockerfile`, `infra/docker-compose.yml`, `.env.example` | `/srv/artifacts` owned by `careeros`, `artifact-data` volume on API and worker, limit variables passed to API and worker only | Decision I |
| `README.md`, `docs/architecture/database.md`, `docs/architecture/auth.md` | Configuration rows, section, grants, circular FK note, hook now points at artifacts.md | Decision I |

## Important things I learned

- Starlette's normal form parsing (and FastAPI's `UploadFile`) spools the whole body to a temporary file before the route runs, so "stop at the limit" cannot be done there. I parse the multipart stream myself with `python_multipart`'s callback parser, hashing and spooling the file part as chunks arrive and aborting at limit + 1; a `Content-Length` pre-check and a total-bytes cap cover chunked bodies. FastAPI also turns non-HTTP exceptions raised during body parsing into a generic 400, which is another reason to parse inside the handler.
- Magic-byte sniffing beats trusting `Content-Type` or the extension because both are chosen by the client. A DOCX is a ZIP, so checking `PK` is not enough: the guard reads the central directory (member count, total and per-member uncompressed size, compression ratio) without decompressing anything.
- A thread cannot enforce a parse timeout: Python cannot kill a thread, and a parser stuck in C code holds the GIL, so the worker would hang with it. A spawned child process can be terminated, and a crash or memory blow-up in it only fails that parse. The timeout test finishes quickly because starting the child is slower than the 10 ms timeout, so the terminate path really runs.
- Column-level privileges give real immutability: `GRANT UPDATE (extracted_text, extraction_status, extraction_error_code)` means even a bug or SQL injection through the app role cannot change `sha256` or `storage_key`; the test tries seven columns and expects `InsufficientPrivilege` for each.
- Circular foreign keys need the second constraint added after both tables exist; and cascades from `users` removed all four tables without complaint. **A premise in the brief did not reproduce:** I expected `RESTRICT` to break account deletion, so I tried to prove it by switching both circular keys to `RESTRICT` (all three combinations) on PostgreSQL 16. Every one still deleted the user, because the cascaded deletes' foreign-key checks run when the outer statement completes. I kept `NO ACTION` as the brief decided (it is order-independent by definition and can be deferred), replaced the negative-control test with one that pins the constraints' action codes, and documented what was and was not observed rather than claiming `RESTRICT` fails.
- Atomic no-overwrite publishing needs more than `rename`: on POSIX `rename` replaces an existing file silently. Writing a temporary file and publishing it with `os.link` is atomic and fails if the key exists.
- Test parametrization with raw file bytes made pytest put the bytes in the test id and its `PYTEST_CURRENT_TEST` environment variable, which exceeded Windows' 32,767-character limit; explicit `ids` fixed it. Environmental, not a code bug.
- Shell heredocs on this host mangled backslashes (`\n`, `\x00`, line continuations) in generated files twice; edits containing them were redone with the editor tool and verified.

## Checks run and results

| Check | Result |
| --- | --- |
| `ruff check`, `ruff format --check` | Pass |
| `mypy` (strict) | Pass, 100 files |
| `pytest` with Postgres, `REQUIRE_DB_TESTS=1` | 374 passed, 1 skipped (symlink test, host limitation), 0 failed |
| OpenAPI contract up to date (`python -m app.openapi_export`, no diff) | Pass |
| Migrations: upgrade, `alembic check`, downgrade base, upgrade, check | Pass |
| Frontend `npm run lint`, `typecheck`, `test` (36 tests), `build` | Pass |
| Generated API types up to date | Pass (no change after regeneration) |
| Stack: compose up, migrate exit 0, `/healthz` 200 | Pass |
| Live API: PDF and DOCX 202, parsed, outline, file in volume | Pass |
| Live API: duplicate 409, renamed `.txt` 415, oversized 413, missing CSRF 403 | Pass |
| Live API: download headers and byte-identical file | Pass |
| Live API: account deletion removes rows and storage prefix | Pass |
| Live UI check (owner), at `localhost:5173` | Pass |
| GitHub Actions (backend, frontend, secrets), run 37052570713 on `111e58e` | Pass |

## Deviations from the frozen spec

None. Where the brief and spec could differ I followed the spec: object storage is local only (S3 adapter deferred to deployment, O-6); no model is called in parsing (INV-17).

## Unresolved issues

- Cosmetic: the app has no favicon, so the browser shows a cached icon from another `localhost` app. To be fixed in Task 10.
- S3-compatible storage adapter is not built (needs the deployment target, O-6). OCR for scanned PDFs is deferred; such files fail as `unreadable`.
- The outline heuristic treats a single upper-case word on its own line (for example a skill acronym) as a heading; accepted for a deterministic, generic first version and documented.
- DOCX has no page limit (no reliable page count); it is bounded by upload size, the zip guard and the text cap.
- The symlink-escape storage test could not run on this Windows host; it runs in CI on Linux.
- Local dev database now has migration 0003 applied (expected).

## Git state

Branch `task-04-profile-resumes` from `main` (merge commit of Task 3). Commits (oldest first): `docs: Task 4 brief`; tables, grants and settings; storage, upload guards, extraction, API and parse job; unit tests; schema tests; API tests; parse job, deletion and isolation tests with regenerated OpenAPI; type annotations; frontend pages; Docker, config and docs; this checkpoint. Pushed. PR URL: none (gh is not authenticated); compare URL: https://github.com/BharathraajNagarajan/career-os/compare/main...task-04-profile-resumes. CI status: green on `111e58e` (run 37052570713); the checkpoint update commit is pending push and CI.

## Recommendation

Approve. The live UI check passed, Actions are green for backend, frontend and secrets, and every acceptance criterion has automated tests plus live-stack evidence. The frozen spec is followed without deviation, and the one surprise (RESTRICT did not fail) changed documentation, not behavior. Remaining items are the deferred S3 adapter and OCR, and the cosmetic favicon (Task 10).
