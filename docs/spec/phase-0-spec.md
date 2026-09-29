# Career OS — Phase 0 Engineering Specification

Frozen 2026-09-29 (revision 3). Source: Claude Docs spec, exported for the repository.

## 0. Status and how to use this spec

Career OS Phase 1 should be a **modular monolith**: one Python API/worker codebase, one React SPA, one PostgreSQL database, one object store, with Gmail and the LLM behind explicit integration boundaries. Nothing in this proposal requires Redis, Kafka, Temporal, a vector database, microservices or Kubernetes.

- **Status:** Phase 0 FROZEN (revision 3, approved 2026-09-29). This spec is the implementation source of truth. It changes only for a genuine contradiction, missing prerequisite, security issue or impossible requirement, through the smallest correction and an ADR. Tasks are authorized one at a time; Task 1 is authorized.
- **Scope:** Phase 1A: Shared Foundation, manual Applications workflow, evidence and Skill Inventory, Home, evaluation. Phase 1B: Gmail, then targeted outreach (committed, high priority). Other modules appear only as boundaries.
- **Priority order:** (1) trustworthy manual opportunity and application workflow, (2) evidence and Skill Inventory, (3) useful Home, (4) Review architecture, (5) Gmail ingestion and proposals, (6) outreach recommendation and drafting.
- **How to read it:** Section 0A defines canonical terms. Sections 1 to 16 are the specification (7A covers Home and UI). Section 17 lists decisions. The Checkpoint Report summarizes; the change sections at the end record each revision.
- **Change control:** once frozen, this spec moves into the repository as `docs/spec/` and consequential changes go through ADRs (section 15).
- **Attribution rule:** the only static creator-specific string allowed anywhere in the product is `Created by Bharathraaj Nagarajan`. All examples that mention companies, roles or skills are illustrative and must never appear in production logic, prompts, seeds or defaults.

## 0A. Canonical terms

Each term has exactly one meaning across the spec, code, API and UI. Retired synonyms must not be used in code or schema.

| Term | Canonical meaning | Retired synonyms or common confusion |
| --- | --- | --- |
| Opportunity | A job posting the user has ingested and may act on; exists independently of applying | "job", "posting" as entity names |
| Application | The fact that the user applied to one Opportunity; created only by Apply or a confirmed ReviewItem; stage derived from DomainEvents | Not a status on Opportunity |
| DomainEvent | Immutable record of something that happened to an aggregate | "ApplicationEvent" (now a DomainEvent with aggregate type `application`) |
| Skill | An entry in the user's Skill Inventory naming a capability (canonical name + aliases). A Skill has no evidence class of its own | Not a claim; not a JD requirement |
| Claim | One citable statement about the user's experience with exactly one evidence class, one or more EvidenceSources, and links to zero or more Skills | "evidence item" |
| EvidenceSource | Where a Claim comes from: resume, project URL, artifact, or the user's own words |  |
| Evidence class | Attribute of a Claim: `professional`, `academic_research`, `project`, `learning` | "evidence category" when applied to claims |
| Engagement type | Attribute of a professional Claim: `full_time`, `part_time`, `contract`, `internship`, `unspecified` | "employment subtype", "engagement context" |
| Skill category | Derived display value of a Skill: Professional, Academic / Research, Project, Learning, Gap, Not recorded. A Skill can show several evidence badges at once | Never stored |
| Gap | A Skill the user explicitly marked as not possessed. Only the user creates one | Never inferred from missing evidence |
| Not recorded | A Skill or requirement with no evidence and no gap marker: unknown, not negative | "gap" (wrong) |
| ReviewItem | A system-generated proposal awaiting Confirm, Edit + Confirm, or Reject / Ignore | "proposal", "review task"; RecruitingAction kind `review` (removed) |
| RecruitingAction | Something the user needs or intends to do by a time: follow-up, reply, assessment, interview, outreach, custom | "to-do", "FollowUp" (now a kind) |
| Interaction | One communication or meeting with a Contact, any channel, either direction | Not an outreach draft |
| Contact | A person in the user's network, owned by the user | Not a global person record |
| Evaluation | One immutable `opportunity_evaluations` row: interpretable components, qualification assessments, open questions, recommendation | "fit score", "match percentage", "OpportunityEvaluation" in prose |
| Stale evaluation | An Evaluation whose basis inputs changed after it was created (6.2c). Still shown, flagged, re-run only by the user | "outdated", "invalid" |
| Attention item | A typed Home entry published by a module's attention provider | "widget", "card" in schema |

## 1. Requirements normalization

The spec reduces to 38 functional requirements, 12 non-functional requirements and 18 invariants. Invariants are rules that must hold in every release and get dedicated tests. Revision 2 keeps requirement IDs stable: modified rows are marked, new rows start at FR-29.

### 1.1 Functional requirements (first vertical)

| ID | Requirement | Phase |
| --- | --- | --- |
| FR-01 | Users register and sign in; every request is authenticated | 1A |
| FR-02 | User maintains one primary profile: headline, location, relocation/remote preference, work-authorization facts, target role categories, communication preferences | 1A |
| FR-03 | User uploads one or many resumes; originals are stored unchanged | 1A |
| FR-04 | User defines resume lanes and associates resumes with lanes | 1A |
| FR-05 | *(modified)* System extracts proposed claims **and proposed skills** from resumes with provenance and evidence class; user confirms, edits or rejects | 1A |
| FR-06 | User ingests a JD (pasted text plus optional source URL) | 1A |
| FR-07 | System extracts company, title, team, job ID, location, source, minimum and preferred qualifications into structured records | 1A |
| FR-08 | System resolves the JD to an existing or new company and flags likely duplicate opportunities | 1A |
| FR-09 | *(modified)* System evaluates an opportunity with interpretable components, qualification-level assessments, blockers and a lane recommendation, using **both the Skill Inventory and claims**. Missing evidence is reported as "not recorded", never automatically as a gap; required skills without evidence become clarification questions | 1A |
| FR-10 | Evaluation considers company history: prior opportunities, applications, outcomes, contacts, interactions and strategy rules | 1A |
| FR-11 | User can Apply, Save or Skip an opportunity; Apply creates an Application | 1A |
| FR-12 | Application history is an append-only event stream; current stage is derived | 1A |
| FR-13 | User can record events manually and correct mistaken events without deleting history | 1A |
| FR-14 | User creates and completes recruiting actions and follow-ups with due dates, including upcoming interviews and assessment deadlines | 1A |
| FR-15 | Contacts, contact-company links, contact-opportunity links and interactions are first-class and manually editable | 1A |
| FR-16 | User connects Gmail with read-only access and can disconnect at any time | 1B |
| FR-17 | *(modified)* System syncs new mail incrementally **about every 12 hours (configurable)** plus on-demand "Sync now", detects recruiting mail and classifies it | 1B |
| FR-18 | System matches recruiting mail to company, opportunity, application and contact | 1B |
| FR-19 | *(modified)* **Every Gmail finding that would create or change a career record** becomes a review item with Confirm, Edit + Confirm, Reject / Ignore; confirmed items run the normal deterministic commands | 1B |
| FR-20 | *(modified)* Home answers "what deserves my attention now?" **from the end of the manual Applications workflow onward**, and is enriched by Gmail in 1B without a separate architecture | 1A, enriched 1B |
| FR-21 | Opportunity chat always has an explicit active opportunity shown in the UI; Home chat has no active opportunity | 1A |
| FR-22 | Home and opportunity chat share one context-builder and model boundary | 1A |
| FR-23 | Strategy rules are user data, scoped globally, to a company or to a lane | 1A, basic |
| FR-24 | *(modified)* AI drafts outreach text; the user copies or sends it themselves. Now covered by FR-34 | 1B |
| FR-25 | Versioned communication templates | Deferred |
| FR-26 | Follow-up priority scoring (distinct from fit) | Deferred; outreach reasons (FR-33) cover the Phase 1 need |
| FR-27 | Automated job discovery through source adapters | Deferred; boundary exists |
| FR-28 | Projects/GitHub, DSA, System Design, Speaking, Behavioral, Market Learning, voice | Deferred; module boundary only |
| FR-29 | *(new)* First-class, user-editable Skill Inventory: canonical name, aliases, confirmation status, linked evidence, optional note, last-updated time. User can add, edit, confirm, reject, merge and mark a real gap | 1A |
| FR-30 | *(new)* A skill may have evidence from several contexts; the system derives a current skill assessment from all confirmed evidence without discarding any source | 1A |
| FR-31 | *(new)* Minimal Skills UI: list, search and filter, classification, evidence sources, resumes exposing the skill, add, correct, merge, mark gap, change classification with explicit confirmation | 1A |
| FR-32 | *(new)* Skill feedback loop: when the user answers a clarification in chat, the system proposes a durable skill-evidence update through Review; once confirmed, all future evaluations use it | 1A |
| FR-33 | *(new)* Outreach recommendation per opportunity and contact: worthwhile, optional, or not now, with interpretable reasons and no numeric certainty score | 1B |
| FR-34 | *(new)* Outreach drafting grounded in the opportunity, contact, confirmed evidence, company history, prior interactions and strategy rules; no invented experience or relationships; never sent by the system | 1B |
| FR-35 | *(new)* Contact email addresses are entered manually (or confirmed from Gmail) with their source recorded; an enrichment-provider boundary exists but no provider is built | 1A manual; provider deferred |
| FR-36 | *(new)* Gmail proposes relationship events (a contact replied, an email belongs to a contact) only when the email itself supports them | 1B |
| FR-37 | *(new)* User-set priority on opportunities and strategic priority on companies (three levels each) feed Home and outreach reasoning | 1A |
| FR-38 | *(new)* The contact and interaction model can later attach networking events (event, person met, follow-up, referral) through additive changes only | Deferred; boundary only |

### 1.2 Non-functional requirements

- **NFR-01 Isolation:** no user can read, infer or modify another user's data through any API, job, prompt or log.
- **NFR-02 Least privilege:** each integration requests the narrowest scope that supports the approved behavior.
- **NFR-03 Secret handling:** OAuth tokens and secrets are encrypted at rest and never enter LLM context, logs, error reports or the frontend.
- **NFR-04 Latency:** deterministic reads and writes target p95 under 300 ms server time on MVP data volumes (assumption, to be measured).
- **NFR-05 Progress:** any LLM work over about 2 seconds runs as a job or stream with visible progress; the UI never blocks.
- **NFR-06 Provider independence:** domain code depends on an internal model interface, not a vendor SDK.
- **NFR-07 Reproducibility:** every LLM-derived record stores prompt version, model, and a context manifest of the records it used.
- **NFR-08 Deletion:** a user can delete their account and all derived data; deletion covers the database and object storage.
- **NFR-09 Observability:** failures are diagnosable from IDs, timings and error codes without reading career or email content.
- **NFR-10 Understandability:** one language per tier, explicit SQL-friendly schema, reviewable migrations, ADRs for consequential choices.
- **NFR-11 Cost control:** LLM calls are bounded per user and per job; deterministic filters run before any model call.
- **NFR-12 Testability:** the LLM and Gmail are replaceable with deterministic fakes in tests.

### 1.3 Invariants

1. **INV-01** No creator career data in source, prompts, schemas, seeds, fixtures used by production code, or defaults. Only the attribution string is static.
2. **INV-02** Every user-owned row carries `user_id`; every cross-entity reference stays within one user (enforced by composite foreign keys).
3. **INV-03** An Application exists only after a user Apply action or a confirmed ReviewItem.
4. **INV-04** DomainEvents are append-only. Corrections are new events that void earlier ones.
5. **INV-05** Uploaded artifacts are immutable. The system never rewrites a user's resume.
6. **INV-06** No autonomous external side effects: no sending, submitting, deleting or modifying anything outside Career OS.
7. **INV-07** The LLM never writes domain state directly. Its output is validated, then applied by deterministic code. Evidence, skills, applications, contacts and interactions change only through a user action or a confirmed ReviewItem. JD extraction may populate Opportunity, Qualification and Company fields as `extracted` origin because they describe the posting, not the user, and every such field is user-editable.
8. **INV-08** A Claim's evidence class and engagement type are set or raised only by the user; the model may only propose them.
9. **INV-09** Generated text cannot present evidence beyond its class's permitted uses (checked deterministically after generation).
10. **INV-10** Opportunity chat always names its active Opportunity; a message cannot be scoped to an Opportunity the user does not own.
11. **INV-11** Tokens and secrets are unreachable from the LLM layer by construction (separate table, separate repository, no serializer).
12. **INV-12** Deleting User A and registering User B with a different career requires no code change (portability test, section 11).
13. **INV-13** Absence of evidence is not a Gap. A Skill is a Gap only when the user marks it so; otherwise it is Not recorded.
14. **INV-14** Chat statements never change evidence directly. They become ReviewItems that the user confirms, edits or rejects.
15. **INV-15** An outreach draft may cite only evidence and Interactions present in its context manifest, and is never sent by the system.
16. **INV-16** *(rev 3)* Engagement type is never dropped. Professional evidence is described or counted as full-time only when its engagement type is confirmed `full_time`, `part_time` or `contract`; `internship` is always named as internship; `unspecified` is treated conservatively (not counted toward years of experience, never called full-time).
17. **INV-17** *(rev 3)* No hidden model work. Model calls happen only on an explicit user action (upload, ingest, evaluate, chat, recommend, draft) or scheduled Gmail classification within per-sync and per-day caps. Data changes only mark Evaluations stale.
18. **INV-18** *(rev 3)* Every entity ID read from JSONB, arrays, job payloads or client input is re-resolved through a user-scoped repository before use, because foreign keys do not protect those references.

### 1.4 Constraints

- No LinkedIn scraping or unofficial API use. LinkedIn data enters manually or semi-manually.
- No new infrastructure without a concrete requirement and an ADR.
- Gmail is read-only in Phase 1.
- A single match percentage is not ground truth and is not produced in Phase 1.
- No final weights for fit or priority in Phase 0 or Phase 1.

### 1.5 Explicitly deferred

Automated job discovery and Startup Hunter; JD fetching from URLs; versioned communication templates; contact-enrichment and email-discovery providers (boundary only, no provider); follow-up priority scoring; semantic retrieval with embeddings; Gmail push notifications; Gmail draft creation and label writing; the Events/networking module (boundary only); all non-Applications modules; voice; teams or shared workspaces; billing; mobile apps.

### 1.6 Ambiguities (resolved by default unless the owner objects)

| Ambiguity | Default taken in this spec |
| --- | --- |
| Can an opportunity have more than one application? | At most one non-terminal application per opportunity; a re-application after rejection is a new application row on the same opportunity only if the same posting is reopened. Otherwise it is a new opportunity. |
| Are resume-extracted claims and skills usable before the user confirms them? | Yes as unverified, at their extracted class or lower; they are marked unverified in context and in output. Listed in section 17 (O-8). |
| Is internship a sixth evidence class? | No (decided, O-10): internship is professional evidence with `engagement_type = internship`, and permitted uses distinguish it. |
| If a JD skill is missing from the selected resume, is it a gap? | No (INV-13). The Skill Inventory is checked first; with no evidence the qualification is "not recorded" and becomes a clarification question. |
| Does a casual chat statement ("I used Excel at work") count as evidence? | Only after the user confirms a structured proposal that names the skill, class, engagement type and their own words. |
| What makes an external event reliable enough to create an Application? | Nothing automatically. A Gmail acknowledgement produces a review item proposing the application. |
| Is Company global or per user? | Per user in Phase 1. Listed in section 17 (O-7). |
| Does connection-request activity belong in application history? | It is stored as an Interaction; when linked to an application it also emits an application event that references the interaction, so the application timeline stays one ordered stream. |
| How does the user state a strategy? | Free-text rules with optional structured conditions. Structured ones are checked in code; free-text ones are passed to the model as rules. |

