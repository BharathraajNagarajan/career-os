import threading
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.ids import new_id
from app.db.models import (
    Profile,
    ProposalType,
    ReviewItem,
    ReviewSource,
    ReviewStatus,
)
from app.db.tenancy import NotFound
from app.db.versioning import ConcurrencyConflict
from app.review.errors import InvalidPayload, InvalidTransition, NoHandler
from app.review.repository import ReviewItemRepository
from app.review.service import ReviewService
from tests.db.factories import make_user
from tests.db.llm_helpers import VALID, make_gateway, structured
from tests.db.review_helpers import RecordingRegistry, SkillNote, create_item, recording_registry

pytestmark = pytest.mark.db


@pytest.fixture
def user_id(session: Session) -> uuid.UUID:
    user = make_user(session)
    session.commit()
    return user.id


@pytest.fixture
def registry() -> RecordingRegistry:
    return recording_registry()


def reload(session: Session, item_id: uuid.UUID) -> ReviewItem:
    session.rollback()
    return session.scalars(
        select(ReviewItem).where(ReviewItem.id == item_id).execution_options(populate_existing=True)
    ).one()


def headline(session: Session, user_id: uuid.UUID) -> str | None:
    session.rollback()
    return session.scalars(select(Profile.headline).where(Profile.user_id == user_id)).one_or_none()


def test_create_stores_a_pending_item_with_provenance_fields(
    app_sessions: sessionmaker[Session],
    session: Session,
    user_id: uuid.UUID,
    registry: RecordingRegistry,
) -> None:
    gateway, _ = make_gateway(app_sessions, script=[VALID])
    run_id = structured(gateway, user_id).run_id

    item_id = create_item(app_sessions, registry, user_id, llm_run_id=run_id)

    item = reload(session, item_id)
    assert item.status is ReviewStatus.PENDING
    assert item.state_version == 1
    assert item.decided_at is None
    assert item.llm_run_id == run_id
    assert item.source is ReviewSource.EXTRACTION
    assert item.confidence == Decimal("0.800")
    assert item.proposed_payload == {"schema_version": 1, "name": "Synthetic skill"}


def test_create_validates_against_the_registered_payload_model(
    app_sessions: sessionmaker[Session], user_id: uuid.UUID, registry: RecordingRegistry
) -> None:
    with pytest.raises(InvalidPayload):
        create_item(app_sessions, registry, user_id, payload={"schema_version": 1, "name": ""})
    with pytest.raises(InvalidPayload):
        create_item(app_sessions, registry, user_id, payload={"schema_version": 1, "extra": "x"})


def test_create_without_a_handler_needs_a_schema_version(
    app_sessions: sessionmaker[Session], session: Session, user_id: uuid.UUID
) -> None:
    empty = recording_registry()
    with pytest.raises(InvalidPayload):
        create_item(
            app_sessions,
            empty,
            user_id,
            proposal_type=ProposalType.CLAIM,
            payload={"anything": "goes"},
        )

    item_id = create_item(
        app_sessions,
        empty,
        user_id,
        proposal_type=ProposalType.CLAIM,
        payload={"schema_version": 1, "text": "x"},
    )

    assert reload(session, item_id).proposal_type is ProposalType.CLAIM


def test_a_run_owned_by_another_user_cannot_be_linked(
    app_sessions: sessionmaker[Session],
    session: Session,
    user_id: uuid.UUID,
    registry: RecordingRegistry,
) -> None:
    other = make_user(session)
    session.commit()
    gateway, _ = make_gateway(app_sessions, script=[VALID])
    foreign_run = structured(gateway, other.id).run_id

    with pytest.raises(IntegrityError):
        create_item(app_sessions, registry, user_id, llm_run_id=foreign_run)


def test_evidence_ref_is_a_plain_uuid_without_a_foreign_key(
    session: Session, user_id: uuid.UUID, registry: RecordingRegistry
) -> None:
    item = ReviewItemRepository(session).create(
        user_id=user_id,
        registry=registry,
        source=ReviewSource.GMAIL,
        proposal_type=ProposalType.SKILL,
        payload=SkillNote(name="x"),
        evidence_ref_id=new_id(),
    )
    session.commit()

    assert item.evidence_ref_id is not None


