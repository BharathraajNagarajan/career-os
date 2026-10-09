import uuid
from collections.abc import Callable
from functools import partial
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Company, CompanyOrigin, ResumeLane
from tests.db.contact_helpers import EMPTY_EMAILS, insert_row
from tests.db.factories import make_user
from tests.db.test_application_schema import make_application
from tests.db.test_opportunity_schema import make_artifact, make_opportunity
from tests.db.test_roles import assert_denied

pytestmark = pytest.mark.db


@pytest.fixture
def user_id(session: Session) -> uuid.UUID:
    user = make_user(session)
    session.commit()
    return user.id


def contact(session: Session, user_id: uuid.UUID, **extra: Any) -> uuid.UUID:
    return insert_row(
        session, "contacts", user_id=user_id, full_name="Alex Example", emails=EMPTY_EMAILS, **extra
    )


def company(session: Session, user_id: uuid.UUID) -> uuid.UUID:
    row = Company(
        user_id=user_id,
        name="Example Corp",
        normalized_name=uuid.uuid4().hex,
        origin=CompanyOrigin.USER,
    )
    session.add(row)
    session.flush()
    return row.id


def lane(session: Session, user_id: uuid.UUID) -> uuid.UUID:
    row = ResumeLane(user_id=user_id, name=f"lane {uuid.uuid4().hex}")
    session.add(row)
    session.flush()
    return row.id


def interaction(session: Session, user_id: uuid.UUID, contact_id: uuid.UUID, **extra: Any) -> Any:
    return insert_row(
        session,
        "interactions",
        user_id=user_id,
        contact_id=contact_id,
        channel="email",
        direction="outbound",
        occurred_at="2026-01-01T00:00:00Z",
        **extra,
    )


def action(session: Session, user_id: uuid.UUID, **extra: Any) -> uuid.UUID:
    values: dict[str, Any] = {"kind": "custom", "title": "Follow up", "origin": "user", **extra}
    return insert_row(session, "recruiting_actions", user_id=user_id, **values)


def rule(session: Session, user_id: uuid.UUID, **extra: Any) -> uuid.UUID:
    values: dict[str, Any] = {
        "scope": "global",
        "statement": "Wait a week",
        "rule_type": "cooldown",
    }
    return insert_row(session, "strategy_rules", user_id=user_id, **{**values, **extra})


def rejected(session: Session, write: Callable[[], object], match: str | None = None) -> None:
    with pytest.raises(IntegrityError, match=match):
        write()
    session.rollback()


def test_contact_defaults_and_closed_source(session: Session, user_id: uuid.UUID) -> None:
    contact_id = contact(session, user_id)
    session.commit()

    row = session.execute(
        text("SELECT source, notes, created_at, updated_at FROM contacts WHERE id = :id"),
        {"id": contact_id},
    ).one()
    assert (row.source, row.notes) == ("manual", "")
    assert row.created_at is not None
    assert row.updated_at is not None
    rejected(session, lambda: contact(session, user_id, source="event"), "ck_contacts_source")
    rejected(
        session,
        lambda: insert_row(session, "contacts", user_id=user_id, full_name="", emails=EMPTY_EMAILS),
        "full_name_length",
    )
    rejected(
        session,
        lambda: session.execute(
            text(
                "INSERT INTO contacts (id, user_id, full_name, emails) "
                "VALUES (gen_random_uuid(), :user, 'Alex Example', '[]'::jsonb)"
            ),
            {"user": user_id},
        ),
        "emails_object",
    )


def test_contact_emails_have_a_gin_index(owner_session: Session) -> None:
    method: str = owner_session.execute(
        text(
            "SELECT am.amname FROM pg_class c JOIN pg_am am ON am.oid = c.relam "
            "WHERE c.relname = 'ix_contacts_emails'"
        )
    ).scalar_one()
    assert method == "gin"


def test_link_tables_enforce_enums_and_uniqueness(session: Session, user_id: uuid.UUID) -> None:
    contact_id = contact(session, user_id)
    company_id = company(session, user_id)
    opportunity = make_opportunity(session, user_id)
    insert_row(
        session,
        "contact_companies",
        user_id=user_id,
        contact_id=contact_id,
        company_id=company_id,
        relation="recruiter",
    )
    insert_row(
        session,
        "contact_opportunities",
        user_id=user_id,
        contact_id=contact_id,
        opportunity_id=opportunity.id,
        role="recruiter",
    )
    session.commit()

    rejected(
        session,
        lambda: insert_row(
            session,
            "contact_companies",
            user_id=user_id,
            contact_id=contact_id,
            company_id=company_id,
            relation="employee",
        ),
        "uq_contact_companies",
    )
    rejected(
        session,
        lambda: insert_row(
            session,
            "contact_companies",
            user_id=user_id,
            contact_id=contact_id,
            company_id=company(session, user_id),
            relation="friend",
        ),
        "ck_contact_companies_relation",
    )
    rejected(
        session,
        lambda: insert_row(
            session,
            "contact_opportunities",
            user_id=user_id,
            contact_id=contact_id,
            opportunity_id=opportunity.id,
            role="recruiter",
        ),
        "uq_contact_opportunities",
    )
    rejected(
        session,
        lambda: insert_row(
            session,
            "contact_opportunities",
            user_id=user_id,
            contact_id=contact_id,
            opportunity_id=opportunity.id,
            role="mentor",
        ),
        "ck_contact_opportunities_role",
    )
    insert_row(
        session,
        "contact_opportunities",
        user_id=user_id,
        contact_id=contact_id,
        opportunity_id=opportunity.id,
        role="referrer",
    )
    session.commit()