## 2. Proposed system architecture

The smallest coherent architecture is one deployable codebase running as two processes (API and worker) over one PostgreSQL database and one object store. The API never waits on Gmail or slow model calls; it writes a job row and returns, or streams.

```mermaid
flowchart TB
  SPA["Browser: React SPA (TypeScript)"] -->|HTTPS + SSE, cookie session| API["API process (FastAPI)"]
  API -->|login only| G["Google sign-in (OIDC)"]
  W["Worker process (same codebase)"] -->|read-only sync| GM["Gmail API (gmail.readonly)"]
  W -->|bounded context| LLM["LLM provider"]
  API -->|state, events, jobs| PG[("PostgreSQL: system of record")]
  W -->|claims jobs| PG
  PG --- OS[("Object storage: immutable artifacts")]
```

The worker and API share the same domain services; only the entry point differs. The job queue lives in Postgres, so a job and the state it changes commit in one transaction.

### 2.1 Components and responsibilities

| Component | Responsibility | Boundary rule |
| --- | --- | --- |
| Frontend SPA | Rendering, local UI state, active-opportunity header, streaming display | Holds no secrets; talks only to the Career OS API; renders model output as sanitized markdown with remote images blocked |
| API process | Auth, request validation, commands and queries, chat streaming, job enqueueing | Every handler resolves the current user from the session and passes it into services explicitly |
| Domain services | Business rules and state machines per module | Services own their tables; other modules call the service, never its repository |
| Skill inventory service | Skills, aliases, merges, gap markers, derived assessment, resume exposure | The only writer of skills and claim-skill links; evidence class changes require a user command |
| Event log | Append-only `domain_events` written in the same transaction as the state change | Never updated; corrections are new events |
| Review inbox | Holds proposals from Gmail, resume extraction and chat until the user confirms | Confirmation calls the same command a manual action would |
| Attention providers | Each module publishes typed attention items (due action, pending review, stage change, decision needed) that Home ranks | Deterministic queries only; Gmail and future modules add providers without changing Home |
| Context builder | Assembles bounded, typed context packages per request scope and intent | Reads through services; returns IDs plus a manifest; never touches credentials |
| Outreach advisor | Computes deterministic outreach signals, asks the model for a recommendation and optional draft | Produces recommendations and drafts only; never sends; records outreach only when the user says it was sent |
| Model gateway | One internal interface for structured output and streaming; prompt registry; validation; run records | Only module that imports a vendor SDK |
| Integration boundary | Adapters per external source: Gmail now; contact enrichment, LinkedIn manual import, job sources and GitHub later | Adapters emit normalized source records; the domain never sees vendor payloads; no provider is coupled to the domain |
| Credential vault | Encrypt, decrypt and refresh OAuth tokens | Separate table and repository; only integration adapters may call it |
| Worker | Runs queued and scheduled jobs with retries and idempotency keys | Same code, separate process; can be scaled independently later |
| PostgreSQL | System of record: state, events, jobs, sessions, encrypted tokens, full-text indexes | Single database, shared schema, `user_id` on every owned row |
| Object storage | Immutable binary artifacts | Private bucket; access only through the API with short-lived signed URLs or streamed responses |

### 2.2 Request styles

- **Deterministic reads and writes:** synchronous HTTP, direct SQL, no model call.
- **Fast AI tasks** (JD extraction, email classification): queued jobs using a fast model tier; the UI polls or receives a status update.
- **Reasoning tasks** (evaluation, chat): streamed over Server-Sent Events from the API; long evaluations can also run as jobs and notify on completion.
- **External sync:** scheduled worker jobs; the user can also trigger "sync now".

### 2.3 Future modules

Projects/GitHub, DSA, System Design, Speaking, Behavioral and Market Learning each become a new backend package with its own tables, services and context providers. They plug into Home by publishing attention items and into chat by registering context providers. None of them needs new infrastructure by default.

## 3. Technology recommendation

Recommended stack: **Python 3.12 + FastAPI + SQLAlchemy 2 + Alembic + Pydantic v2** on the backend, **React + TypeScript + Vite** on the frontend, **PostgreSQL 16**, an **S3-compatible bucket**, and a **Postgres-backed job queue**. Every choice below lists what it beats and what it costs.

| Layer | Recommendation | Why | Alternatives considered | Tradeoff accepted |
| --- | --- | --- | --- | --- |
| Backend language | Python 3.12 | Strongest LLM, PDF/DOCX parsing and Google client ecosystem; matches a data/ML background; readable for a learner | TypeScript everywhere (one language, shared types); Java/Spring (mature, heavier) | Two languages across tiers; types bridged by generated OpenAPI client |
| Web framework | FastAPI | Explicit request models, OpenAPI for free, async streaming (SSE), small surface | Django (batteries, heavier ORM and admin coupling); Flask (less typing) | Fewer built-ins; auth and admin are assembled, not given |
| ORM and migrations | SQLAlchemy 2 (typed) + Alembic | Explicit SQL when needed, reviewable migration files, composite foreign keys supported | Django ORM; raw SQL + a migration tool; SQLModel (thinner, less mature) | More boilerplate than Django; worth it for control |
| Validation | Pydantic v2 | Same models validate API input and LLM structured output | attrs/marshmallow | None significant |
| Database | PostgreSQL 16 | Relational integrity, JSONB for typed payloads, full-text search, `SKIP LOCKED` queues, pgvector available later without a new service | MongoDB (weaker cross-entity integrity for a relational domain); SQLite (no concurrent worker story, no pgvector parity) | Needs a managed instance in production |
| Semantic retrieval | Not in Phase 1. Postgres full-text search plus normalized skill tags | Phase 1 retrieval is mostly exact and small per user; embeddings add cost and eval burden before a measured gap | pgvector now; dedicated vector DB | Some paraphrase matches missed until pgvector is justified (ADR-010) |
| Job queue | Postgres table + worker loop using `FOR UPDATE SKIP LOCKED`; library choice (`procrastinate` or a small in-house module) settled in Task 1 | Jobs commit atomically with state; no Redis; easy to inspect with SQL | Celery + Redis; RQ; Temporal; cloud queues | Lower throughput ceiling, far above MVP needs |
| Scheduling | Worker-side scheduler ticks writing jobs | One process type, no cron service | Platform cron; Celery beat | Must guard against duplicate ticks with unique job keys |
| Frontend | React + TypeScript + Vite SPA, TanStack Query, React Router | Clean server boundary, simple mental model, no server components to learn | Next.js (SSR and server actions blur the backend boundary); HTMX + server templates (simpler, weaker for streaming chat UX) | Separate build; no SEO (not needed) |
| API contract | OpenAPI generated from FastAPI; typed TS client generated in CI | One source of truth for request and response shapes | Hand-written client; tRPC (TS-only) | A codegen step |
| Authentication | Google OIDC sign-in via Authlib; server-side sessions in Postgres; httpOnly, Secure, SameSite=Lax cookie; CSRF token for mutations | Users already need Google for Gmail; no third-party auth vendor; session revocation is a row delete | Managed auth (Clerk, Auth0, Supabase Auth); JWT-only sessions | We own session security; must be tested carefully (ADR-004) |
| Artifact storage | S3-compatible private bucket in production; local filesystem adapter in development | Cheap, standard, provider-portable | Postgres large objects; cloud-specific blob APIs | One more credential to manage |
| Document parsing | `pypdf` or `pdfplumber` for PDF, `python-docx` for DOCX, run in the worker with size and page limits | Pure-Python, no external service | Hosted document AI | Weak on scanned PDFs; OCR deferred |
| LLM access | Internal `ModelGateway` interface with one vendor adapter (Anthropic suggested) plus a deterministic fake | Satisfies provider independence without a router | LangChain/LlamaIndex (large abstraction surface, harder to learn from); multi-provider router | Adapter written by hand; small |
| Encryption of tokens | Envelope encryption: AES-256-GCM data key per record, key-encryption key from environment secret now, cloud KMS later | Tokens useless if the database leaks alone | Plaintext with DB-level encryption only | Key rotation procedure must be documented |
| Hosting | One container image, two process types, on a PaaS; managed Postgres; managed bucket | Lowest operations load; no Kubernetes | Self-managed VM; Kubernetes; serverless functions (awkward for workers and SSE) | Some vendor coupling at the deploy layer only |
| Local development | Docker Compose: Postgres + API + worker + frontend dev server | One command to run everything | Local installs | Docker required |
| Quality gates | Ruff, mypy (strict on domain packages), pytest; ESLint, TypeScript strict, Vitest, Playwright; gitleaks pre-commit and in CI | Fast feedback, enforce no secrets | Fewer tools | Some setup time in Task 1 |

Provider-specific hosting, database and bucket vendors are listed in section 13 as options only; the choice is an open decision because it sets recurring cost.

## 4. Domain model

The model has 31 tables in Phase 1: 28 in Phase 1A and 3 more for Gmail in Phase 1B (section 4.9 audits each one). Every table except `users` is owned by exactly one user, and every foreign key between owned tables includes `user_id`, so a cross-user reference cannot be written even by a buggy query.

### 4.1 Conventions

- **IDs:** UUIDv7 primary keys (time-ordered, safe to expose, no enumeration).
- **Ownership:** `user_id NOT NULL` on every owned table; unique constraint `(user_id, id)`; child foreign keys are composite, e.g. `(user_id, opportunity_id) REFERENCES opportunities(user_id, id)`.
- **IDs outside foreign keys** *(rev 3)*: IDs stored in JSONB, arrays (e.g. evaluation `skill_ids`), job payloads and review payloads are not FK-protected. They are always re-resolved through a user-scoped repository before use (INV-18), and a missing or foreign ID is treated as not found.
- **Time:** `timestamptz` everywhere. Events carry `occurred_at` (when it happened in the world) and `recorded_at` (when Career OS learned it).
- **Enums:** Postgres `text` with `CHECK` constraints, mirrored by Python enums; extended by additive migrations.
- **JSONB:** allowed only for typed payloads validated by a named Pydantic schema with a `schema_version`. Anything filtered or joined on gets a real column.
- **Schema evolution** *(rev 3)*: mutable rows with an old JSONB `schema_version` are converted by Alembic data migrations. Immutable rows (DomainEvents, Evaluations, LLM runs) are never rewritten; readers upcast every historical `schema_version` in code, and upcasters are covered by tests.
- **State versions** *(rev 3)*: every aggregate with a state machine (opportunities, applications, recruiting\_actions, review\_items, skills, claims) carries `state_version` for optimistic concurrency.
- **Soft vs hard delete:** user-initiated deletion is hard delete. `archived_at` exists for hide-without-delete.
- **Provenance columns:** LLM-derived rows carry `origin` (`user`, `extracted`, `chat`, `gmail`, `system`), `llm_run_id` and, where relevant, `confirmation_status`.

### 4.2 Identity and access

| Entity | Purpose | Key fields | Relationships | Lifecycle and constraints |
| --- | --- | --- | --- | --- |
| User | Account root | id, primary\_email, display\_name, status, created\_at, deleted\_at | Owns everything | `active` → `deletion_requested` → hard-deleted by a job. Not user-owned itself |
| AuthIdentity | Login identity from a provider | user\_id, provider, provider\_subject, email\_at\_login | User 1..n | Unique (provider, provider\_subject). Holds no tokens |
| Session | Server-side session | id\_hash, user\_id, created\_at, expires\_at, last\_seen\_at, user\_agent\_hash | User 1..n | Cookie holds a random ID; only its hash is stored. Revoked by delete |
| Integration | A connected external account | user\_id, provider (`gmail`), external\_account\_email, status, granted\_scopes\[\], sync\_cursor, last\_synced\_at, last\_error\_code | User 1..n; IntegrationCredential 1..1 | `pending` → `active` → `needs_reauth` / `disconnected`. One active Gmail integration per user in Phase 1 |
| IntegrationCredential | Encrypted OAuth refresh token | integration\_id, user\_id, ciphertext, wrapped\_data\_key, key\_version, token\_expires\_at | Integration 1..1 | Never loaded by default queries; only the credential vault reads it. Deleted on disconnect |
| ExternalRef | Maps an external identifier to an internal entity for idempotency and dedup | user\_id, source, external\_id, entity\_type, entity\_id | Any entity | Unique (user\_id, source, external\_id). Phase 1: Gmail message IDs. Later: source adapters and enrichment providers |

### 4.3 Career identity, skills and evidence

| Entity | Purpose | Key fields | Relationships | Lifecycle and constraints |
| --- | --- | --- | --- | --- |
| Profile | Primary career identity (one per user) | headline, summary, current\_location, relocation\_preference, remote\_preference, work\_authorization (typed JSONB), constraints\_updated\_at (bumped only by location, remote and authorization edits), target\_roles (typed JSONB list: name, priority, notes), communication\_preferences (typed JSONB: tone, length, sign-off, things to avoid) | User 1..1 | Always user-edited; never overwritten by extraction. Target roles and communication preferences are user data with no defaults |
| Artifact | Immutable stored file or text snapshot | kind (`resume_file`, `jd_snapshot`, `email_excerpt`, `reference`), storage\_key, sha256, mime\_type, byte\_size, original\_filename, extracted\_text, extraction\_status | Resume, Opportunity, Interaction | Never modified after upload. Replacement = new artifact. Unique (user\_id, sha256, kind) |
| Resume | A user's resume document | artifact\_id, label, lane\_id (nullable), parsed\_outline (typed JSONB), status (`active`, `archived`) | Artifact 1..1; ResumeLane n..1; Claim via EvidenceSource | Parsed outline is derived and re-derivable; the file is authoritative |
| ResumeLane | Truthful alternative presentation for an opportunity category | name, description, emphasis\_notes, target\_role\_labels text\[\], default\_resume\_id, status, updated\_at | Resume 1..n | A lane cannot create claims or skills; it only selects and orders existing ones |
| Skill | *(new)* One skill in the user's inventory, independent of any resume | canonical\_name, normalized\_key, aliases text\[\], confirmation\_status (`proposed`, `confirmed`, `rejected`), user\_marked\_gap, gap\_note, user\_note, origin (`user`, `extracted`, `chat`), merged\_into\_skill\_id, updated\_at (also bumped when linked claims or their sources change) | ClaimSkill 1..n; Claims through ClaimSkill | Partial unique (user\_id, normalized\_key) where not merged; alias collisions checked by the service in the same transaction. Merge re-points claim links and keeps the merged row as a redirect. Assessment is derived, never stored (4.3.2) |
| Claim | One career statement that can be cited | statement, evidence\_class, engagement\_type (required when class is `professional`: full\_time, part\_time, contract, internship, unspecified), confirmation\_status, start\_date, end\_date, organization\_label, origin, llm\_run\_id | EvidenceSource 1..n; ClaimSkill 1..n | confirmation\_status: `proposed` → `confirmed` / `rejected`; edits are CLAIM\_EDITED events, not a status. Class and engagement type set or raised only by the user (INV-08). An unconfirmed professional claim whose source text does not state the engagement type is extracted as `unspecified` |
| EvidenceSource | Where a claim comes from | claim\_id, source\_type (`resume`, `project_url`, `user_assertion`, `artifact`), artifact\_id, message\_id (chat assertions), locator, url, assertion\_text | Claim n..1 | At least one per claim. A chat assertion keeps the user's own words verbatim |
| ClaimSkill | *(modified)* Links a claim to a Skill | claim\_id, skill\_id | Claim n..m Skill | Now a composite FK to `skills` instead of a free-text key, so evidence is attached to the inventory |

#### 4.3.1 Evidence classes and the internship question

Claims use four evidence classes; the fifth category, Gap, is a skill-level marker because a gap is the absence of evidence, not a piece of it. The five categories therefore appear consistently wherever skills are shown: Professional, Academic / Research, Project, Learning, Gap.

