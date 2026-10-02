# Task 1 Checkpoint Report — Repository Scaffold and CI

**What was verified** (mapped to spec §14 acceptance criteria)

1. `docker compose up` starts Postgres, API, worker, frontend — **verified**. All four services came up on every run; postgres/api report `healthy`, worker and frontend have no healthcheck defined (by design — worker is a loop, frontend is dev-only) but both stayed running.
2. `/healthz` returns OK — **verified**. `200 {"status":"ok","version":"0.1.0"}` with an `x-request-id` header, both directly (port 8000) and through the Vite proxy (port 5173).
3. CI runs ruff, mypy, pytest, ESLint, tsc, Vitest, gitleaks on every push and passes — **verified**. GitHub Actions run for commit `d5d03ca` is green: backend, frontend, secrets all passed. Locally, the same seven checks all pass (see table).

**Evidence**

- `GET /healthz` → `200`, `{"status":"ok","version":"0.1.0"}`, `x-request-id` present.
- API log: `{"event":"request_completed","route":"/healthz","status_code":200,...}` — route template only, no raw path, no secrets.
- Worker log: `worker_started` → (on stop) `worker_stop_requested` (`SIGTERM`) → `worker_stopped` → container exit code `0`.
- Frontend at `localhost:5173` (confirmed in-browser): "Career OS / Home / ... / API connected (version 0.1.0) / Created by Bharathraaj Nagarajan" — proves the Vite→API proxy end-to-end.
- Backend: ruff check clean, ruff format clean (14 files), mypy clean (14 files), pytest 33 passed.
- Frontend: ESLint clean, tsc clean, Vitest 3 passed, `vite build` succeeded (346 KB / 109 KB gzip).
- GitHub Actions on `main` @ `d5d03ca`: backend ✅, frontend ✅, secrets ✅.

**Changes made during verification**

| File | Change | Reason |
|---|---|---|
| `frontend/vite.config.ts` | Added `watch: usePolling ? { usePolling: true, interval: 300 } : undefined`, gated on `VITE_USE_POLLING` env var | Vite's chokidar watcher doesn't see file changes on this Windows bind mount by default (verified via WebSocket HMR probe: no `update` message after an edit); polling forces a stat-based fallback. Off by default so non-Docker/native dev is unaffected. |
| `infra/docker-compose.yml` | Added `VITE_USE_POLLING: "true"` to the `frontend` service environment | Turns the polling fallback on only inside the Compose dev stack, where the bind-mount issue actually occurs. |
| `.gitignore` | Added `.claude/` | Local Claude Code tool-permission cache (machine-specific, created locally by Claude Code during this session, not part of the archive) — same category as the already-ignored `.vscode/`/`.idea/` — not project source, shouldn't be committed. |
| *(none to compose/Dockerfile/CI/README beyond the above)* | — | All other Task 1 acceptance criteria passed unmodified. |

**Important things I learned**

- uvicorn's `--reload` (via the Rust `watchfiles` library) picks up changes on this Windows→Docker Desktop (WSL2) bind mount out of the box; Vite's default watcher (chokidar, inotify-based) does not — different watch strategies react differently to the same mount, and only one of the two needed a fix.
- Windows resolves PATH as *Machine* entries then *User* entries; nvm-windows only rewrites its own symlink target, so a pre-existing standalone Node install in `C:\Program Files\nodejs` (Machine PATH) silently shadowed nvm's Node 22 in every new terminal until it was uninstalled.
- `uv`'s installer appends to the *User* PATH directly, so it persisted into new terminals with no shadowing issue — worth remembering as the contrast case to the Node problem above.
- `uv sync` provisions its own CPython (3.12.14 here) independent of whatever Python is otherwise on the machine, which is exactly why the backend's Python-3.10 host mismatch never became a real blocker.
- Git's `core.autocrlf=true` (Windows default) converts LF→CRLF on checkout but the repo's committed bytes stayed LF and every check passed against them; no actual CRLF-driven failure occurred, so no `.gitattributes` was added — that's a live risk to revisit if a future contributor's Git settings ever produce a real failure, not a fix to make preemptively.
- A stray `.claude/` directory (Claude Code's local tool-permission cache) was created locally during this session; worth being alert to environment/tool artifacts sneaking into a first commit, since they don't show up as "untracked" red flags the way `.env` would.

**Checks run and results**

| Check | Result |
|---|---|
| `docker compose up --build` (4 services) | ✅ Pass |
| postgres + api healthcheck | ✅ Healthy |
| `GET /healthz` (direct, port 8000) | ✅ 200, correct body + `x-request-id` |
| `GET /healthz` (via Vite proxy, port 5173) | ✅ 200, proxy confirmed |
| API logs: JSON, route template, no secrets | ✅ Pass |
| Worker: `worker_started` | ✅ Pass |
| Worker: graceful `stop` → `worker_stop_requested`/`worker_stopped`, exit 0 | ✅ Pass |
| Frontend renders "API connected (version 0.1.0)" | ✅ Confirmed in-browser |
| Vite HMR over Windows bind mount (before fix) | ❌ No `update` message on WebSocket probe |
| Vite HMR over Windows bind mount (after `usePolling` fix) | ✅ `update` message received |
| uvicorn `--reload` over Windows bind mount | ✅ Reload detected, no fix needed |
| `ruff check` | ✅ Pass |
| `ruff format --check` | ✅ Pass (14 files) |
| `mypy` | ✅ Pass (14 files, no issues) |
| `pytest` | ✅ Pass (33 passed) |
| `eslint . --max-warnings 0` | ✅ Pass |
| `tsc -b --pretty` | ✅ Pass |
| `vitest run` | ✅ Pass (3 passed) |
| `vite build` | ✅ Pass |
| CI on GitHub (`main` @ `d5d03ca`): backend / frontend / secrets | ✅ / ✅ / ✅ |

**Deviations from the frozen spec**

None. The two config changes (Vite polling, `.gitignore` entry) are dev-environment/tooling fixes within Task 1's scaffold, not spec or architecture changes.

**Unresolved issues or environment notes**

- No `.gitattributes` exists. Nothing failed because of it today, but if a future contributor's Git config ever writes real CRLF bytes into a commit, that's the fix to reach for — not proactive today since nothing failed.
- `gh` is now installed but not authenticated in this non-interactive session; the CI check was completed manually. If future sessions want `gh run watch` from here, `gh auth login` needs to be run once, interactively, outside this tool.
- Local machine now has: `uv` (persists in new terminals), nvm-windows managing Node 22.23.3 as the sole Node (standalone Node 24 removed, persists in new terminals — confirmed by a `node -v` check in a new terminal), and `gh` 2.101.0 (unauthenticated).

**Git state**

- Branch: `main`
- Commit: `d5d03ca` — "Task 1: repository scaffold and CI"
- Remote: `https://github.com/BharathraajNagarajan/career-os.git`
- Working tree: clean
- CI run on `d5d03ca`: green — backend ✅, frontend ✅, secrets ✅

**Recommendation: Approve Task 1.**

All three acceptance criteria are met with direct evidence (not just green CI): the stack runs end-to-end, `/healthz` is correct and observable through both the API and the frontend proxy, structured logging and graceful worker shutdown are proven in logs, and the full local check suite matches the green GitHub Actions run. The two changes made were environment/tooling fixes scoped to Task 1's own acceptance criteria (dev-loop reliability, clean commit hygiene) and didn't touch domain code, schema, or architecture. No spec contradictions surfaced. Ready to take this back to the planning chat for Task 2 authorization.