def test_confirm_runs_the_domain_command_and_marks_the_item_confirmed(
    app_sessions: sessionmaker[Session],
    session: Session,
    user_id: uuid.UUID,
    registry: RecordingRegistry,
) -> None:
    item_id = create_item(app_sessions, registry, user_id, name="Confirmed name")

    with app_sessions() as work:
        result = ReviewService(work, registry).confirm(
            user_id=user_id, item_id=item_id, expected_state_version=1
        )

    assert result.status is ReviewStatus.CONFIRMED
    assert result.state_version == 2
    assert result.decided_at is not None
    assert result.decided_payload is None
    session.rollback()
    stored_null: bool = session.execute(
        text("SELECT decided_payload IS NULL FROM review_items WHERE id = :id"), {"id": item_id}
    ).scalar_one()
    assert stored_null is True
    assert registry.recorder.calls == [(item_id, "Confirmed name")]
    assert headline(session, user_id) == "Confirmed name"


def test_edit_confirm_validates_applies_and_stores_the_edited_payload(
    app_sessions: sessionmaker[Session],
    session: Session,
    user_id: uuid.UUID,
    registry: RecordingRegistry,
) -> None:
    item_id = create_item(app_sessions, registry, user_id, name="Original")

    with app_sessions() as work:
        result = ReviewService(work, registry).edit_confirm(
            user_id=user_id,
            item_id=item_id,
            expected_state_version=1,
            payload={"schema_version": 1, "name": "Edited"},
        )

    assert result.status is ReviewStatus.CONFIRMED
    assert result.decided_payload == {"schema_version": 1, "name": "Edited"}
    assert result.proposed_payload == {"schema_version": 1, "name": "Original"}
    assert registry.recorder.calls == [(item_id, "Edited")]
    assert headline(session, user_id) == "Edited"


def test_edit_confirm_with_an_invalid_payload_changes_nothing(
    app_sessions: sessionmaker[Session],
    session: Session,
    user_id: uuid.UUID,
    registry: RecordingRegistry,
) -> None:
    item_id = create_item(app_sessions, registry, user_id)

    with app_sessions() as work, pytest.raises(InvalidPayload):
        ReviewService(work, registry).edit_confirm(
            user_id=user_id,
            item_id=item_id,
            expected_state_version=1,
            payload={"schema_version": 1, "name": ""},
        )

    item = reload(session, item_id)
    assert (item.status, item.state_version) == (ReviewStatus.PENDING, 1)
    assert registry.recorder.calls == []


def test_reject_records_the_note_and_never_calls_a_handler(
    app_sessions: sessionmaker[Session],
    session: Session,
    user_id: uuid.UUID,
    registry: RecordingRegistry,
) -> None:
    item_id = create_item(app_sessions, registry, user_id)

    with app_sessions() as work:
        result = ReviewService(work, registry).reject(
            user_id=user_id, item_id=item_id, expected_state_version=1, note="not recruiting"
        )

    assert result.status is ReviewStatus.REJECTED
    assert result.decision_note == "not recruiting"
    assert result.decided_at is not None
    assert registry.recorder.calls == []
    assert headline(session, user_id) is None


def test_an_item_without_a_handler_cannot_be_confirmed_but_can_be_rejected(
    app_sessions: sessionmaker[Session], session: Session, user_id: uuid.UUID
) -> None:
    empty = recording_registry()
    item_id = create_item(
        app_sessions,
        empty,
        user_id,
        proposal_type=ProposalType.CLAIM,
        payload={"schema_version": 1},
    )

    with app_sessions() as work:
        service = ReviewService(work, empty)
        with pytest.raises(NoHandler):
            service.confirm(user_id=user_id, item_id=item_id, expected_state_version=1)
        with pytest.raises(NoHandler):
            service.edit_confirm(
                user_id=user_id,
                item_id=item_id,
                expected_state_version=1,
                payload={"schema_version": 1},
            )
        assert reload(session, item_id).status is ReviewStatus.PENDING
        rejected = service.reject(
            user_id=user_id, item_id=item_id, expected_state_version=1, note=None
        )

    assert rejected.status is ReviewStatus.REJECTED