| Claim evidence\_class | engagement\_type | May be described as | May not be described as |
| --- | --- | --- | --- |
| `professional` | `full_time`, `part_time`, `contract` | Professional experience, with the engagement type stated when relevant; counts toward years-of-experience requirements | Full-time, if the type is part-time or contract |
| `professional` | `internship` | Internship experience at the named organization; industry exposure | Full-time or ordinary professional employment; never counted toward years-of-experience requirements |
| `professional` | `unspecified` | Experience at the named organization | Full-time experience; not counted toward years-of-experience requirements until the user sets the type |
| `academic_research` | n/a | Research or academic work | Professional experience |
| `project` | n/a | Project work built or shipped by the user | Professional or production experience |
| `learning` | n/a | Currently learning, coursework, exposure | Experience of any kind |

Decision (O-10, locked): internship is `professional` with `engagement_type = internship`, not a sixth class. An internship is real employment at a real organization; the truthful difference is the terms of employment. The risk is code that reads `evidence_class = professional` alone and over-counts internships. Mitigations: permitted-use checks, years-of-experience logic, prompts and the Skills UI always read the pair (class, engagement type) (INV-16); the evaluation's professional-evidence component reports full-time and internship evidence separately; there is no per-evaluation opt-in to count internships, which keeps the rule simple and testable.

#### 4.3.2 Derived skill assessment

Computed by a SQL query or view on read, so it can never go stale:

- **Evidence badges:** every class present among the skill's non-rejected claims, each marked confirmed or unverified. Python can show Professional, Academic / Research and Project at once.
- **Headline category:** the strongest confirmed class in the order professional (full-time/part-time/contract) > professional (internship) > academic/research > project > learning. The order is for display only; evaluations read all badges.
- **Gap:** shown when the user marked the gap. Marking a gap is refused while confirmed academic, project or professional evidence exists; the user must reject or downgrade that evidence first. Learning evidence may coexist with a gap marker ("learning, not yet able to claim it").
- **Not recorded:** no claims and no gap marker. Never treated as a gap (INV-13).
- **Recency:** latest end date among supporting claims (open-ended counts as current).
- **Resume exposure:** resumes whose claims support the skill ("stated"), plus resumes whose extracted text mentions the canonical name or an alias ("mentioned"), computed with Postgres full-text search on demand.

### 4.4 Market: companies, opportunities, evaluation

| Entity | Purpose | Key fields | Relationships | Lifecycle and constraints |
| --- | --- | --- | --- | --- |
| Company | A company in the user's world | name, normalized\_name, aliases\[\], domains\[\], careers\_url, strategic\_priority (`high`, `normal`, `low`; user-set, default `normal`), notes | Opportunity, Contact (via ContactCompany), Interaction | Unique (user\_id, normalized\_name). Merge re-points children and records a merge event |
| Opportunity | A job posting the user may act on | company\_id, title, team, external\_job\_id, location\_text, locations (typed JSONB), workplace\_type, source, source\_url, jd\_artifact\_id, status, priority (`high`, `normal`, `low`; user-set), extraction\_status, content\_updated\_at (bumped by JD field or qualification edits), discovered\_at, latest\_evaluation\_id, state\_version | Company n..1; Qualification 1..n; Evaluation 1..n; Application 0..n | State machine in section 5. Partial unique (user\_id, company\_id, external\_job\_id) when job ID present; fuzzy duplicate check otherwise |
| Qualification | One requirement line from a JD | opportunity\_id, kind (`minimum`, `preferred`), ordinal, text\_verbatim, category (`skill`, `experience`, `education`, `domain`, `authorization`, `location`, `other`), skill\_keys\[\] (JD vocabulary), min\_years, is\_hard\_constraint | Opportunity n..1 | Verbatim text always kept; normalized fields derived and editable. JD skill keys are mapped to inventory Skills at evaluation time via normalized key and aliases |
| Evaluation (`opportunity_evaluations`) | One immutable evaluation run | opportunity\_id, recommended\_lane\_id, recommended\_resume\_id, recommendation (`apply`, `save`, `skip`, `needs_info`), summary, components (typed JSONB), qualification\_assessments (typed JSONB), open\_questions (typed JSONB), basis: skill\_ids uuid\[\], unmatched\_skill\_keys text\[\], lane\_ids uuid\[\], resume\_ids uuid\[\]; llm\_run\_id, created\_at | Opportunity n..1; LlmRun 1..1 | Never edited. Components cover ten dimensions: lane alignment, core skills, experience and seniority, domain, professional evidence (full-time and internship reported separately), project evidence, location, work authorization, critical missing requirements, career direction. Assessment status per qualification: `met`, `partial`, `not_recorded`, `gap` (user-marked), `blocked` (hard constraint fails). Every cited ID is validated at write time. Staleness is computed from the basis (6.2c). The context manifest lives on the LLM run, not here |

### 4.5 Applications, actions, events

| Entity | Purpose | Key fields | Relationships | Lifecycle and constraints |
| --- | --- | --- | --- | --- |
| Application | The user actually applied | opportunity\_id, resume\_id, lane\_id, applied\_at, channel, stage (materialized), is\_terminal, state\_version | Opportunity n..1; events; RecruitingAction | Created only by Apply or a confirmed review item. Partial unique: one non-terminal application per opportunity |
| DomainEvent | Append-only history for all aggregates | aggregate\_type (`opportunity`, `application`, `recruiting_action`, `skill`, `claim`, `contact`, `company`), aggregate\_id, event\_type, occurred\_at, recorded\_at, actor (`user`, `system`, `gmail`), source\_ref\_id, payload (typed JSONB), voids\_event\_id, correlation\_id | Any aggregate | Insert-only for the app role. Written in the same transaction as the state change. Evidence-class and skill changes are logged here, so every classification change has an auditable author |
| RecruitingAction | *(modified)* To-do, follow-up, scheduled commitment, or outreach | kind (`follow_up`, `reply`, `complete_assessment`, `attend_interview`, `schedule_interview`, `outreach`, `custom`), title, due\_at (deadline or scheduled time), status, snoozed\_until, sequence\_no, opportunity\_id, application\_id, contact\_id, interaction\_id, origin; for `outreach` only: recommendation\_llm\_run\_id, draft\_subject, draft\_body, draft\_llm\_run\_id, draft\_updated\_at | Optional links to opportunity, application, contact, interaction | State machine in section 5. Upcoming interviews and assessment deadlines are actions with `due_at`, so Home needs no calendar table. Earlier draft versions remain recoverable from `llm_runs` |
| ReviewItem | *(modified)* Proposal awaiting human confirmation | source (`gmail`, `extraction`, `chat`), proposal\_type (`claim`, `skill`, `skill_evidence`, `create_application`, `application_event`, `interaction`, `contact_link`, `contact_email`), proposed\_payload (typed JSONB), confidence, rationale, evidence\_ref\_id, status, decided\_at | ExternalRef or Message; produced events | `pending` → `confirmed` / `rejected` / `expired`. Actions offered: Confirm, Edit + Confirm, Reject / Ignore. Confirming runs the same command as a manual action |

### 4.6 Relationships and interactions

| Entity | Purpose | Key fields | Relationships | Lifecycle and constraints |
| --- | --- | --- | --- | --- |
| Contact | *(modified)* A person in the user's network | full\_name, emails (typed JSONB list: address, source `manual`/`gmail`/`provider`, added\_at), linkedin\_url (manually entered), headline, notes, source (`manual`, `gmail`, `import`) | ContactCompany, ContactOpportunity, Interaction | GIN index on emails; the service enforces one contact per address per user inside the write transaction. Merge operation like Company |
| ContactCompany | Contact's relation to a company | contact\_id, company\_id, relation (`employee`, `recruiter`, `former_employee`, `agency_recruiter`, `other`), title, is\_current | Contact n..m Company | Many per contact over time |
| ContactOpportunity | Contact's role on an opportunity | contact\_id, opportunity\_id, role (`recruiter`, `hiring_manager`, `referrer`, `interviewer`, `team_member`, `other`) | Contact n..m Opportunity | Unique (contact, opportunity, role). Drives outreach routing checks |
| Interaction | One communication, any channel | channel (`email`, `linkedin`, `phone`, `in_person`, `other`), direction, occurred\_at, contact\_id, company\_id, opportunity\_id, application\_id, summary, artifact\_id, external\_ref\_id | Contact, Company, Opportunity, Application | Channel-agnostic by design (see 4.10). Linked to an application → also writes a referencing application event. Relationship strength is derived by query, not stored |

### 4.7 Strategy, AI runs, chat

| Entity | Purpose | Key fields | Relationships | Lifecycle and constraints |
| --- | --- | --- | --- | --- |
| StrategyRule | User-authored decision rule | scope (`global`, `company`, `lane`), company\_id, lane\_id, statement, rule\_type (`constraint`, `preference`, `cooldown`), condition (typed JSONB, optional), active | Company, ResumeLane | Structured conditions checked in code (application cooldowns, outreach cooldowns); statements passed to the model as rules. Decisions themselves are events |
| LlmRun | Record of one model call | purpose (`extract_resume`, `extract_jd`, `classify_email`, `evaluate`, `chat`, `propose_skill_evidence`, `outreach_recommendation`, `outreach_draft`), prompt\_id, prompt\_version, provider, model, input\_tokens, output\_tokens, latency\_ms, status, error\_code, context\_manifest, output (typed JSONB) | Referenced by derived rows | User-owned and deleted with the user. Stores structured output, not raw prompts, by default |
| Conversation | A chat thread with an explicit scope | scope (`home`, `opportunity`), opportunity\_id (required iff scope = opportunity), title | Messages | Scope fixed at creation |
| Message | One chat turn | conversation\_id, role, content, llm\_run\_id (the manifest lives on the LLM run) | Conversation n..1; EvidenceSource (chat assertions) | Content is user data; never logged. A user message can be the cited source of a confirmed skill assertion |
| Job | Queued or scheduled work | kind, user\_id (nullable for system ticks), payload (IDs only), status, attempts, run\_after, unique\_key, last\_error\_code | Any | Payload holds IDs, never content or tokens |

### 4.8 Consolidations and splits made

- **FollowUp merged into RecruitingAction** as `kind = follow_up` with `sequence_no`.
- **Decision merged into DomainEvent** as `OPPORTUNITY_DECIDED`. StrategyRule stays separate.
- **ExternalIdentity split in two:** AuthIdentity (who can log in) and ExternalRef (which external record maps to which internal entity).
- **ApplicationEvent generalized to DomainEvent** so every aggregate, now including skills and claims, shares one history.
- **ReviewItem** is the single human-confirmation mechanism for Gmail, extraction and chat.
- *(rev 2)* **Skill added** as a first-class table; ClaimSkill now references it. Aliases are an array column, not a table.
- *(rev 2)* **Gap moved from a claim class to a skill marker.** A claim describes something you have; a gap is its absence.
- *(rev 2)* **Internship is an engagement type on professional claims**, not a new class (pending O-10).
- *(rev 2)* **TargetRole and lane\_target\_roles merged** into a Profile JSONB list and a lane label array; nothing queried them relationally.
- *(rev 2)* **EvaluationComponent and QualificationAssessment merged** into typed JSONB on the immutable evaluation; integrity is enforced by write-time validation against the manifest.
- *(rev 2)* **Outreach recommendations and drafts need no new tables:** recommendations are LlmRun outputs referenced from an `outreach` RecruitingAction, which also carries the current draft.
- *(rev 2)* **Contact emails stay on Contact** as a typed list with per-address source, instead of a contact\_emails table.
- **Deferred tables:** CommunicationTemplate, PriorityScore, SourceAdapterRun, NetworkingEvent, enrichment results, global company directory.

### 4.9 Phase 1 complexity audit

Every table was asked whether it earns its implementation cost before Career OS becomes useful. Result: 28 essential (3 of them only needed in Phase 1B and built then), 3 justified supporting infrastructure, 4 removed by merging, and nothing the approved workflow needs was deferred.

| Table | Class | Earns its cost because | Built in |
| --- | --- | --- | --- |
| users | Essential now | Account root; ownership anchor | T2 |
| jobs | Justified supporting | Async parsing, extraction, sync and deletion without Redis | T2 |
| domain\_events | Essential now | Append-only history is an approved invariant | T2 |
| auth\_identities | Essential now | Login mapping; a second provider needs no schema change | T3 |
| sessions | Justified supporting | Server-side revocation is simpler and safer than JWT revocation | T3 |
| profiles | Essential now | Primary identity, constraints, target roles, communication preferences | T4 |
| artifacts | Essential now | Immutable originals, dedup, provenance target | T4 |
| resumes | Essential now | Multiple resumes and lane assignment | T4 |
| resume\_lanes | Essential now | Lane recommendation is an approved output | T4 |
| review\_items | Essential now | Human confirmation for extraction, chat and Gmail | T5 |
| llm\_runs | Justified supporting | Reproducibility, cost tracking, manifests, provenance of every derived row | T5 |
| companies | Essential now | Company history and routing | T6 |
| opportunities | Essential now | Core domain | T6 |
| qualifications | Essential now | Per-requirement matching against skills; verbatim retention | T6 |
| applications | Essential now | Core domain | T7 |
| recruiting\_actions | Essential now | Follow-ups, interviews, deadlines, outreach drafts | T8 |
| contacts | Essential now | Relationships and outreach | T8 |
| contact\_companies | Essential now | "Who do I know at this company" | T8 |
| contact\_opportunities | Essential now | Recruiter, hiring manager and referrer routing | T8 |
| interactions | Essential now | Relationship history, previous outreach | T8 |
| strategy\_rules | Essential now (small) | Cooldowns and constraints are approved requirements | T8 |
| skills | Essential now | Skill Inventory is a core requirement | T9 |
| claims | Essential now | Citable evidence with class and engagement type | T9 |
| evidence\_sources | Essential now | Provenance; one claim can have several sources | T9 |
| claim\_skills | Essential now | Connects evidence to inventory; without it skills lose provenance | T9 |
| opportunity\_evaluations | Essential now | Immutable, interpretable Evaluations with a staleness basis | T11 |
| conversations | Essential now | Fixed chat scope enforces the active-opportunity rule | T11 |
| messages | Essential now | Chat history; source for skill assertions | T11 |
| integrations | Essential in 1B | Gmail connection state and cursor | T12 |
| integration\_credentials | Essential in 1B | Physically separates tokens from anything the LLM layer reads | T12 |
| external\_refs | Essential in 1B | Gmail idempotency; job IDs already live on opportunities | T12 |

Removed by merging: target\_roles, lane\_target\_roles, evaluation\_components, qualification\_assessments. Considered and not added: skill\_aliases, contact\_emails, drafts, outreach\_recommendations, networking\_events.

### 4.10 Events and networking extension boundary

A future Events module must support Event → person met → Interaction → Company → follow-up → opportunity, referral or interview through additive migrations only:

- **Later, additive:** a `networking_events` table (name, date, location, notes); nullable `networking_event_id` on interactions and recruiting\_actions; `event` added to Contact.source and Opportunity.source CHECK lists; a `REFERRAL_SUBMITTED` application event type.
- **Already in place:** interactions are channel-agnostic (`in_person` exists); ContactCompany captures where someone works; ContactOpportunity has `referrer`; follow-ups are RecruitingActions linked to a contact.
- **Phase 1 obligation:** keep enums as text with CHECK constraints (extendable by migration), keep all cross-links nullable, and never assume an interaction came from email.

## 5. State machines

State is a projection of events. Each aggregate stores a materialized current state for fast reads, but the stage is recomputed from its event stream whenever an event is added or voided, so history and state cannot disagree.

### 5.1 Application