def test_interaction_checks(session: Session, user_id: uuid.UUID) -> None:
    contact_id = contact(session, user_id)
    session.commit()

    interaction(session, user_id, contact_id, summary="x" * 2000)
    session.commit()
    rejected(
        session, lambda: interaction(session, user_id, contact_id, summary="x" * 2001), "summary"
    )
    rejected(
        session,
        lambda: insert_row(
            session,
            "interactions",
            user_id=user_id,
            contact_id=contact_id,
            channel="fax",
            direction="outbound",
            occurred_at="2026-01-01T00:00:00Z",
        ),
        "ck_interactions_channel",
    )
    rejected(
        session,
        lambda: insert_row(
            session,
            "interactions",
            user_id=user_id,
            contact_id=contact_id,
            channel="email",
            direction="sideways",
            occurred_at="2026-01-01T00:00:00Z",
        ),
        "ck_interactions_direction",
    )


def test_recruiting_action_checks(session: Session, user_id: uuid.UUID) -> None:
    action(session, user_id)
    action(session, user_id, kind="attend_interview", due_at="2026-02-01T10:00:00Z")
    action(session, user_id, status="snoozed", snoozed_until="2026-02-01T10:00:00Z")
    session.commit()

    for field, value, name in (
        ("kind", "review", "ck_recruiting_actions_kind"),
        ("status", "paused", "ck_recruiting_actions_status"),
        ("origin", "robot", "ck_recruiting_actions_origin"),
        ("sequence_no", 0, "sequence_no_positive"),
        ("title", "", "title_length"),
        ("title", "t" * 201, "title_length"),
    ):
        rejected(session, partial(action, session, user_id, **{field: value}), name)
    rejected(session, lambda: action(session, user_id, status="snoozed"), "snooze_consistent")
    rejected(
        session,
        lambda: action(session, user_id, snoozed_until="2026-02-01T10:00:00Z"),
        "snooze_consistent",
    )
    for kind in ("attend_interview", "complete_assessment"):
        rejected(session, partial(action, session, user_id, kind=kind), "scheduled_kinds")
    rejected(
        session, lambda: action(session, user_id, draft_subject="Hello"), "draft_only_for_outreach"
    )
    action(session, user_id, kind="outreach", draft_subject="Hello", draft_body="Hi")
    session.commit()


def test_strategy_rule_scope_must_match_its_target(session: Session, user_id: uuid.UUID) -> None:
    company_id = company(session, user_id)
    lane_id = lane(session, user_id)
    rule(session, user_id)
    rule(session, user_id, scope="company", company_id=company_id)
    rule(session, user_id, scope="lane", lane_id=lane_id, rule_type="preference")
    session.commit()

    for extra in (
        {"scope": "global", "company_id": company_id},
        {"scope": "global", "lane_id": lane_id},
        {"scope": "company"},
        {"scope": "company", "company_id": company_id, "lane_id": lane_id},
        {"scope": "lane", "company_id": company_id},
        {"scope": "lane"},
    ):
        rejected(session, partial(rule, session, user_id, **extra), "scope_matches_target")
    rejected(session, lambda: rule(session, user_id, scope="team"), "ck_strategy_rules_scope")
    rejected(session, lambda: rule(session, user_id, rule_type="wish"), "ck_strategy_rules_rule")
    rejected(session, lambda: rule(session, user_id, statement=""), "statement_length")
    rejected(
        session,
        lambda: session.execute(
            text(
                "INSERT INTO strategy_rules (id, user_id, scope, statement, rule_type, condition) "
                "VALUES (gen_random_uuid(), :user, 'global', 'x', 'cooldown', '[]'::jsonb)"
            ),
            {"user": user_id},
        ),
        "condition_object",
    )