def test_a_stale_state_version_is_a_conflict_and_nothing_runs(
    app_sessions: sessionmaker[Session],
    session: Session,
    user_id: uuid.UUID,
    registry: RecordingRegistry,
) -> None:
    item_id = create_item(app_sessions, registry, user_id)

    def confirm(service: ReviewService) -> None:
        service.confirm(user_id=user_id, item_id=item_id, expected_state_version=7)

    def edit_confirm(service: ReviewService) -> None:
        service.edit_confirm(
            user_id=user_id,
            item_id=item_id,
            expected_state_version=7,
            payload={"schema_version": 1, "name": "x"},
        )

    def reject(service: ReviewService) -> None:
        service.reject(user_id=user_id, item_id=item_id, expected_state_version=7, note=None)

    for action in (confirm, edit_confirm, reject):
        with app_sessions() as work, pytest.raises(ConcurrencyConflict):
            action(ReviewService(work, registry))

    assert reload(session, item_id).status is ReviewStatus.PENDING
    assert registry.recorder.calls == []


@pytest.mark.parametrize("first", ["confirm", "reject"])
@pytest.mark.parametrize("second", ["confirm", "edit_confirm", "reject"])
def test_a_decided_item_cannot_be_decided_again(
    app_sessions: sessionmaker[Session],
    user_id: uuid.UUID,
    registry: RecordingRegistry,
    first: str,
    second: str,
) -> None:
    item_id = create_item(app_sessions, registry, user_id)

    def act(name: str, version: int) -> None:
        with app_sessions() as work:
            service = ReviewService(work, registry)
            if name == "confirm":
                service.confirm(user_id=user_id, item_id=item_id, expected_state_version=version)
            elif name == "edit_confirm":
                service.edit_confirm(
                    user_id=user_id,
                    item_id=item_id,
                    expected_state_version=version,
                    payload={"schema_version": 1, "name": "again"},
                )
            else:
                service.reject(
                    user_id=user_id, item_id=item_id, expected_state_version=version, note=None
                )

    act(first, 1)
    calls_after_first = list(registry.recorder.calls)

    with pytest.raises(InvalidTransition):
        act(second, 2)

    assert registry.recorder.calls == calls_after_first


def test_a_failing_handler_rolls_everything_back(
    app_sessions: sessionmaker[Session],
    session: Session,
    user_id: uuid.UUID,
    registry: RecordingRegistry,
) -> None:
    item_id = create_item(app_sessions, registry, user_id)
    registry.recorder.fail = True

    with app_sessions() as work, pytest.raises(RuntimeError):
        ReviewService(work, registry).confirm(
            user_id=user_id, item_id=item_id, expected_state_version=1
        )

    item = reload(session, item_id)
    assert item.status is ReviewStatus.PENDING
    assert item.state_version == 1
    assert item.decided_at is None
    assert registry.recorder.calls == [(item_id, "Synthetic skill")]
    assert headline(session, user_id) is None

    registry.recorder.fail = False
    with app_sessions() as work:
        ReviewService(work, registry).confirm(
            user_id=user_id, item_id=item_id, expected_state_version=1
        )
    assert headline(session, user_id) == "Synthetic skill"


def test_concurrent_confirmations_apply_the_command_exactly_once(
    app_sessions: sessionmaker[Session],
    session: Session,
    user_id: uuid.UUID,
    registry: RecordingRegistry,
) -> None:
    item_id = create_item(app_sessions, registry, user_id)
    barrier = threading.Barrier(2)
    outcomes: list[object] = []

    def worker() -> None:
        with app_sessions() as work:
            service = ReviewService(work, registry)
            item = service.get(user_id=user_id, item_id=item_id)
            barrier.wait(timeout=10)
            try:
                outcomes.append(
                    service.confirm(
                        user_id=user_id, item_id=item_id, expected_state_version=item.state_version
                    ).status
                )
            except ConcurrencyConflict as exc:
                outcomes.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(type(outcome).__name__ for outcome in outcomes) == [
        "ConcurrencyConflict",
        "ReviewStatus",
    ]
    assert len(registry.recorder.calls) == 1
    assert reload(session, item_id).state_version == 2