```mermaid
stateDiagram-v2
  [*] --> Applied: Apply action or confirmed ReviewItem
  state Active {
    Applied --> Assessment
    Assessment --> Interviewing
    Interviewing --> Offer
  }
  Active --> Rejected: terminal event
  Active --> Withdrawn
  Active --> Accepted
  Active --> Declined
  Active --> NoResponse
  Rejected --> Active: reopened by user correction
```

Active stages may move in any direction because companies differ (an assessment after a first interview is common). The stage is the stage of the latest non-voided stage-bearing event by `occurred_at`; a terminal event freezes it until a later `APPLICATION_REOPENED`.

| Event type | Stage effect | Typical source |
| --- | --- | --- |
| APPLICATION\_SUBMITTED | Applied | User Apply; confirmed Gmail acknowledgement |
| APPLICATION\_ACKNOWLEDGED | None | Gmail |
| ASSESSMENT\_RECEIVED / ASSESSMENT\_COMPLETED | Assessment | Gmail or user |
| INTERVIEW\_REQUESTED / INTERVIEW\_SCHEDULED / INTERVIEW\_COMPLETED | Interviewing | Gmail or user |
| OFFER\_RECEIVED | Offer | Gmail or user |
| REJECTED | Rejected (terminal) | Gmail or user |
| WITHDRAWN | Withdrawn (terminal) | User only |
| OFFER\_ACCEPTED / OFFER\_DECLINED | Accepted / Declined (terminal) | User only |
| MARKED\_NO\_RESPONSE | No response (terminal) | User only; the system may suggest it, never apply it |
| CONNECTION\_REQUEST\_SENT, CONNECTION\_ACCEPTED, OUTREACH\_SENT, FOLLOWUP\_SENT, RECRUITER\_CONTACTED, CONTACT\_REPLIED, NOTE\_ADDED | None | User or Gmail; reference an Interaction when one exists |
| APPLICATION\_REOPENED | Recomputes from events after it | User only |
| EVENT\_VOIDED | Removes the voided event from the projection | User only |

### 5.2 Opportunity

| From | To | Trigger | Notes |
| --- | --- | --- | --- |
| (none) | New | JD ingested | Extraction status and Evaluations are attributes, not states |
| New | Saved | User Save | Records OPPORTUNITY\_DECIDED with reason |
| New, Saved | Skipped | User Skip | Reason optional but prompted |
| Skipped | Saved | User reconsiders | History keeps both decisions |
| New, Saved, Skipped, Closed | Applied | User Apply, or a confirmed ReviewItem (e.g. a Gmail acknowledgement for an opportunity the user had skipped or closed) | Creates the Application in the same transaction |
| New, Saved, Skipped | Closed | User marks the posting closed | Future source adapters may propose this through Review |
| Applied | (stays Applied) | n/a | Further progress lives on the Application |

### 5.3 RecruitingAction

| From | To | Trigger |
| --- | --- | --- |
| (none) | Open | User creates; system creates from a confirmed event (assessment received creates "complete assessment" with the deadline; interview scheduled creates "attend interview" at the scheduled time); user accepts an outreach recommendation (creates `outreach`) |
| Open | Open (draft updated) | Outreach draft generated or edited; not a state change, recorded in `draft_updated_at` and `llm_runs` |
| Open | Snoozed | User snoozes until a time |
| Snoozed | Open | Snooze time passes (scheduler) |
| Open, Snoozed | Done | User completes. For `outreach`, completing requires the user to confirm it was sent, which records an outbound Interaction and `OUTREACH_SENT` |
| Open, Snoozed | Dismissed | User dismisses |
| Open, Snoozed | Superseded | System, when the reason disappears (a confirmed contact reply supersedes a pending follow-up; a rescheduled interview supersedes the old one). Internal-only and reversible |

### 5.4 ReviewItem

`pending` → `confirmed` (Confirm, or Edit + Confirm: the edited payload is re-validated, then the proposed command runs inside one transaction) | `rejected` (Reject / Ignore, with an optional reason such as "not recruiting"; feeds precision metrics) | `expired` (the target changed so the proposal no longer applies). A confirmed item's effects are undone with `EVENT_VOIDED` or the owning aggregate's correction command, never by deleting rows.

### 5.4a Skill and claim confirmation *(new)*

| Aggregate | From | To | Trigger | Event |
| --- | --- | --- | --- | --- |
| Skill | (none) | Proposed | Extraction or chat proposal | SKILL\_PROPOSED |
| Skill | (none) | Confirmed | User adds manually | SKILL\_ADDED |
| Skill | Proposed | Confirmed / Rejected | User decision in Review or Skills UI | SKILL\_CONFIRMED / SKILL\_REJECTED |
| Skill | Confirmed | Merged | User merges into another skill; claim links move; merged row redirects | SKILL\_MERGED |
| Skill | Proposed, Confirmed | gap marker on / off | User only; refused while confirmed academic, project or professional evidence exists | SKILL\_GAP\_MARKED / SKILL\_GAP\_CLEARED |
| Claim | Proposed | Confirmed / Rejected | User decision | CLAIM\_CONFIRMED / CLAIM\_REJECTED |
| Claim | Proposed, Confirmed | Same status, content edited | User edits statement, dates or organization | CLAIM\_EDITED |
| Claim | Proposed, Confirmed | Same status, class or engagement type changed | User only, with an explicit confirmation step; the model can propose but never apply | EVIDENCE\_CLASS\_CHANGED (old and new class and engagement type in payload) |

Skill confirmation means the user accepts the skill entry as theirs; it says nothing about strength, which comes only from linked Claims. Any Claim or Skill change bumps the affected skills' `updated_at`, which is how Evaluations become stale (6.2c).

A confirmed `skill_evidence` review item runs one transaction: create or reuse the Skill, create a confirmed Claim with the class and engagement type the user confirmed, attach an EvidenceSource of type `user_assertion` holding the user's own words and message ID, link them with ClaimSkill, and write the events above.

### 5.5 Rules shared by all machines

- Transitions are functions `(current_state, command) → events | error` in pure Python, unit-tested exhaustively.
- Every state-changing command takes an `expected_state_version` to prevent lost updates from two tabs or a racing job.
- Invalid transitions return a typed error; they never silently no-op.

## 6. Context and memory design

Memory in Career OS is the combination of persisted state, a deterministic context builder, and bounded model calls. The model receives a typed context package of a few thousand tokens assembled by SQL for one scope and one intent, never the user's history.

### 6.1 Principles

- **Exact questions get exact answers.** "How many times have I applied to Company X?" is a SQL count rendered by code. No model call.
- **Recipes, not free-form retrieval.** Each (scope, intent) pair has a context recipe: a list of typed context providers, each with a row limit and a token budget.
- **Aggregate before you include.** History enters as counts, dates and the few most recent items, not as raw rows.
- **Everything included is recorded.** Each model call persists a context manifest: the IDs and versions of every record it saw.
- **Output is checked against the manifest.** Citations to records outside the manifest, or uses that exceed an evidence class, fail validation.

### 6.2 Worked example: "Should I apply to this Amazon role?"

The user is in opportunity chat. The header shows the active opportunity (company, title, team, job ID), so the scope is `opportunity` and `opportunity_id` is known from the conversation row, not guessed from text.

1. **Scope and ownership check.** Load the conversation; verify the Opportunity belongs to the session user. No match means a 404, not a model call.
2. **Intent resolution.** A small fixed intent set per scope (`apply_decision`, `explain_missing_requirement`, `skill_clarification`, `company_history`, `general_question`). Suggested prompts map directly; free text is mapped by a fast-model classifier whose only output is one enum value. When the conversation has open clarification questions, the classifier also checks whether the message answers one.
3. **Evaluation lookup (rev 3).** Load the latest Evaluation and compute staleness (6.2c) in SQL. Chat never starts an evaluation run by itself: if none exists or it is stale, the answer says so and shows an **Evaluate** or **Re-evaluate** control. Evaluation runs happen only on that explicit action or the same button on the opportunity page (INV-17).
4. **Deterministic retrieval** through the `apply_decision` recipe (table below). Qualification skill keys are first matched to the user's Skill Inventory by normalized key and aliases; evidence is then pulled through the matched Skills.
5. **Deterministic pre-checks:** structured work-authorization and location conflicts, cooldown rules the user wrote, duplicate application detection, and per-qualification evidence status (`met` candidates, `not_recorded`, user-marked `gap`). Hard conflicts are passed as facts.
6. **Model reasoning (evaluation run only),** reasoning tier: returns a validated Evaluation (components, qualification assessments, blockers, lane recommendation, recommendation, open questions). Required qualifications with status `not_recorded` must appear as open questions, never as gaps. In chat, the streamed answer is grounded in the latest Evaluation plus the retrieved context.
7. **Post-validation.** Every cited Claim and Skill must be in the manifest; a `learning` claim cannot back a rating described as experience; `internship` and `unspecified` professional claims cannot satisfy years-of-experience requirements and are never described as full-time (INV-16); a `not_recorded` qualification cannot be labeled a gap. One repair retry, then a typed error.
8. **Persist** the Evaluation with its basis arrays (skill\_ids, unmatched\_skill\_keys, lane\_ids, resume\_ids) and the LLM run with its manifest.
9. **Deterministic action.** The answer ends with Apply / Save / Skip controls and any clarification cards. The model never creates the Application or changes evidence.

| Context section | Retrieval type | Query | Bound |
| --- | --- | --- | --- |
| Opportunity + qualifications | SQL | By opportunity\_id | All qualification lines (typically 5 to 30) |
| Profile constraints | SQL | Profile row: location, remote, work authorization, target roles | 1 row |
| Resume lanes | SQL | Active lanes with descriptions and default resume outline summaries | All active lanes; outline summary per lane, not the resume text |
| Skill Inventory matches *(new)* | SQL | Skills whose normalized key or aliases match any qualification skill key, with derived badges, gap markers and resume exposure | One row per matched skill, top 30 |
| Relevant evidence *(modified)* | SQL join | Claims linked to matched skills through claim\_skills, plus top claims per class by recency | Top 25 claims; class, engagement type and confirmation status always shown |
| Evidence fallback | Postgres full-text | Qualification text against claim statements and skill names when matching returns fewer than 5 | Top 10 |
| Company history summary | SQL aggregate | Counts of opportunities and applications at this company by stage; last outcome; last activity date; strategic priority | 1 row of aggregates |
| Prior applications at company | SQL | Most recent applications: title, team, applied\_at, stage, terminal reason | Last 5 |
| Recent company events | SQL | DomainEvents for this company's aggregates in the last 180 days | Last 10, types and dates only |
| Similar past opportunities | SQL | Same company, title token overlap or same team | Last 3, title and decision only |
| Contacts at company | SQL aggregate | Contacts via ContactCompany or ContactOpportunity with interaction count and last interaction date | Top 5 by recency of interaction |
| Strategy rules | SQL | Active rules scoped global, to this company, or to candidate lanes | All matching; usually under 10 |
| Open actions | SQL | Open RecruitingActions for this company | Up to 5 |
| Artifact text | Object storage | Only on explicit request | One document, truncated |

The eighth application to a company therefore reaches the model as one aggregate row, five short application lines and ten dated events. Old JDs never enter the prompt.

### 6.2a Skill feedback loop *(new)*

A clarification answered in one opportunity becomes durable knowledge only after the user confirms a structured proposal.

