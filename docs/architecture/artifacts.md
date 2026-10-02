# Artifacts, resumes and lanes

Profile, immutable artifacts, resume upload and text parsing, resume lanes. Spec references: 1.3 (INV-01, INV-02, INV-05, INV-17, INV-18), 2.1, 3, 4.3, 6.2c, 8 (T1, T5, T6, T16), 9, 14.

## Objects and key layout

Original files live behind a `StorageAdapter` (`put`, `open`, `delete_prefix`; `app/artifacts/storage.py`). Development uses `FilesystemStorage`, rooted at `ARTIFACT_STORAGE_DIR` (Compose mounts the named volume `artifact-data` at `/srv/artifacts` in the API and the worker). The S3-compatible adapter that spec 3 calls for in production is deferred until deployment (open item O-6); it implements the same three methods.

| Rule | Why |
| --- | --- |
| Keys are `users/{user_id}/artifacts/{artifact_id}`, built from IDs by `artifact_key()` | The uploaded filename never reaches the filesystem, so path tricks in a filename are irrelevant. The per-user prefix makes account deletion one `delete_prefix` call |
| Every key is checked before use: no empty parts, `.`, `..`, backslash or NUL, and the resolved path must stay under the root (symlinks included) | Defense in depth (T6): even a bug elsewhere cannot write or read outside the root |
| Writes go to a temporary file in the same directory, are flushed and `fsync`ed, then published with a hard link (`os.link`) | A reader never sees a half-written file (atomic publish), and `link` fails if the key exists, so an existing object is never overwritten |
| Compose volume ownership comes from the image: the Dockerfile creates `/srv/artifacts` owned by the non-root `careeros` user before `USER careeros` | Docker copies the image directory's ownership into an empty named volume on first mount, so the unprivileged process can write |

## Database

`profiles`, `artifacts`, `resumes` and `resume_lanes` are user-owned tables (see [database.md](database.md) for grants). Highlights:

- **Immutability by privilege (INV-05).** `career_os_app` has `SELECT, INSERT` on `artifacts` plus `UPDATE` only on `extracted_text`, `extraction_status` and `extraction_error_code`. `storage_key`, `sha256`, `byte_size`, `mime_type`, `original_filename`, `kind` and `user_id` cannot be changed by the application role even if code tried. `career_os_app` has no `DELETE` on any of the four tables; resumes and lanes are archived, not deleted.
- **Deduplication.** `UNIQUE (user_id, sha256, kind)`. The same bytes uploaded twice by one user is rejected; two users uploading identical bytes each get their own object.
- **`resumes` ↔ `resume_lanes` are circular** (`resumes.lane_id` and `resume_lanes.default_resume_id`). Migration 0003 creates both tables first and adds the `default_resume_id` foreign key afterwards with `ALTER`. Both foreign keys use `NO ACTION`. Account deletion removes all of a user's rows through `ON DELETE CASCADE` from `users`; `NO ACTION` is checked at the end of the statement, so the result does not depend on the order in which the cascade happens to visit the tables (a test deletes a user with a lane, a resume in it and a default). Note on `RESTRICT`: it is the same check performed immediately and cannot be deferred. On PostgreSQL 16 we could not make it fail this cascade (the cascaded deletes' checks run when the outer statement finishes), so `NO ACTION` is chosen because it is order-independent by definition and keeps `DEFERRABLE` available, not because `RESTRICT` was observed to break deletion.
- **Lane names** are unique per user among active lanes, ignoring case (`UNIQUE (user_id, lower(name))` where `status = 'active'`). Archived lanes keep their name and do not block reuse; unarchiving into a taken name returns 409 `lane_name_taken`.
- **Typed JSON.** `work_authorization`, `target_roles`, `communication_preferences` and `parsed_outline` are written only from Pydantic models and carry `schema_version`. A new profile row contains empty lists and strings only; there are no default career values (INV-01).

## Upload pipeline (`POST /api/v1/resumes`)

Multipart, authenticated and CSRF-protected. Stages, in order:

1. **Stream limit.** The body is parsed incrementally (`app/resumes/upload.py`); the file part is hashed and spooled to a temporary file chunk by chunk, and the request is rejected with 413 `resume_too_large` the moment the file exceeds `RESUME_MAX_BYTES`. A declared `Content-Length` over the limit plus a small framing allowance is rejected before reading anything, and the total bytes read are capped as well, so a chunked body with no length cannot be buffered without bound. Starlette's default form parsing is not used because it spools the entire body before application code runs.
2. **Sniff.** The type comes from the file's first bytes, never from the client's `Content-Type` or extension: `%PDF-` is a PDF; a ZIP that contains `word/document.xml` is a DOCX. Anything else is 415 `unsupported_file_type`. A PDF named `.txt` is accepted as a PDF; a text file named `.pdf` is rejected.
3. **Zip guard (DOCX).** Before accepting, the archive's central directory is checked: at most 1000 members, 50 MiB total uncompressed, `word/document.xml` at most 20 MiB, and no member over 1 MiB that expands more than 200 times. Violations are 422 `unsafe_document`. Declared sizes cannot be forged upward past what the reader will actually produce, because Python's zip reader stops at the declared size.
4. **Hash and dedup.** SHA-256 was computed during streaming. An existing `resume_file` artifact with the same hash for the same user returns 409 `duplicate_resume` with the existing resume's id; nothing new is stored.
5. **Store.** The object is written under the generated key.
6. **Transaction.** One transaction inserts the artifact (`pending`) and resume (label defaults to the filename without extension), enqueues `parse_resume` (`user_id` = owner, payload `{artifact_id, resume_id}`, unique key `parse_resume:<artifact_id>`), and, if the upload names a lane, bumps that lane's `updated_at`. If anything fails, the stored object is removed (no orphan files) and a concurrent duplicate is reported as 409.
7. **Response.** 202 with the resume summary including `extraction_status: pending`.

`original_filename` is display data only: path components, control characters and edge dots are stripped and the length is capped. Downloads (`GET /resumes/{id}/file`) stream the stored bytes with the stored MIME type, `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff` and `Cache-Control: private, no-store` (T6). There is no endpoint that changes or replaces a stored file; replacement is a new upload.

## Parsing (`parse_resume`, worker)

No model is involved (INV-17); `pypdf` reads PDFs and `python-docx` reads DOCX.

- The handler re-resolves the artifact and resume through the user-scoped repositories with `ctx.user_id` (INV-18). A payload naming another user's rows, or rows that no longer exist, does nothing.
- Only `pending` artifacts are processed, so re-running the job for a succeeded (or permanently failed) artifact does nothing.
- Extraction runs in a **spawned child process** with a hard timeout (`PARSE_TIMEOUT_SECONDS`). A thread cannot enforce this: Python cannot kill a thread, and a parser stuck in a C extension or a pathological loop would hold the worker (and its GIL) indefinitely, while a memory blow-up or crash would take the worker down with it. A separate process can be terminated and killed from outside, and a crash in it is just a failed parse. `spawn` (not `fork`) starts a clean interpreter, so the child inherits no database connections or secrets.
- Limits: PDFs over `RESUME_MAX_PAGES` fail with `too_many_pages`. DOCX has no reliable page count, so DOCX is bounded by the upload byte limit, the zip guard and `EXTRACTED_TEXT_MAX_CHARS`. Extracted text is truncated to `EXTRACTED_TEXT_MAX_CHARS`.
- Outcomes: `succeeded`, or `failed` with one of `too_many_pages`, `encrypted`, `unreadable` (corrupt files and files with no extractable text, such as scanned images), `parse_timeout`. Parse failures are permanent: the artifact is marked failed and the job succeeds, so it is not retried. Infrastructure errors (database, storage) raise, and the job queue retries them with backoff.
- Logs carry error codes and counts only, never document text.

### Outline format

`resumes.parsed_outline` (schema version 1) is derived and re-derivable:

```json
{"schema_version": 1, "line_count": 10, "char_count": 252,
 "sections": [{"heading": "Experience", "start_line": 4, "end_line": 6}]}
```

Lines are the non-empty, trimmed lines of the extracted text, numbered from 1. A heading is a DOCX paragraph with a `Heading` style, or a short standalone line (80 characters or less, at most 4 words) that ends with a colon, is all upper case, or is one of a generic vocabulary of section words (summary, experience, education, skills, projects and similar). A section runs from its heading to the line before the next one; text before the first heading is not in any section. Heuristics are deterministic and generic; an upper-case single word such as a skill acronym on its own line is treated as a heading, which is an accepted limit of the approach.

## Lanes and staleness inputs

`resume_lanes.updated_at` is bumped when a lane is edited, archived or unarchived, and when a resume is assigned to it, removed from it, uploaded into it, archived or unarchived while in it (spec 6.2c). Archiving a resume clears it as the default of any lane. A default must be an active resume of the same user that is assigned to that lane. Foreign ids in a body are answered with 404, never 403; ineligible own ids with 422.

`profiles.constraints_updated_at` changes only when `current_location`, `relocation_preference`, `remote_preference` or `work_authorization` actually change value; headline, summary, target roles and communication preferences never touch it.

## Account deletion

`app/artifacts/deletion.py` registers a deletion hook that calls `delete_prefix("users/{user_id}/")`. The worker runs it before `delete_user_account()`, it is safe to run twice, and a failure raises so the job retries. The database rows are removed by the cascade from `users`. Tests prove the user's files and rows disappear and another user's remain.

## Deferred

- S3-compatible adapter (O-6, at deployment).
- OCR for scanned PDFs; such files currently fail as `unreadable`.
- Extraction of claims or skills from resume text (Task 9).