def test_other_users_items_are_not_found(
    app_sessions: sessionmaker[Session],
    session: Session,
    user_id: uuid.UUID,
    registry: RecordingRegistry,
) -> None:
    other = make_user(session)
    session.commit()
    item_id = create_item(app_sessions, registry, user_id)

    with app_sessions() as work:
        service = ReviewService(work, registry)
        with pytest.raises(NotFound):
            service.get(user_id=other.id, item_id=item_id)
        with pytest.raises(NotFound):
            service.confirm(user_id=other.id, item_id=item_id, expected_state_version=1)
        with pytest.raises(NotFound):
            service.reject(user_id=other.id, item_id=item_id, expected_state_version=1, note=None)
    assert registry.recorder.calls == []


def test_list_returns_only_the_callers_items_newest_first_with_a_status_filter(
    app_sessions: sessionmaker[Session],
    session: Session,
    user_id: uuid.UUID,
    registry: RecordingRegistry,
) -> None:
    other = make_user(session)
    session.commit()
    first = create_item(app_sessions, registry, user_id, name="first")
    second = create_item(app_sessions, registry, user_id, name="second")
    create_item(app_sessions, registry, other.id, name="foreign")
    with app_sessions() as work:
        ReviewService(work, registry).reject(
            user_id=user_id, item_id=first, expected_state_version=1, note=None
        )

    with app_sessions() as work:
        service = ReviewService(work, registry)
        everything = service.list(user_id=user_id, status=None, limit=10)
        pending = service.list(user_id=user_id, status=ReviewStatus.PENDING, limit=10)

    assert [item.id for item in everything] == [second, first]
    assert [item.id for item in pending] == [second]


def test_app_role_can_neither_delete_review_items_nor_rewrite_the_proposal(
    app_sessions: sessionmaker[Session],
    session: Session,
    user_id: uuid.UUID,
    registry: RecordingRegistry,
) -> None:
    create_item(app_sessions, registry, user_id)
    from tests.db.test_roles import assert_denied

    assert_denied(session, "DELETE FROM review_items")
    assert_denied(session, "UPDATE review_items SET proposed_payload = '{}'::jsonb")
    assert_denied(session, "UPDATE review_items SET proposal_type = 'claim'")
    assert_denied(session, "UPDATE review_items SET user_id = gen_random_uuid()")
    assert_denied(session, "TRUNCATE review_items")


@pytest.mark.parametrize(
    "assignment",
    [
        "status = 'pending', decided_at = now()",
        "status = 'confirmed', decided_at = NULL",
        "status = 'rejected', decided_at = now(), decided_payload = '{\"schema_version\": 1}'",
        "decided_payload = '[]'::jsonb, status = 'confirmed', decided_at = now()",
        "status = 'archived'",
    ],
)
def test_the_database_rejects_inconsistent_review_states(
    app_sessions: sessionmaker[Session],
    session: Session,
    user_id: uuid.UUID,
    registry: RecordingRegistry,
    assignment: str,
) -> None:
    create_item(app_sessions, registry, user_id)

    with pytest.raises(IntegrityError):
        session.execute(text("UPDATE review_items SET " + assignment))  # noqa: S608
    session.rollback()


def test_confidence_must_be_a_fraction(
    session: Session, user_id: uuid.UUID, registry: RecordingRegistry
) -> None:
    with pytest.raises(IntegrityError):
        ReviewItemRepository(session).create(
            user_id=user_id,
            registry=registry,
            source=ReviewSource.CHAT,
            proposal_type=ProposalType.SKILL,
            payload=SkillNote(name="x"),
            confidence=Decimal("1.500"),
        )
    session.rollback()