1. The evaluation marks a required qualification (say, Excel) as `not_recorded` and emits an open question.
2. The chat asks: Excel is required, but there is no confirmed evidence for it. Is this a real gap, or experience that is not recorded yet?
3. The user replies, e.g. "I used Excel professionally."
4. The model (fast tier, `propose_skill_evidence`) returns a `SkillEvidenceProposal`: skill (existing ID or new name), proposed evidence class, proposed engagement type, organization if stated, `assertion_text` (the user's words), rationale, and ambiguity flags.
5. Deterministic rules on the proposal: `assertion_text` must be a verbatim span of the user's message; engagement type is `unspecified` unless the words state it; a vague statement ("I know Excel") yields class `unspecified`, which the user must choose; the model can never propose `professional` unless the words say work, job or employer.
6. A ReviewItem (source `chat`) appears as an inline card in the chat and in the Review inbox: **Confirm**, **Edit + Confirm** (choose class and engagement type, add organization or dates), **It's a real gap** (marks the skill gap), **Ignore**.
7. Confirming runs the transaction in 5.4a and increments the Skill Inventory version. Evaluations that used that skill, or had an unmatched JD skill key that now matches it, become stale (6.2c). They are flagged on the opportunity and on Home and are never re-run automatically.
8. Future evaluations for any opportunity see Excel through the inventory, with the user's words as provenance.

### 6.2c Stale evaluations *(rev 3, O-12 locked)*

An Evaluation is stale when an input it relied on changed after it was created. Staleness is a SQL comparison computed on read; it never starts model work.

Stale if any of these is later than the Evaluation's `created_at`:

- `updated_at` of any Skill in its `skill_ids` (skill edits, merges, gap markers, and changes to linked Claims or EvidenceSources all bump it);
- creation or alias change of a non-merged Skill matching any key in `unmatched_skill_keys`;
- `updated_at` of any lane in `lane_ids`, or the creation, archiving or lane reassignment of a resume in those lanes (covers "selected resume changed");
- the Opportunity's `content_updated_at` (JD fields or qualifications edited);
- the Profile's `constraints_updated_at` (location, remote, work authorization).

Not triggers: company history, contacts, interactions, strategy rules, communication preferences. Those are read live when chat answers, and the Evaluation shows its date.

A stale Evaluation stays visible with a stale badge and a Re-evaluate control. Home shows an `evaluation_stale` item only for Opportunities in New or Saved, so old decisions do not create noise.

### 6.2b Outreach recipe *(new, Phase 1B)*

Outreach reasoning separates deterministic signals from model judgment and never produces a numeric score.

| Signal | Source | Deterministic override |
| --- | --- | --- |
| Opportunity importance | Opportunity.priority, latest evaluation recommendation, stage | Terminal application → not now (user may override) |
| Strategic company importance | Company.strategic\_priority | None |
| Relationship strength | Interaction count, last interaction date, any inbound reply, ContactCompany relation | None |
| Role and team relevance | ContactOpportunity role, contact title and relation, team match | None |
| Existing routing | Referrer or recruiter already linked to this opportunity; recruiter already engaged on the application | Flags possible duplication |
| Previous outreach | Outbound interactions to this contact and open outreach actions | Unanswered outreach inside the cooldown → not now |
| Cooldown and follow-up rules | StrategyRules with conditions | Violated rule → not now |
| Duplicate-contact risk | Recent or open outreach to other contacts at the same company or opportunity | Flagged in reasons |
| Reachability | Contact has an email or LinkedIn URL recorded | Missing both → draft only, flagged |

The model returns `worthwhile`, `optional` or `not_now`, a list of reasons each tied to a signal, and a suggested channel. If the user proceeds, an `outreach` RecruitingAction is created and a draft is requested.

Draft context: opportunity summary and top qualifications, the contact (name, title, relation), up to 8 relevant confirmed claims with class labels, the company history summary, prior interactions with this contact, communication preferences and rules. Draft output is structured: subject, body, `cited_claim_ids`, `referenced_interaction_ids`, `relationship_basis` (`none` or `prior_interaction`). Validation: cited IDs must be in the manifest; class-use checks apply; `relationship_basis = none` requires no referenced interactions; a fast-model checker highlights any sentence asserting experience or a relationship not backed by cited items. Highlighted sentences are shown to the user, not silently rewritten. The user edits, copies and sends; the system never sends.

### 6.3 Where each mechanism is used

| Mechanism | Use it for | Do not use it for |
| --- | --- | --- |
| SQL / structured | Counts, histories, states, due dates, ownership, rules with conditions, contacts at a company | Anything requiring interpretation of prose |
| Artifact retrieval | Showing the user's original files; rare verbatim comparison | Routine context (use parsed outlines and claims) |
| Full-text search (Phase 1) | Matching qualification wording to claim wording when tags miss | Ranking by meaning across paraphrases |
| Semantic retrieval (later, pgvector) | Paraphrase-heavy matching, "similar roles I evaluated before", chat over long interaction notes | Replacing exact queries |
| LLM reasoning | Extraction, classification, fit judgment, explanations, drafts | Counting, filtering, sorting, access control |

### 6.4 Home scope

Home chat uses the same builder with a `home` recipe whose main input is the Home attention feed (section 7A): the same ranked items the page shows, as counts plus the top few items per group. If a Home question names a company, the builder adds that company's history summary; if it names a skill, the builder adds that skill's assessment; if it clearly targets one opportunity, the UI offers to open opportunity chat rather than silently switching scope.

### 6.5 Chat tools (Phase 2 candidate)

Later, chat can call a small set of read-only, user-scoped query functions (`count_applications`, `list_contacts_at_company`) instead of relying only on recipes. Phase 1 keeps recipes because they are easier to test and to reason about.

## 7. Gmail architecture

Gmail is read-only, synced about every 12 hours plus on demand, filtered deterministically before any model call, and never allowed to change career state without a human confirmation in Phase 1. Its purpose is to replace manual labeling ("application sent", "rejection") with proposals the user confirms in a few clicks. Sign-in and Gmail access are separate grants, so Career OS works fully without Gmail.

### 7.1 OAuth and scopes

| Grant | Scopes | When requested |
| --- | --- | --- |
| Sign-in | `openid`, `email`, `profile` | Registration and login |
| Gmail connect | `https://www.googleapis.com/auth/gmail.readonly` | Only when the user clicks Connect Gmail (incremental authorization, `access_type=offline`, `prompt=consent` on first connect) |
| Not requested in Phase 1 | `gmail.send`, `gmail.compose`, `gmail.modify`, full `mail.google.com` | Drafting stays inside Career OS; the user copies text into their own mail client |

- `gmail.metadata` was considered and rejected: it exposes headers only and does not support search queries, while assessment links, interview times and rejection wording live in the body.
- OAuth uses Authorization Code with PKCE and a `state` parameter bound to the session; the redirect URI is an exact match.
- Granted scopes returned by Google are stored and checked; a user who unticks Gmail access ends in `needs_reauth` with a clear message.

### 7.2 Google verification and consent (future public product)

To verify before public launch; not verified against current Google documentation in this phase:

- `gmail.readonly` is, to current knowledge, a **restricted** scope. Public apps using restricted scopes need OAuth app verification and a recurring third-party security assessment, which carries cost and lead time.
- While the app stays in **Testing** status it is limited to a small allowlist of test users, and refresh tokens for external apps in Testing are understood to expire after about 7 days. Expect periodic reconnects during personal use; the `needs_reauth` state handles this gracefully.
- Requirements for public launch likely include a privacy policy, a homepage, a verified domain, a scope-justification video, and compliance with Google's Limited Use rules for user data (including restrictions on using Gmail data for model training and on human reading of mail).
- Recommendation: stay in Testing through Phase 1 and 2; revisit before any multi-user beta (open decision O-4).

### 7.3 Sync

1. **Initial backfill (bounded):** `messages.list` with a query limited to a recent window (default 90 days, user-configurable at connect) and a cap on message count. Store the mailbox `historyId` from `users.getProfile` as the cursor.
2. **Incremental (revised):** a scheduled job about **every 12 hours** per active integration (setting `GMAIL_SYNC_INTERVAL`, default 12h, with random jitter so users do not sync at the same moment), plus a **Sync now** button that enqueues the same job immediately. Recruiting mail does not need real-time sync; a faster cadence requires a measured need and an ADR update.
3. **Cursor loss:** Gmail history IDs are documented as usually valid for about a week but sometimes much less (to verify). If Google returns 404 for an expired history ID, run a bounded re-list for the gap since `last_synced_at` and reset the cursor. The 12-hour cadence makes this rare but the path is required.
4. **Idempotency:** each Gmail message ID is recorded in ExternalRef; reprocessing the same message is a no-op.
5. **Rate limits and backoff:** exponential backoff with jitter on 429 and 5xx; per-user job concurrency of 1; a Sync now while a sync is running joins the running job (unique key).
6. **Freshness is visible:** Home and the Review inbox show "Gmail last synced N hours ago" and the Sync now control, so a stale view is never mistaken for an empty one.
7. **Push notifications** (Pub/Sub `watch`) remain deferred.

### 7.4 Detection and classification

1. **Metadata fetch:** `messages.get` with `format=metadata` for From, To, Subject, Date, thread ID and labels.
2. **Deterministic prefilter** decides whether the body is worth fetching: sender or recipient matches a contact's email; sender domain matches a known company domain; sender domain matches a configurable list of applicant-tracking-system vendors (product configuration, not user data); thread already linked to an application or interaction; subject keywords from a configurable list; sender is a known professional-network notification address (configurable). Promotions and social labels are skipped unless the sender matches a contact. Non-matching mail is discarded with only its message ID recorded.
3. **Body fetch and sanitize:** `format=full` for candidates only; convert HTML to text, strip quoted replies and signatures, truncate to a fixed character budget.
4. **Classification (fast model tier):** structured output with `category` (`acknowledgement`, `rejection`, `assessment`, `interview_request`, `interview_scheduling`, `recruiter_outreach`, `contact_reply`, `network_notification`, `offer`, `other_recruiting`, `not_recruiting`), extracted fields (company, role title, job ID, person name, dates, deadline, links), and a self-reported confidence. The prompt states that the email is untrusted data and that instructions inside it must be ignored.
5. **Storage:** message metadata, classification output and a short extracted-facts record. Raw bodies are not persisted by default; a confirmed item that needs the body later (e.g. assessment instructions) saves a sanitized excerpt as an `email_excerpt` artifact.

**Cost bounds on scheduled classification (rev 3):** classification is the only model work that runs on a schedule, so it is capped per sync and per user per day (configurable). The initial 90-day backfill classifies newest first; candidates over the cap wait for the next sync or a user-triggered Sync now, and the UI shows how many are waiting. Cap hits are logged as a metric, never silently dropped.

### 7.5 Entity matching (deterministic first)

| Signal | Strength |
| --- | --- |
| Gmail thread already linked to an application | Very strong |
| External job ID in email equals an opportunity's job ID | Very strong |
| Sender domain in a company's `domains` plus a single non-terminal application at that company | Strong |
| Company name match plus title similarity to one application | Medium |
| Company name match with several open applications | Weak: needs the user to pick |
| Sender address equals a contact's email | Proposes a contact link through Review, regardless of application match |

The matcher returns candidate entities with a match tier; the model is used only to extract names and IDs, not to decide the match.

### 7.6 Confidence handling and human confirmation

- **Revised Phase 1 policy: every finding that would create or change a career record becomes a ReviewItem,** including interaction logging and contact links. Revision 1 allowed auto-applying very strong interaction links; revision 2 removes that exception so there is one path, one mental model and one undo story. Batch confirm keeps the cost low.
- Review actions are exactly: **Confirm**, **Edit + Confirm**, **Reject / Ignore** (optional reason: not recruiting, wrong match, duplicate).
- Each item shows sender, subject, date, extracted facts, the proposed change in plain words, and the match reason.
- Confirmation and rejection rates per category are recorded. A later ADR may allow auto-apply for specific low-risk categories once measured precision justifies it; that would be a user-visible setting, off by default.

| Proposal shown to the user | Proposal type | Created when the email supports it | Effect on confirm |
| --- | --- | --- | --- |
| "Application acknowledgement for Company X / Role Y" | `create_application` or `application_event` | Acknowledgement matched to an opportunity or application, or enough facts to create one | Creates the Application (and minimal Opportunity if needed) or adds APPLICATION\_ACKNOWLEDGED |
| "Rejection for Application Z" | `application_event` | Rejection matched to an application | REJECTED event; stage recomputed; open follow-ups superseded |
| "Interview scheduling email" | `application_event` | Interview request or a stated date and time | INTERVIEW\_REQUESTED or INTERVIEW\_SCHEDULED; an `attend_interview` action at the stated time |
| "Assessment received" | `application_event` | Assessment invitation | ASSESSMENT\_RECEIVED; `complete_assessment` action with the deadline if stated |
| "Contact X responded" | `interaction` | Inbound mail from an address on a contact, in a thread with an earlier outbound message or outreach | Inbound Interaction; CONTACT\_REPLIED on a linked application; pending follow-up superseded |
| "This email may belong to Contact X" | `contact_link` | Name or address similarity without an exact address match | Links the Interaction to the contact |
| "New email address for Contact X" | `contact_email` | Exact name and company match with a new address | Adds the address with source `gmail` |
| "Connection accepted by X" | `interaction` | Only if a notification email exists and names the person; notifications may be disabled, so absence proves nothing | CONNECTION\_ACCEPTED interaction |

Gmail never infers relationship events it cannot see in an email. Connection acceptance, profile views and messages sent inside other platforms are only known if a notification email carries them.

### 7.7 Event creation

A confirmed review item runs the same domain command a manual action would, in one transaction: write DomainEvent(s) with `actor = gmail` and `source_ref_id` pointing at the ExternalRef, recompute the stage, create the Interaction, create or supersede RecruitingActions, mark the review item confirmed.

### 7.8 Token storage

- Refresh token encrypted with a per-record data key (AES-256-GCM); the data key wrapped by a key-encryption key held outside the database (environment secret in Phase 1, cloud KMS later). `key_version` supports rotation.
- Access tokens are held in memory for the duration of one job and never persisted.
- Only the Gmail adapter can call the credential vault. The vault's return type has a redacted `__repr__`; logging filters reject token-shaped strings as a second line of defense.

### 7.9 Disconnect, revocation, deletion

| Action | Effect |
| --- | --- |
| User disconnects | Call Google's token revocation endpoint; delete IntegrationCredential; set Integration `disconnected`; cancel queued Gmail jobs; keep confirmed events and interactions (they are the user's career history, now marked "source disconnected") |
| User disconnects and chooses "delete Gmail-derived data" | Also delete ExternalRefs, pending review items, classification records and email excerpts; confirmed events remain unless the user deletes them individually |
| Google reports revoked or invalid grant | Integration `needs_reauth`; sync stops; Home shows a reconnect prompt |
| Account deletion | All of the above plus every user-owned row and artifact |

## 7A. Home and UI principles *(new)*

Home answers one question, "what deserves my attention now?", from deterministic data, and exists from Task 10 onward (before any Gmail work). Gmail, evaluations and future modules make the same Home richer by adding attention providers; there is no temporary Home.

### 7A.1 Attention item contract

Every module that wants space on Home publishes typed attention items through a provider interface:

| Field | Meaning |
| --- | --- |
| kind | e.g. `action_due`, `interview_upcoming`, `review_pending`, `stage_changed`, `decision_needed`, `evaluation_stale`, `reply_received`, `integration_health` |
| urgency | `now` (today or overdue), `soon` (next 7 days), `later` |
| title, subtitle | One line each, written for scanning |
| entity\_ref | The opportunity, application, contact, skill or review item it concerns |
| primary\_action | The one thing to do (Open, Confirm, Complete, Decide, Re-evaluate, Reconnect) |
| at | Due time or occurrence time, used for ordering |

Ranking is deterministic: urgency tier, then time, then user-set priority (opportunity priority, company strategic priority). No model call is needed to render Home.

### 7A.2 Groups (product intent, not a fixed layout)

| Group | Shows | Available from |
| --- | --- | --- |
| Now | Overdue and today's actions, interviews and assessment deadlines today, recruiter replies needing action | T10; replies from T13 |
| Pipeline | Active applications counted by stage; stage changes in the last 7 days | T10 |
| Decide | High-priority or strategically important opportunities awaiting Apply / Save / Skip; stale evaluations | T10; evaluation signals from T11 |
| Review | Pending proposals grouped by source (resume extraction, chat, Gmail) with batch confirm | T10 (extraction); chat from T11; Gmail from T13 |
| Relationships | Follow-ups due, recent inbound interactions, outreach worth doing | T10 (manual); Gmail and outreach from T13 and T14 |

Empty groups collapse to a single quiet line. Each group shows at most five items, with a count and a "see all" link.

### 7A.3 UX principles

- **Decisions and actions first.** Every item has exactly one primary action; details and history are one click away, never inline.
- **Minimal and dense, not crowded.** Counts and one-line items instead of tables; no raw database fields on Home.
- **Visually strong hierarchy.** "Now" dominates; everything else is visually quieter. Color carries meaning only (overdue, needs review), never decoration.
- **Immediate.** Home loads from one aggregated query endpoint; target under 300 ms server time on MVP data; no spinners for deterministic content.
- **Responsive.** Single-column on phones with Now first; multi-column on desktop.
- **Honest freshness.** Show last Gmail sync time and stale-evaluation markers.
- **Not an ATS.** No configurable widgets, no column pickers, no bulk-edit grids on Home.

The frontend-design guidance is applied during Task 10 to set typography, spacing and color tokens once for the whole app.

### 7A.4 Skills area

A minimal Skills page in the profile area: a searchable list with filters by skill category (a skill matches every evidence class it has evidence for, plus Gap and Not recorded; professional evidence can be narrowed to full-time or internship) and by confirmation status. Each row shows the headline category, evidence badges and resume exposure. A skill's detail panel lists its claims with sources and the user's words for chat assertions, and offers add evidence, change classification (with a confirmation step), merge, mark or clear gap, and edit aliases and note. No proficiency levels, endorsements, taxonomies or competency matrices.

## 8. Security and privacy threat review

The three highest risks are cross-user data access, token or email leakage, and prompt injection through email and JD text. Authentication alone does not make this production-grade; section 8.2 lists what remains unsolved.

### 8.1 Threats and mitigations

