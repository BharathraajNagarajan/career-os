# Review framework

Spec references: 1.3 (INV-07, INV-14, INV-18), 2.1, 4.1, 4.5, 5.4, 9, 11.

A review item is a proposal waiting for the user. Models, Gmail and chat may only propose; a person confirms, edits or rejects, and confirming runs the same domain command a manual action would. The framework never writes domain state itself.

## Lifecycle

```
pending ──confirm / edit + confirm──▶ confirmed
   ├──────reject / ignore───────────▶ rejected
   └──────expire (target changed)───▶ expired
```

`transition(status, action)` in `app/review/transitions.py` is a pure function: from `pending` it returns the target of `confirm`, `reject` or `expire`; from any other status it raises `InvalidTransition`. Tests cover every status and action pair. Expiry automation is not built (no producer needs it yet); the state and the transition exist. A confirmed item is undone by the owning aggregate's correction command, never by deleting rows.

## Commands

| Command | Endpoint | Effect |
| --- | --- | --- |
| Confirm | `POST /api/v1/review-items/{id}/confirm` | Apply `proposed_payload` through the registered handler |
| Edit + Confirm | `POST …/edit-confirm` | Validate the user's payload with the same model, apply it, keep it in `decided_payload` (the original proposal stays unchanged) |
| Reject / Ignore | `POST …/reject` | Status `rejected`, optional `note` kept in `decision_note` |

Reads: `GET /api/v1/review-items?status=pending` (the caller's items, newest first) and `GET …/{id}`. Every item carries `confirmable`, true when a handler is registered for its type. Foreign ids return 404.

Each command is one transaction, in this order:

1. Load the item through the user-scoped repository (`NotFound` for another user's id).
2. Compare the client's `expected_state_version` with the stored one; a mismatch is a conflict (409 `conflict`).
3. Check the transition (409 `invalid_transition` for an item that is no longer pending).
4. For confirm and edit: find the handler (422 `no_handler` if none) and validate the payload (422 `invalid_payload`). All of this happens before anything is written.
5. `UPDATE … WHERE id AND user_id AND state_version = expected`, bumping the version. This claims the item.
6. Run the handler's domain command in the same transaction.
7. Commit. Any exception rolls back everything, so a failing handler leaves the item pending with its version unchanged.

Claiming the row (step 5) before running the handler is deliberate. If two requests read version 1 at the same moment and the handler ran first, both would apply the command. With the claim first, the second request's `UPDATE` blocks on the row lock until the first commits, then matches zero rows and gets the conflict. A threaded test with real Postgres proves the command runs exactly once.

## Optimistic concurrency

Pessimistic locking holds a lock while a person thinks; optimistic concurrency does not. The client sends the `state_version` it saw. If anyone changed the item since, the update touches zero rows and the client gets 409 and must reload. The Review page shows a plain message and refreshes.

## Registering a handler (for Tasks 6, 9 and 13)

```python
class SkillProposal(BaseModel):
    schema_version: int = 1
    name: str

def confirm_skill(context: ReviewContext, payload: SkillProposal) -> None:
    SkillService(context.session).add(user_id=context.user_id, name=payload.name, ...)

registry.register(ReviewHandler(ProposalType.SKILL, SkillProposal, confirm_skill))
```

- `confirm` receives a `ReviewContext` (session, user id, review item id, optional `llm_run_id`) and calls the same service method the manual UI action calls. It must not commit; the framework commits.
- The payload model is the single schema for the proposal, the edit form and the command input.
- Producers create items with `ReviewItemRepository.create(...)`, which validates the payload against the registered model, or, when no handler is registered, requires an integer `schema_version`. They pass `llm_run_id` from the gateway's `StructuredResult.run_id` for provenance.
- Handlers are registered on the application's `ReviewHandlerRegistry` (`create_app(review_registry=...)`). Production registers none yet, so every item is rejectable but not confirmable until its producer ships; tests use a recording registry with a synthetic type.

`evidence_ref_id` is a plain uuid (the tables it will point at do not exist yet) and must be re-resolved through a user-scoped repository before use (INV-18). Proposal payloads are plain data; the UI renders them as text, never HTML (T5).

## Boundaries

`app/review` may import only its own modules, logging, the tenancy and versioning helpers, and the review tables. It cannot reach domain tables or the LLM layer; domain effects happen inside handlers registered by the domain modules. `tests/test_boundaries.py` enforces this.