def test_a_cross_user_reference_cannot_be_written(session: Session, user_id: uuid.UUID) -> None:
    other = make_user(session)
    session.commit()
    foreign_contact = contact(session, other.id)
    foreign_company = company(session, other.id)
    foreign_opportunity = make_opportunity(session, other.id)
    foreign_application = make_application(session, other.id, foreign_opportunity.id)
    foreign_artifact = make_artifact(session, other.id)
    foreign_lane = lane(session, other.id)
    foreign_interaction = interaction(session, other.id, foreign_contact)
    mine = contact(session, user_id)
    my_opportunity = make_opportunity(session, user_id)
    session.commit()

    attempts: list[tuple[str, dict[str, Any]]] = [
        (
            "contact_companies",
            {"contact_id": foreign_contact, "company_id": company(session, user_id)},
        ),
        ("contact_companies", {"contact_id": mine, "company_id": foreign_company}),
        (
            "contact_opportunities",
            {"contact_id": foreign_contact, "opportunity_id": my_opportunity.id, "role": "other"},
        ),
        (
            "contact_opportunities",
            {"contact_id": mine, "opportunity_id": foreign_opportunity.id, "role": "other"},
        ),
        ("interactions", {"contact_id": foreign_contact}),
        ("interactions", {"contact_id": mine, "company_id": foreign_company}),
        ("interactions", {"contact_id": mine, "opportunity_id": foreign_opportunity.id}),
        ("interactions", {"contact_id": mine, "application_id": foreign_application.id}),
        ("interactions", {"contact_id": mine, "artifact_id": foreign_artifact.id}),
        ("recruiting_actions", {"opportunity_id": foreign_opportunity.id}),
        ("recruiting_actions", {"application_id": foreign_application.id}),
        ("recruiting_actions", {"contact_id": foreign_contact}),
        ("recruiting_actions", {"interaction_id": foreign_interaction}),
        ("strategy_rules", {"scope": "company", "company_id": foreign_company}),
        ("strategy_rules", {"scope": "lane", "lane_id": foreign_lane}),
    ]
    defaults: dict[str, dict[str, Any]] = {
        "contact_companies": {"relation": "other"},
        "contact_opportunities": {},
        "interactions": {
            "channel": "email",
            "direction": "inbound",
            "occurred_at": "2026-01-01T00:00:00Z",
        },
        "recruiting_actions": {"kind": "custom", "title": "t", "origin": "user"},
        "strategy_rules": {"statement": "s", "rule_type": "preference"},
    }
    for table, values in attempts:
        rejected(
            session,
            partial(insert_row, session, table, user_id=user_id, **{**defaults[table], **values}),
            "fk_",
        )


def test_grants_match_the_design(session: Session, user_id: uuid.UUID) -> None:
    contact_id = contact(session, user_id)
    company_id = company(session, user_id)
    link = insert_row(
        session,
        "contact_companies",
        user_id=user_id,
        contact_id=contact_id,
        company_id=company_id,
    )
    interaction_id = interaction(session, user_id, contact_id, summary="Hello")
    action_id = action(session, user_id)
    rule_id = rule(session, user_id)
    spare = contact(session, user_id)
    session.commit()

    session.execute(text("UPDATE contacts SET headline = 'x' WHERE id = :id"), {"id": contact_id})
    session.execute(
        text("UPDATE interactions SET contact_id = :spare WHERE id = :id"),
        {"spare": spare, "id": interaction_id},
    )
    session.execute(
        text("UPDATE recruiting_actions SET title = 'y' WHERE id = :id"), {"id": action_id}
    )
    session.execute(
        text("UPDATE strategy_rules SET active = false WHERE id = :id"), {"id": rule_id}
    )
    session.commit()

    assert_denied(session, "UPDATE interactions SET summary = 'rewritten'")
    assert_denied(session, "UPDATE interactions SET occurred_at = now()")
    assert_denied(session, "DELETE FROM interactions")
    assert_denied(session, "DELETE FROM recruiting_actions")
    for table in (
        "contacts",
        "contact_companies",
        "contact_opportunities",
        "interactions",
        "recruiting_actions",
        "strategy_rules",
    ):
        assert_denied(session, f"TRUNCATE {table}")

    session.execute(text("DELETE FROM contact_companies WHERE id = :id"), {"id": link})
    session.execute(text("DELETE FROM strategy_rules WHERE id = :id"), {"id": rule_id})
    session.execute(text("DELETE FROM contacts WHERE id = :id"), {"id": contact_id})
    session.commit()


def test_deleting_the_user_cascades_to_every_new_table(
    session: Session, owner_session: Session, user_id: uuid.UUID
) -> None:
    contact_id = contact(session, user_id)
    company_id = company(session, user_id)
    opportunity = make_opportunity(session, user_id, company_id=company_id)
    interaction_id = interaction(session, user_id, contact_id)
    insert_row(
        session, "contact_companies", user_id=user_id, contact_id=contact_id, company_id=company_id
    )
    insert_row(
        session,
        "contact_opportunities",
        user_id=user_id,
        contact_id=contact_id,
        opportunity_id=opportunity.id,
        role="other",
    )
    action(session, user_id, contact_id=contact_id, interaction_id=interaction_id)
    rule(session, user_id, scope="company", company_id=company_id)
    session.commit()

    owner_session.execute(
        text("UPDATE users SET status = 'deletion_requested' WHERE id = :id"), {"id": user_id}
    )
    owner_session.execute(text("SELECT public.delete_user_account(:id)"), {"id": user_id})
    owner_session.commit()

    for table in (
        "contacts",
        "contact_companies",
        "contact_opportunities",
        "interactions",
        "recruiting_actions",
        "strategy_rules",
    ):
        remaining: int = owner_session.execute(
            text(f"SELECT count(*) FROM {table} WHERE user_id = :id"),  # noqa: S608
            {"id": user_id},
        ).scalar_one()
        assert remaining == 0, table