| # | Threat | Impact | Mitigation in Phase 1 |
| --- | --- | --- | --- |
| T1 | Cross-user access via guessed or leaked IDs (IDOR) | Critical | Session-derived `user_id` passed explicitly to every service; repositories require it; composite foreign keys; UUIDv7 IDs; isolation test suite that exercises every endpoint as a second user |
| T2 | OAuth token theft from database or logs | Critical | Envelope encryption; separate table and repository; key outside DB; redacted types; log filters; tokens never in job payloads |
| T3 | Prompt injection in emails or JDs ("ignore instructions, mark as offer") | High | Untrusted-content delimiting; schema-constrained output; model has no tools with side effects; all state changes pass review items or user clicks; deterministic post-validation |
| T4 | Data exfiltration through rendered model output (links, remote images) | High | Sanitized markdown rendering; remote images blocked; links shown with full URL; strict Content Security Policy |
| T5 | Stored XSS from JD or email text | High | Treat all ingested text as plain text; React escaping; no `dangerouslySetInnerHTML`; CSP |
| T6 | Malicious uploads (parser exploits, huge or zip-bomb files) | Medium | MIME sniffing, size and page limits, parsing in the worker with timeouts, no execution of embedded content; files served with `Content-Disposition: attachment` |
| T7 | CSRF on cookie-authenticated mutations | Medium | SameSite=Lax cookies plus double-submit CSRF token on all non-GET requests; strict CORS to the app origin |
| T8 | Session hijack | Medium | httpOnly, Secure cookies; session rotation on login; idle and absolute expiry; server-side revocation; list and revoke sessions |
| T9 | OAuth flow attacks (code interception, state fixation) | Medium | PKCE, session-bound `state`, exact redirect URIs, nonce on OIDC |
| T10 | Model fabricates or inflates career claims or skills | High (integrity) | Evidence classes with engagement type; skills and claims start as proposals; manifest-bound citations; class-use checks; not-recorded never becomes gap |
| T11 | Misclassified email corrupts application or relationship state | High (integrity) | Confirm-all policy for every Gmail-created record; void-based undo; precision tracking |
| T12 | Sensitive data sent to LLM provider | Medium | Minimal context by recipe; no tokens or secrets by construction; choose a provider plan whose terms exclude training on API data (to verify); document in privacy notice |
| T13 | Secrets committed to the repository | High | gitleaks pre-commit and CI; `.env` ignored; secrets only from environment or secret manager |
| T14 | Cost abuse (runaway LLM calls, loops) | Medium | Per-user daily call and token caps; job attempt limits; prefilter before model calls; stale evaluations not auto-re-run |
| T15 | Dependency and supply-chain compromise | Medium | Lockfiles, Dependabot or Renovate, minimal dependency list, pinned container base image |
| T16 | Incomplete deletion (backups, object storage, logs) | Medium | Deletion job covers DB and bucket; logs hold no content; backup retention window documented |
| T17 | Future SSRF when JD URL fetching is added | Medium (deferred) | Not in Phase 1; when added: allowlisted schemes, private-IP blocking, size and time limits, run in worker |
| T18 *(new)* | Chat-driven evidence inflation (a casual remark becomes "professional experience") | High (integrity) | Structured proposal with verbatim assertion; class and engagement type unspecified unless stated; user confirms class explicitly; event logged |
| T19 *(new)* | Outreach drafts invent experience, shared history or a relationship | High (reputational) | Structured drafts with cited claims and interactions; `relationship_basis` validation; checker highlights unsupported sentences; user review; no sending |
| T20 *(new, future)* | Enrichment providers receive contact data and return unreliable addresses | Medium | No provider in Phase 1; when added: explicit per-lookup user action, results as review proposals with source `provider`, provider terms reviewed in an ADR |

### 8.2 Assumptions and unresolved security work

- No formal penetration test, security review or compliance program exists; Phase 1 is suitable for the owner and a few trusted test users only.
- Postgres Row-Level Security is not enabled in Phase 1 (open decision O-3); isolation depends on application code plus tests plus composite keys.
- Key management is an environment secret until a KMS is adopted; rotation is documented but not automated.
- No rate limiting beyond per-user LLM caps and platform defaults.
- The LLM provider's retention and training terms must be verified and recorded before real email content is sent.
- A privacy policy, data processing notes and Google Limited Use compliance are required before any public launch.

## 9. API and server boundaries

The API is organized as use cases grouped by module, split into commands (change state, emit events) and queries (read only). The exact endpoint list is produced per task in Phase 1, not here.

| Module | Commands | Queries |
| --- | --- | --- |
| Auth | Start sign-in, complete callback, sign out, revoke session, request account deletion | Current user, active sessions |
| Profile | Update profile, target roles, communication preferences | Get profile |
| Resumes and lanes | Upload resume, archive resume, create/update/archive lane, assign resume to lane | List resumes, lanes, parse status |
| Evidence | Confirm, edit, reject proposed claims; add claim manually; change evidence class or engagement type (user only, confirmed) | List claims by status, class or skill |
| Skills *(new)* | Add skill, edit name/aliases/note, confirm or reject proposed skill, merge skills, mark or clear gap, attach evidence | List and search with category and status filters; skill detail with evidence and resume exposure |
| Companies | Create, rename, add alias or domain, set strategic priority, merge | Company detail with history summary |
| Opportunities | Ingest JD, edit extracted fields and qualifications, set priority, request evaluation, Save, Skip, Apply, Close | List with filters, detail, latest evaluation, duplicates |
| Applications | Record event, void event, reopen, withdraw, mark no response | List by stage, detail, timeline |
| Actions | Create, complete, snooze, dismiss | Due and overdue, upcoming interviews and deadlines, by entity |
| Contacts | Create, edit (including manual email entry), merge, link to company or opportunity, log interaction | List, detail, contacts for company or opportunity |
| Outreach *(new, 1B)* | Request recommendation, accept recommendation (creates action), generate or regenerate draft, edit draft, mark sent | Recommendation with reasons, current draft with citations and highlights |
| Strategy | Create, edit, deactivate rules | List rules by scope |
| Integrations | Start Gmail connect, complete callback, sync now, disconnect (with or without derived-data deletion) | Integration status, last sync, errors |
| Review | Confirm, edit-and-confirm, reject/ignore, batch confirm | Pending review items by source |
| Home | None | Attention feed (one aggregated endpoint) |
| Chat | Create conversation (scope fixed), send message (SSE stream) | List conversations, messages |

Boundary rules:

- **Routers** handle HTTP, auth dependency, validation and error mapping only.
- **Services** hold business rules and call the state machines; each command is one transaction that writes state, events and jobs together.
- **Repositories** are the only place SQL lives; every method takes `user_id`.
- **Adapters** (Gmail, model gateway, object storage) sit behind interfaces with fakes for tests.
- **Errors** are typed (`NotFound`, `Conflict`, `InvalidTransition`, `NeedsReauth`) and mapped to HTTP codes; a resource owned by another user returns 404, never 403, to avoid confirming existence.
- **Long work** returns `202` with a job ID; the SPA polls job status or subscribes through the chat stream.
- **Versioning:** `/api/v1` prefix; breaking changes are rare because the only client ships from the same repository.

## 10. Repository structure

One monorepo with `backend/`, `frontend/`, `docs/` and `infra/`. The backend is a modular monolith: one package per domain module, each with the same five files, and dependency rules enforced by an import linter.

```
career-os/
  README.md
  docs/
    spec/            (this specification, split by section)
    adr/             (ADR-001 ... numbered, immutable once accepted)
    runbooks/        (key rotation, restore, deletion, Gmail reauth)
    threat-model.md
  backend/
    pyproject.toml
    alembic/versions/
    app/
      main.py        (API entry point)
      worker.py      (worker entry point)
      config.py
      core/          (db session, tenancy, ids, errors, logging, redaction, security)
      auth/
      profile/       (profile, target roles, communication preferences)
      artifacts/
      resumes/       (resumes, lanes)
      evidence/      (claims, sources)
      skills/        (inventory, merges, gap markers, assessment, resume exposure)
      companies/
      opportunities/ (opportunities, qualifications, evaluations)
      applications/
      actions/
      contacts/      (contacts, links, interactions)
      outreach/      (signals, recommendation, drafting, draft validation)
      strategy/
      events/        (domain_events, projections)
      review/
      attention/     (provider interface, ranking)
      context/       (context builder, recipes, providers)
      llm/           (gateway interface, adapters, prompts/, fake)
      integrations/
        gmail/       (oauth, sync, prefilter, classifier, matcher)
        enrichment/  (interface only, no provider)
        vault/       (credential encryption)
      jobs/          (queue, scheduler, handlers registry)
      home/
      chat/
    tests/
      unit/ integration/ isolation/ contract/ fixtures/personas/
  frontend/
    package.json
    src/
      app/ routes/ api/ (generated client)
      features/ home/ skills/ opportunities/ applications/ contacts/ outreach/ review/ chat/ settings/
      components/ lib/
    tests/e2e/
  infra/
    docker-compose.yml
    Dockerfile
  .github/workflows/
  .gitleaks.toml
```

Per-module layout: `models.py` (SQLAlchemy), `schemas.py` (Pydantic), `repository.py`, `service.py`, `api.py`, plus `machine.py` where a state machine exists.

Dependency rules:

- `core` depends on nothing in `app`.
- Modules call other modules only through `service.py`.
- Only `llm/adapters` imports a vendor SDK; only `integrations/vault` decrypts tokens; only `integrations/gmail` calls Google APIs.
- `context` may read through services but never imports `vault`.
- Future modules (`projects`, `dsa`, `system_design`, `speaking`, `behavioral`, `market`) are added as sibling packages that register Home attention providers and context providers.

## 11. Testing strategy

Tests run against a real PostgreSQL in Docker, a fake model gateway and a fake Gmail API; no test calls a real LLM or Google by default. Two synthetic personas with unrelated careers are the core fixtures, which makes the data-portability requirement a CI test rather than a promise.

| Layer | What it covers | How |
| --- | --- | --- |
| Unit | State machines (every transition and invalid transition), stage projection from events including out-of-order and voided events, evidence-class and engagement-type use checks (including internship and unspecified never counting as full-time), JSONB upcasters for every historical schema\_version, skill assessment derivation (multi-class, gap refusal, not-recorded), prefilter rules, matcher tiers, outreach overrides, context recipe budgeting | pytest, pure functions, table-driven cases |
| Integration | Services with real DB: commands write state + events + jobs atomically; review confirmation runs the same command as manual action; skill merge re-points claim links; company merge | pytest with a transaction-per-test Postgres |
| Migrations | Upgrade from empty, upgrade from previous release with data, downgrade where supported, schema drift check between models and migrations | Alembic in CI; autogenerate diff must be empty |
| Authorization and isolation | Every endpoint called by persona B against persona A's IDs returns 404; list endpoints never leak; jobs for A never read B's rows; composite FKs reject cross-user inserts; foreign IDs planted in review payloads, evaluation arrays and job payloads resolve as not found | Generated test matrix from the route table, so a new endpoint without an isolation test fails CI |
| Data portability (INV-01, INV-12) | Full flow (register, upload resume, confirm skills, ingest JD, evaluate, clarify a skill, apply, Gmail event, outreach draft) for persona A, delete A, repeat for persona B with a different career: same code, correct results | End-to-end test in CI, plus a CI-secret denylist of creator-specific terms scanned against the repo |
| Skill feedback loop *(new)* | A not-recorded requirement yields a question, never a gap; vague answers yield unspecified class; confirmed assertion appears in the next evaluation of a different opportunity; rejected proposal changes nothing; every 6.2c trigger marks the right Evaluations stale and non-triggers do not; no model call results from staleness | Integration test with fake gateway |
| Gmail parsing and classification | MIME decoding, HTML to text, quote stripping, prefilter decisions, 12-hour schedule and Sync now joining a running job, cursor recovery, idempotent re-sync, every proposal type | Recorded synthetic fixtures; fake Gmail server |
| LLM structured output | Schemas accept valid and reject invalid outputs; repair-retry path; manifest citation checks; injection fixtures produce no state change; draft validation rejects uncited relationships | Fake gateway returning canned outputs |
| LLM quality (offline) | Classifier precision and recall per category; JD extraction accuracy; evaluation citation validity; skill proposal class accuracy; draft unsupported-sentence rate | Labeled set kept outside the repo; run before prompt or model changes |
| Frontend | Active-opportunity header rules; Home groups and empty states; Skills filters | Vitest + Testing Library |
| End to end | Sign-in (test IdP stub), JD ingest to Apply, Home after manual workflow, skill clarification card, review confirm | Playwright against Docker Compose |
| Security checks | Secrets scan, dependency audit, CSP headers present, cookie flags | gitleaks, pip-audit, npm audit, header tests |

## 12. Observability

Logs, metrics and traces carry IDs, types, counts and timings only. Career content, email content, prompts, model outputs and tokens never leave the database through telemetry.

### 12.1 Logging

- Structured JSON logs via `structlog` with `request_id`, `job_id`, `user_id` (opaque UUID), module, event name, duration, outcome, error code.
- **Allowlist logging:** log calls accept only whitelisted field names; unknown fields are dropped. A redaction processor also masks email addresses and token-shaped strings as a second defense.
- Exceptions are logged with type and stack, not with local variables or request bodies.
- `request_id` propagates into jobs via `correlation_id`, so one user action can be followed across API and worker.

### 12.2 Metrics (minimal set)

| Area | Metric |
| --- | --- |
| API | Request count and p50/p95 latency by route and status |
| Jobs | Queue depth, oldest job age, failures and retries by kind |
| Gmail | Sync lag per integration, messages seen, prefilter pass rate, classifications by category, review confirm vs reject rate |
| LLM | Calls, input/output tokens, latency, validation failures and repairs by prompt ID and version; estimated cost per user per day |
| Integrity | Voided events per week (a proxy for bad automation or UX) |

### 12.3 Tracing and errors

- Phase 1: OpenTelemetry instrumentation for FastAPI and SQLAlchemy is optional; request and correlation IDs are required.
- An error tracker may be added with request-body capture disabled and PII scrubbing on; not required for Phase 1.
- `LlmRun` rows give per-call debuggability inside the user's own data boundary; an admin debugging a user's issue requires that user's explicit consent (policy to write before multi-user beta).

## 13. Cost model

For a single user the MVP can run near the free tiers of common hosting, Postgres and storage providers; LLM usage is the only cost that grows with activity. No prices below are verified; every figure is a formula or a labeled assumption to check at selection time.

| Cost | Type | Driver | Can start free? | Notes |
| --- | --- | --- | --- | --- |
| App hosting (API + worker) | Fixed monthly | Instance size, always-on worker | Possibly (assumption) | Worker must stay on for scheduled sync; free tiers that sleep are unsuitable for the worker |
| Managed PostgreSQL | Fixed monthly | Storage, compute, backups | Possibly (assumption) | Check backup retention and point-in-time restore on the chosen tier |
| Object storage | Usage | GB stored, requests, egress | Likely at MVP volume (assumption) | Resumes and JDs are small |
| Domain and TLS | Fixed yearly | Domain registration | TLS typically free | Needed for a stable OAuth redirect URI |
| LLM API | Usage | Calls x tokens x per-token price by tier | No | Main variable cost; controlled by prefilter, reusing evaluations until the user re-runs them, fast tier for extraction and classification |
| Gmail API | Usage quota | Requests | Free within quota (to verify) | Quota, not billing, is the practical limit; the 12-hour cadence keeps request volume low |
| Google OAuth verification and security assessment | One-off and recurring | Restricted scope for public use | Not needed while in Testing | Potentially significant; required only for a public product |
| Error tracking, monitoring | Fixed or usage | Events | Often free at small scale (assumption) | Optional in Phase 1 |

LLM cost estimate formula for planning:

```latex
\text{monthly LLM cost} = \sum_{k \in \{\text{extract},\,\text{classify},\,\text{evaluate},\,\text{chat},\,\text{skill},\,\text{outreach}\}} N_k \times (T^{in}_k \, p^{in}_{tier(k)} + T^{out}_k \, p^{out}_{tier(k)})
```

Where N is calls per month, T is average tokens per call, and p is the verified per-token price for the tier used. Phase 1 instruments every term so the estimate becomes a measurement within weeks. A per-user daily cap (open decision O-5) bounds the worst case.

### 13.1 Daily LLM cost cap (decided, O-5)

Each user may consume at most **$1.00 of model cost per UTC day** by default. The value is configuration (`LLM_DAILY_COST_CAP_USD`), not code, and will be revised from measured usage.

- **No silent overage:** before every call, the gateway reserves the worst-case cost (estimated input tokens plus `max_tokens` output, at configured per-model prices) against the remaining budget, and settles the actual cost from the provider's usage after the call. A call whose reservation does not fit is refused with a typed `llm_budget_exhausted` error; it is never sent.
- **When the cap is reached:** all model work for that user stops until the next UTC day: extraction, evaluation, chat replies, skill proposals, outreach and scheduled Gmail classification (candidates wait, visible as a count). Deterministic features (Home, pipeline, manual edits, Review of existing items) keep working.
- **Visible to the user:** a budget indicator (spent / cap, resets at 00:00 UTC) in settings and next to any AI action; a clear message naming the cap when an action is refused.
- **Where it is enforced:** only in the model gateway, from `llm_runs` totals, so no path can bypass it. Per-model prices are configuration, labeled as assumptions until verified.
- **Delivered by:** configuration key in Task 1; enforcement, reservation and settlement in Task 5; UI indicator in Task 5 (settings) and Task 10 (app shell).

## 14. Phase 1 plan

Phase 1 is 14 tasks in two parts, ordered by the locked priority list. **Phase 1A (Tasks 1 to 11)** delivers the manual opportunity and application workflow first, then evidence and the Skill Inventory, then Home, then evaluation with the skill feedback loop. **Phase 1B (Tasks 12 to 14)** adds Gmail and then targeted outreach; outreach is a committed, high-priority 1B capability, not optional polish. Each task ships backend, migrations, minimal UI and tests together and ends with a short review note. A checkpoint separates 1A and 1B.

| # | Task | Part | Depends on | Size |
| --- | --- | --- | --- | --- |
| 1 | Repository scaffold, tooling, CI, Docker Compose, config and logging baseline | 1A | None | M |
| 2 | Database foundation, tenancy pattern, events table, job queue | 1A | 1 | M |
| 3 | Authentication: Google sign-in, sessions, CSRF, account deletion | 1A | 2 | M |
| 4 | Profile, artifacts, resume upload and text parsing, resume lanes | 1A | 3 | M |
| 5 | Model gateway, prompt registry, LLM runs, review framework | 1A | 3 | M |
| 6 | Companies, JD ingestion and extraction, qualifications, duplicates, priorities | 1A | 5 | L |
| 7 | Opportunity and Application state machines, decisions, timeline, corrections | 1A | 6 | M |
| 8 | Contacts, interactions, recruiting actions (incl. interviews and deadlines), strategy rules | 1A | 7 | M |
| 9 | Evidence and Skill Inventory: claim and skill extraction, review UI, Skills UI | 1A | 4, 5 | L |
| 10 | Home v1 on attention providers, app shell, design tokens | 1A | 8, 9 | M |
| 11 | Context builder, Evaluation with staleness, opportunity and Home chat, skill feedback loop | 1A | 8, 9, 10 | L |
| 12 | Gmail connect, credential vault, 12-hour sync, Sync now, disconnect | 1B | 3; scheduled after the 1A checkpoint | L |
| 13 | Gmail classification, matching, review proposals, Home enrichment | 1B | 8, 10, 12 | L |
| 14 | Outreach recommendation and drafting | 1B | 8, 11; scheduled after 13 by priority | L |

Task 9 may run in parallel with Tasks 6 to 8 once Task 5 is done, but priority keeps the manual workflow first. Task 12 is technically unblocked after Task 3 but is scheduled after the 1A checkpoint. Task 14 does not depend on Gmail (sent outreach can be recorded manually) and follows Task 13 only by priority. M is one to two days of focused agent work plus review, L two to four days (rough, assumption).

### Acceptance criteria

1. **Task 1: Scaffold.** `docker compose up` starts Postgres, API, worker and frontend; `/healthz` returns OK; CI runs ruff, mypy, pytest, ESLint, tsc, Vitest and gitleaks on every push; settings load only from environment; structured logging with allowlist and redaction has tests; job-queue library choice recorded in an ADR; README explains how to run everything.
2. **Task 2: DB foundation.** Alembic configured; `users`, `domain_events`, `jobs` created; tenancy helper requires `user_id` in every repository method; composite-FK convention demonstrated with a failing cross-user insert test; ID re-resolution helper for non-FK references (INV-18); events table insert-only for the app role; `state_version` convention; worker claims jobs with `SKIP LOCKED`, retries with backoff, honors `unique_key`, and loads every entity through the job's `user_id`; migration drift check in CI.
3. **Task 3: Auth.** Google OIDC sign-in with PKCE, state and nonce; sessions stored hashed with idle and absolute expiry; CSRF on mutations; sign-out and revoke-session work; account deletion removes all user rows and objects; isolation test harness runs against every registered route; no Gmail scope at sign-in.
4. **Task 4: Profile and resumes.** Profile with constraints (and `constraints_updated_at`), target roles and communication preferences; resume upload with MIME, size and page limits; original stored immutably with SHA-256 dedup; worker extracts text and a parsed outline without any model call; lanes CRUD and resume-to-lane assignment; UI never offers to edit a resume file.
5. **Task 5: Model gateway and review framework.** `ModelGateway` with structured-output and streaming methods; one vendor adapter and a fake; model tiers by configuration; prompt registry with versions; every call writes an `LlmRun` with manifest; validation with one repair retry; per-user daily LLM cost cap with reservation, settlement, typed refusal and a budget indicator (13.1); `review_items` with the Confirm, Edit + Confirm, Reject / Ignore command framework that dispatches to domain commands (first producers arrive in Tasks 6 and 9).
6. **Task 6: JD ingestion.** Paste JD text with optional source URL; immutable JD artifact; extraction of company, title, team, job ID, location, workplace type and verbatim qualifications with categories and skill keys, applied as `extracted` origin; company resolution by normalized name, alias or domain; duplicate detection; opportunity priority and company strategic priority; every field user-editable and edits bump `content_updated_at`; no creator data in prompts (reviewed).
7. **Task 7: State machines.** Pure transition functions for Opportunity, Application and RecruitingAction with exhaustive tests; Save, Skip, Apply, Close; Apply creates the Application atomically; manual event recording; void and reopen; projection correct under out-of-order and voided events; optimistic concurrency; single ordered timeline.
8. **Task 8: Relationships, actions, rules.** Contacts CRUD and merge with manual email entry and per-address source; contact-company and contact-opportunity links; Interactions on any channel with application-linked events; RecruitingActions including `attend_interview` and `complete_assessment` with scheduled times; snooze, complete, dismiss; strategy rules with scope.
9. **Task 9: Evidence and Skill Inventory.** Resume extraction (explicit on upload) proposes Claims with class and engagement type (`unspecified` unless stated) and Skills, all as ReviewItems; review UI with batch confirm; Skills CRUD, aliases, merge with redirect, gap marking with refusal rule, class and engagement-type change with explicit confirmation and events; derived skill category and badges; resume exposure; Skills page with filters; model cannot set class or engagement type (test); INV-13 and INV-16 tests.
10. **Task 10: Home v1.** Attention provider interface; providers for actions due and overdue, interviews and deadlines, pipeline by stage, recent stage changes, high-priority opportunities awaiting a decision, pending ReviewItems, and follow-ups due; one aggregated Home endpoint under the latency target; app shell; design tokens set once; empty groups collapse; five-item cap; one primary action per item; Playwright covers Home after the manual workflow.
11. **Task 11: Context, Evaluation, chat, feedback loop.** Recipe registry with budgets; `apply_decision` recipe per section 6.2 with Skill Inventory matching; deterministic pre-checks; explicit Evaluate / Re-evaluate only; Evaluation with components, qualification assessments, open questions and basis arrays; staleness per 6.2c with no automatic re-run; citation, class, engagement-type and not-recorded validation; opportunity chat with fixed scope and visible header; Home chat with no active opportunity; skill clarification cards producing `skill_evidence` ReviewItems; a confirmed assertion appears in the next Evaluation of another opportunity (test); `evaluation_stale` attention provider.
12. **Task 12: Gmail connect and sync.** Incremental OAuth for `gmail.readonly` only; granted scopes verified; refresh token envelope-encrypted; bounded backfill; 12-hour scheduled incremental sync with jitter; Sync now joins a running sync; cursor recovery; idempotency via ExternalRef; `needs_reauth` handling; disconnect revokes and deletes credentials, optional derived-data deletion; last-sync time exposed; no token in logs, job payloads or model calls (tests).
13. **Task 13: Gmail intelligence.** Prefilter including contact addresses; sanitized body fetch for candidates only; classification with per-sync and per-day caps and a visible waiting count; deterministic matcher; every proposal type in section 7.6 created as a ReviewItem, none auto-applied; confirmation runs existing commands; relationship proposals only when the email supports them; precision metrics; injection fixtures cause no state change; Gmail attention providers plug into the existing Home.
14. **Task 14: Outreach.** Deterministic signals and overrides per 6.2b; recommendation only on explicit request, with reasons and no score; accepting creates an `outreach` RecruitingAction; structured draft with citations, `relationship_basis` validation and unsupported-sentence highlighting; engagement-type rules apply to drafts; edit, copy and mark-sent (records an outbound Interaction and OUTREACH\_SENT); no send capability exists; outreach attention items on Home.

Phase 1A exit gate: Tasks 1 to 11 accepted; isolation, portability and staleness tests green; threat mitigations T1 to T10 and T18 verified; a 1A checkpoint report. Phase 1B exit gate: Tasks 12 to 14 accepted; T11 and T19 verified; a Phase 1 checkpoint report before Phase 2.

## 15. ADR candidates

Twenty-one decisions deserve ADRs. Eight are accepted (five with the baseline approval, three locked in revision 3) and thirteen are Proposed, to be written as ADR files during Task 1. Each becomes `docs/adr/NNN-title.md` with Context, Decision, Alternatives, Consequences.

| ADR | Title | Status | Decision | Key consequence |
| --- | --- | --- | --- | --- |
| 001 | Modular monolith with API and worker processes | Proposed | One codebase, two entry points, module boundaries enforced by import rules | Simple deploy and debugging; splitting a service later needs module-level discipline now |
| 002 | PostgreSQL as the single system of record | Proposed | Postgres 16 for state, events, jobs, sessions, credentials and search | One backup story; pgvector available without a new service |
| 003 | Tenant isolation model | Accepted with baseline (O-3); RLS revisit before multi-user beta | Shared schema, `user_id` on every owned row, composite FKs, mandatory repository scoping, isolation test matrix; RLS deferred | Strong and testable; relies on code discipline until RLS |
| 004 | Authentication | Accepted with baseline (O-2) | Google OIDC sign-in, server-side sessions in Postgres, separate grant for Gmail | No auth vendor; Google-only login initially; we own session security |
| 005 | Event-logged state, not event sourcing | Proposed | Append-only `domain_events` written with materialized state; projections recomputable; corrections by voiding | Full history without rebuilding all state from events |
| 006 | Postgres-backed job queue | Proposed | Jobs table with `SKIP LOCKED`, unique keys, retries; worker-side scheduler | No Redis or broker; throughput ceiling far above MVP |
| 007 | Model gateway with single vendor adapter | Accepted with baseline (O-5); cost-cap value pending | Internal interface for structured output and streaming; model tiers by config; no LLM framework | Provider independence at low cost; vendor choice is a data-handling decision |
| 008 | Evidence classes with deterministic use checks | Proposed (revised) | Four claim classes plus engagement type on professional claims; gap is a skill marker; model cannot raise class; outputs validated against permissions | Prevents claim inflation; internship handled as an engagement type (O-10 accepted); checks always read class and engagement type together |
| 009 | Gmail: read-only scope, 12-hour polling, confirm-all | Accepted with baseline (O-4) | `gmail.readonly`; sync about every 12 hours plus Sync now; every Gmail-created or changed record goes through review, no exceptions in Phase 1 | Minimal API activity and one confirmation path; up to 12 hours of latency unless the user syncs |
| 010 | No semantic retrieval in Phase 1 | Proposed | Skill Inventory aliases + normalized keys + Postgres full-text; adopt pgvector on a measured recall gap | No embedding cost yet; some paraphrase misses |
| 011 | Envelope encryption for OAuth credentials | Proposed | AES-256-GCM per record, KEK outside DB, versioned for rotation | DB leak alone does not expose tokens |
| 012 | Company is a per-user entity | Proposed (O-7 confirms) | No shared global company table in Phase 1 | No cross-user leakage; duplicate canonicalization per user |
| 013 | Backend Python/FastAPI, frontend React/Vite SPA | Accepted with baseline (O-1) | As section 3 | Two languages; strong AI and parsing ecosystem |
| 014 | Email data minimization | Proposed | Store metadata, classification and extracted facts; no raw bodies unless user confirms an excerpt | Less sensitive data at rest |
| 015 *(new)* | First-class Skill Inventory with derived assessment | Proposed | Skills table linked to claims; assessment computed on read; not-recorded is never a gap; per-user vocabulary, no global taxonomy | Evaluations stop inventing gaps; users maintain their own aliases |
| 016 *(new)* | Internship as an engagement type | Accepted (O-10, rev 3) | `professional` + `engagement_type = internship`; permitted uses read the pair | One class for employment; checks must never read class alone |
| 017 *(new)* | Chat-to-evidence only through structured proposals | Proposed | Skill-evidence proposals with verbatim assertions, unspecified class unless stated, user-confirmed | Durable learning from chat without evidence inflation |
| 018 *(new)* | Home built on attention providers | Proposed | Modules publish typed attention items; deterministic ranking; one aggregated endpoint | Early Home is the final Home; Gmail and future modules plug in |
| 019 *(new)* | Outreach without new tables | Proposed | Recommendations are LlmRun outputs; drafts live on `outreach` RecruitingActions; sending is manual | No draft or recommendation tables; draft history via llm\_runs |
| 020 *(new)* | Phase 1 split into 1A and 1B | Accepted (O-11, rev 3) | Manual workflow, then skills, Home and evaluation; then Gmail, then outreach (committed, high priority); checkpoint between 1A and 1B | Useful product earlier; scope can be cut before the riskiest work |
| 021 (rev 3) | Staleness by basis comparison, explicit re-run | Accepted (O-12, rev 3) | Evaluations store a basis (skills, unmatched keys, lanes, resumes); staleness is a SQL comparison on read; evaluation runs only on explicit user action | No hidden model cost; users see stale badges and decide when to re-run |

ADR-005 draft, as an example of the format:

- **Context:** application history must be preserved; current stage must be fast to read; companies follow different processes; Gmail and users both add history and both can be wrong.
- **Decision:** every state change writes an immutable DomainEvent in the same transaction as the aggregate's materialized state. Stage is a pure projection of non-voided events. Mistakes are corrected with `EVENT_VOIDED` or `APPLICATION_REOPENED`, never by editing or deleting events.
- **Alternatives:** mutable status column with an audit table (history becomes secondary and drifts); full event sourcing (every read rebuilt from events, snapshots, upcasters: too much machinery for this domain and team).
- **Consequences:** history is authoritative; reads stay simple; projection logic must be pure and exhaustively tested; account deletion needs a privileged path to remove events.

## 16. Risk register

The biggest risks remain Phase 1 scope, Gmail review fatigue and Google's restricted-scope rules; revision 2 adds skill-inventory upkeep and outreach draft quality. Ranked by likelihood times impact.

| Rank | Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- | --- |
| 1 | Phase 1 is too large (14 tasks, six L) | High | High | 1A/1B split with a checkpoint; strict acceptance criteria; minimal UI per task; Task 14 is committed to 1B after Gmail, never dropped as polish |
| 2 | Gmail review fatigue now that every finding needs confirmation | High | Medium | Deterministic prefilter; batch confirm; one-click Ignore; measure precision before any auto-apply ADR |
| 3 | Restricted Gmail scope blocks a public multi-user launch | High | High (for product) | Stay in Testing for personal use; Gmail optional; decide on verification before beta; manual entry stays fully capable |
| 4 | Skill Inventory becomes a chore (too many proposed skills after resume upload) | Medium | Medium | Batch confirm by resume section; proposals only for skills with a supporting line; unconfirmed skills still usable as unverified (O-8) |
| 5 | Cross-user data leak through a missed scope | Low | Critical | Composite FKs, route-generated isolation tests, 404-not-403, consider RLS (O-3) |
| 6 | Evaluations sound confident but are wrong; user over-trusts them | Medium | High | Interpretable components with citations; not-recorded questions instead of false gaps; no single score |
| 7 | Outreach drafts misrepresent the user or a relationship | Medium | High (reputational) | Structured citations, relationship-basis validation, highlighted unsupported sentences, mandatory user review, no sending |
| 8 | Evidence inflation via extraction or chat | Medium | High | Evidence classes with engagement type, verbatim assertions, user-only class changes, event log |
| 9 | Generated-code sprawl reduces owner understanding | Medium | High | Small tasks, fixed module layout, ADRs, review notes per task |
| 10 | Time-sensitive email (same-day interview scheduling) waits up to 12 hours | Medium | Medium | Sync now on Home and Review; last-sync time visible; cadence configurable via ADR if measured need appears |
| 11 | JD and resume parsing fails on varied formats | Medium | Medium | Manual correction everywhere; paste-text fallback; OCR deferred |
| 12 | Company, contact and skill duplicates corrupt history | Medium | Medium | Aliases, domains, merges with events and redirects |
| 13 | LLM cost grows unnoticed | Low | Medium | Per-user caps, cost metric per prompt, explicit-only evaluation runs, no auto re-evaluation |
| 14 | Provider changes (model deprecation, API changes) | Medium | Low | Gateway interface, prompt versions, offline eval before switching |
| 15 | Home drifts toward a cluttered dashboard | Medium | Medium | Attention contract, five-item cap, one primary action per item, no widgets |
| 16 | Sparse LinkedIn data weakens relationship features | High | Low | Manual contacts first-class; Gmail contributes contacts and notifications when present; no scraping |
| 17 | Loss of data (no tested restore) | Low | High | Managed backups; restore runbook tested once before real data |

## 17. Open decisions requiring approval before Phase 1

All decisions are closed. O-1 to O-4 and O-7 to O-9 are accepted with the baseline approval and are not reopened unless implementation reveals a genuine contradiction. O-10 to O-12 were locked in revision 3. O-5: the daily LLM cost cap is $1.00 per user per day, configurable (section 13.1). O-6: hosting vendors and production budget are deferred; Phase 1 runs in local development and hosting never blocks a task.

| ID | Decision | Recommendation | Main alternative |
| --- | --- | --- | --- |
| O-1 | Stack: Python/FastAPI backend and React/Vite SPA | Approve | TypeScript full-stack (Next.js) for one language |
| O-2 | Authentication: self-implemented Google OIDC with DB sessions; Google-only login at first | Approve | Managed auth provider (adds a vendor, reduces owned security code) |
| O-3 | Isolation: app-level scoping + composite FKs + test matrix now; Postgres RLS later | Approve, revisit before multi-user beta | RLS from day one (stronger, harder to learn and debug) |
| O-4 | Gmail: `gmail.readonly`, 12-hour polling plus Sync now, all state changes via review with no auto-apply exceptions, no raw body storage, remain in Google Testing mode through Phase 1 | Approve | Push notifications, auto-apply for high-confidence events |
| O-5 | LLM provider for the first adapter, data-handling acceptance (resume, JD and email excerpts sent to that provider), and a per-user daily cost cap | Anthropic adapter first, cap to be set by owner | Another single vendor |
| O-6 | Hosting, managed Postgres and bucket vendors, and a monthly budget ceiling | Owner sets the ceiling; orchestrator proposes vendors within it in Task 1 | Self-managed VM |
| O-7 | Company is per-user (no shared company directory) | Approve | Global canonical companies with per-user overlays |
| O-8 | Resume-extracted claims and skills usable in evaluations before confirmation, marked unverified | Approve | Require confirmation before any use (safer, slower onboarding) |
| O-9 | Phase 1 JD ingestion is pasted text plus optional URL; no URL fetching | Approve | Fetch public job pages by URL (adds SSRF surface and brittleness) |
| O-10 | Internship model: professional evidence with engagement\_type = internship (not a sixth evidence class) (locked) | Approve (option B) | Sixth class "internship" (option A) |
| O-11 | Split Phase 1 into 1A (Tasks 1 to 11) and 1B (Tasks 12 to 14) with a checkpoint; outreach is a committed, high-priority 1B capability after Gmail (locked) | Approve | One Phase 1 with all 14 tasks, or move outreach to Phase 2 |
| O-12 | Stale Evaluations (skill, evidence, resume or lane, profile constraints, JD changes) are flagged, never re-run automatically (locked) | Approve | Auto re-run for open high-priority opportunities (more cost, fresher Home) |

## Architecture Checkpoint Report

Frozen and approved on 2026-09-29. Task 1 is authorized; every later task needs explicit approval after the previous task's report.

- **Architecture:** modular monolith; API and worker over PostgreSQL (including the job queue) and S3-compatible storage; Gmail, the LLM and a future enrichment provider behind adapters; Home on attention providers. No additional infrastructure.
- **Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2; React, TypeScript, Vite, TanStack Query; PostgreSQL 16; Docker Compose locally; one container on a PaaS with managed Postgres in production.
- **Domain model:** 31 tables (28 in 1A, 3 in 1B). Opportunity and Application separate; append-only DomainEvents; Skill Inventory with derived multi-class categories; Claims with four evidence classes and an engagement type that is never dropped; Gap only when user-marked; ReviewItem for every system proposal; Evaluations immutable with a staleness basis.
- **Security model:** Google OIDC with server-side sessions; tenant scoping, composite FKs, re-resolution of non-FK IDs, route-generated isolation tests; envelope-encrypted tokens unreachable from the LLM layer; allowlist logging; no autonomous external actions. Not production-grade: no pentest, no RLS, KMS pending.
- **Gmail approach:** `gmail.readonly`; bounded backfill; sync about every 12 hours plus Sync now; capped classification; deterministic matching; every finding through Review; no raw bodies stored.
- **Context and memory approach:** SQL recipes with budgets; Skill Inventory matching before evidence retrieval; manifests on LLM runs; validation of citations, classes, engagement types and INV-13; Evaluations run only on explicit action and are flagged stale by SQL.
- **Phase 1 tasks:** 1A: (1) scaffold; (2) DB foundation; (3) auth; (4) profile and resumes; (5) model gateway and review framework; (6) JD ingestion; (7) state machines; (8) contacts, actions, rules; (9) evidence and Skill Inventory; (10) Home v1; (11) context, Evaluation, chat, feedback loop. 1B: (12) Gmail connect and sync; (13) Gmail intelligence; (14) outreach.
- **Estimated complexity:** eight M tasks (1, 2, 3, 4, 5, 7, 8, 10) and six L tasks (6, 9, 11, 12, 13, 14); roughly 16 to 24 focused agent days for 1A and 8 to 12 for 1B plus owner review (assumption).
- **Remaining owner inputs (non-blocking):** none. LLM cost cap set at $1.00 per user per UTC day (configurable); hosting and production budget deferred, Phase 1 runs locally.

## Change Report: revision 2

Revision 2 adds skills, the skill feedback loop, outreach, an earlier Home and a complexity audit without adding infrastructure or weakening any baseline invariant. Net schema effect: 34 tables become 31 (1 added, 4 merged), and three of the 31 are built only in Phase 1B.

### 1. Requirements added

FR-29 Skill Inventory · FR-30 derived multi-context skill assessment · FR-31 Skills UI · FR-32 skill feedback loop through Review · FR-33 outreach recommendation · FR-34 outreach drafting, never sent · FR-35 manual contact emails and enrichment boundary · FR-36 Gmail relationship proposals only when the email supports them · FR-37 opportunity priority and company strategic priority · FR-38 events extension boundary. Invariants INV-13 (absence of evidence is not a gap), INV-14 (chat never changes evidence directly), INV-15 (drafts cite only manifest evidence and are never sent).

### 2. Existing requirements modified

- FR-05: extraction proposes skills as well as claims.
- FR-09: evaluation uses the Skill Inventory; missing evidence is "not recorded" and becomes a question.
- FR-17: sync about every 12 hours (configurable) plus Sync now, replacing 15 minutes.
- FR-19: every Gmail finding that creates or changes a record goes through Review; the revision-1 auto-apply exception for very strong interaction links is removed.
- FR-20: Home available from Task 10, enriched later.
- FR-24: outreach drafting moved from deferred into Phase 1B (FR-34).
- INV-08: engagement type joins evidence class as user-only.

### 3. Domain-model and schema changes

- Added `skills` (canonical name, normalized key, aliases, confirmation status, gap marker, note, origin, merge redirect, updated\_at).
- `claim_skills` now references `skills` instead of a free-text key.
- Claims: `engagement_type` added; class `gap` removed from claims and represented as `skills.user_marked_gap`.
- Evidence sources: `user_assertion` with `message_id` and verbatim `assertion_text`.
- Profile: `target_roles` and `communication_preferences` as typed JSONB. ResumeLane: `target_role_labels`.
- Company `strategic_priority`; Opportunity `priority` (three user-set levels).
- Evaluation: components, qualification assessments and open questions embedded as typed JSONB; assessment statuses `met`, `partial`, `not_recorded`, `gap`, `blocked`; staleness basis added (superseded in revision 3 by 6.2c).
- RecruitingAction: kinds `attend_interview` and `outreach`; outreach draft and recommendation fields.
- ReviewItem: source `chat`; proposal types `skill`, `skill_evidence`, `interaction`, `contact_link`, `contact_email` added.
- Contact: `emails` as a typed list with per-address source.
- DomainEvent: aggregate types `skill`, `claim`, `contact`, `company`. LlmRun: skill and outreach purposes.

### 4. State-machine changes

New skill and claim confirmation machine (5.4a) with events for proposal, confirmation, merge, gap marking and class changes. RecruitingAction gains scheduled interviews and deadlines, outreach drafts as non-state updates, and outreach completion that requires confirming it was sent. ReviewItem actions renamed to Confirm, Edit + Confirm, Reject / Ignore. New non-stage application event `CONTACT_REPLIED`.

### 5. Context-builder changes

Skill Inventory matching precedes evidence retrieval; evidence is joined through skills; new `skill_clarification` intent; post-validation forbids labeling not-recorded as gap and internships as years of experience; new 6.2a feedback loop; new 6.2b outreach recipe with deterministic overrides; Home chat reads the attention feed.

### 6. Gmail changes

12-hour cadence with jitter; Sync now joins a running sync; visible last-sync time; prefilter now includes contact addresses and notification senders; new categories `contact_reply` and `network_notification`; confirm-all with no exceptions; a proposal-type table covering acknowledgement, rejection, interview, assessment, contact reply, contact link, new email address and connection notifications; explicit rule that Gmail proposes only what an email shows.

### 7. Home and UI changes

New section 7A: attention item contract, deterministic ranking, five intent groups (Now, Pipeline, Decide, Review, Relationships) with the task that first feeds each, UX principles, and a minimal Skills area.

### 8. Phase 1 task-order changes

12 tasks became 14 in two parts. Home moved from Task 12 to Task 10, before evaluation and Gmail. New Task 6 (Skill Inventory). Evaluation (now Task 11) includes chat and the feedback loop. Gmail moved to Tasks 12 and 13; outreach added as Task 14. Checkpoint between 1A and 1B.

### 9. Tables retained, deferred, added, merged

| Change | Tables |
| --- | --- |
| Added | skills |
| Merged away | target\_roles (into profiles), lane\_target\_roles (into resume\_lanes), evaluation\_components and qualification\_assessments (into opportunity\_evaluations) |
| Retained, built in 1B | integrations, integration\_credentials, external\_refs |
| Retained, 1A | the remaining 27 tables listed in section 4.9 |
| Considered, not added | skill\_aliases, contact\_emails, drafts, outreach\_recommendations, networking\_events |

### 10. New open decisions

O-10 internship model; O-11 Phase 1A/1B split with outreach as first cut; O-12 flag rather than auto-re-run stale evaluations.

### 11. Conflicts with the existing architecture

- **Gap as a fifth category vs revision 1's claim class `gap`.** A claim cannot be evidence of absence. Resolved by moving gap to the skill level; the five categories still appear consistently in the UI.
- **"Evidence classification" per skill vs multiple classes per skill.** A single stored class would contradict multi-class provenance. Resolved by deriving the classification on read.
- **Outreach drafting vs a bounded Phase 1.** Revision 1 deferred drafting to keep Phase 1 bounded. Resolved by the 1A/1B split, not by quietly enlarging one phase.
- **12-hour cadence vs Home's "interview today" and "recruiter reply needing action".** Gmail-derived Home items can be up to 12 hours late. Mitigated by visible freshness and Sync now; accepted as a tradeoff.
- **"Must not invent" for drafts.** Free text cannot be proven faithful deterministically. Structured citations and relationship-basis checks are deterministic; the unsupported-sentence checker is a model and can miss things; user review is the final guard.
- **Prefer extending entities vs integrity of contact emails.** Keeping emails on Contact loses a database-level uniqueness constraint; uniqueness is enforced in the service transaction and tested.

### 12. Recommendations I disagree with, and why

- **Internship as a sixth class:** not recommended (O-10). It splits "employment" into two classes and loses a home for part-time and contract work; engagement type states the truthful difference more cleanly.
- **Changing a skill's classification directly:** the Skills UI changes the class of the underlying evidence (with confirmation), not a skill-level field. A skill-level override would hide provenance and let the classification drift from its evidence.
- **Outreach drafting in Phase 1:** accepted into 1B, but it is the least necessary piece for Career OS to become useful and depends on contact data that 1A creates. It should be cut first if 1B runs long. (Superseded in revision 3 by O-11: outreach is a committed, high-priority 1B capability.)
- **Confirm-all for exact contact-address interactions:** applied as requested, but these are the lowest-risk proposals and the first candidates for an auto-apply ADR once precision is measured; confirm-all may create avoidable review load.
- **Strategic company importance:** implemented as a three-level user field only. Inferring importance automatically would recreate the fake-certainty scoring the spec rejects.

## Revision 3: decisions and freeze audit

The audit of all sections found 9 blockers, all fixed in this revision; nothing else was redesigned.

| # | Blocker found | Fix |
| --- | --- | --- |
| 1 | Evaluation "fingerprint" relied on version counters (Skill Inventory version, company-history version) that no table defined, and included triggers outside O-12 | Replaced by a stored basis on each Evaluation and a SQL staleness rule (6.2c) using existing timestamps plus `opportunities.content_updated_at` and `profiles.constraints_updated_at` |
| 2 | Chat step 3 could "enqueue or stream a new evaluation" automatically | Evaluations run only on explicit Evaluate / Re-evaluate (6.2 step 3, INV-17) |
| 3 | Internship could count toward years of experience through an undefined per-evaluation opt-in, and unverified extracted claims could default to full-time | Opt-in removed; `unspecified` engagement type added and treated conservatively; INV-16 |
| 4 | IDs inside JSONB, arrays and job payloads had no isolation rule | Convention and INV-18: re-resolve through user-scoped repositories; isolation tests extended |
| 5 | Immutable events and evaluations had no rule for JSONB schema changes | Upcasters in code for immutable rows, data migrations for mutable rows (4.1) |
| 6 | Only Application declared `state_version`, while 5.5 required it for every command | Convention covers every aggregate with a state machine |
| 7 | Claim status `edited` conflicted with edits being events; RecruitingAction kind `review` duplicated ReviewItem | `edited` became the CLAIM\_EDITED event; kind `review` removed |
| 8 | A confirmed Gmail acknowledgement for a Skipped or Closed opportunity had no legal transition; 7.5 still said a contact address match "links" automatically | Skipped and Closed → Applied allowed via Apply or confirmed ReviewItem; 7.5 now proposes through Review |
| 9 | Scheduled Gmail classification, including the 90-day backfill, had no cost bound | Per-sync and per-day caps with a visible waiting count (7.4) |

Also corrected: task order aligned to the locked priority list (manual workflow before evidence), the audit table's build tasks, duplicate manifests removed from Evaluation and Message (kept on the LLM run), the Evaluation dimension list restored, ExternalRef scope narrowed to Gmail in Phase 1, Skills filter semantics, test coverage for the new rules, a canonical-terms section (0A), and the intent `explain_gap` renamed `explain_missing_requirement`.
