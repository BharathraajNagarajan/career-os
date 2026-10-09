import threading
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.auth.fake_idp import FakeIdentityProvider
from tests.db.application_helpers import new_opportunity
from tests.db.auth_helpers import Persona, make_persona
from tests.db.contact_helpers import (
    CONTACTS,
    action_command,
    body_of,
    create_action,
    create_company,
    create_contact,
    create_interaction,
    error_code,
    get_contact,
    merge,
    patch_contact,
)
from tests.db.opportunity_helpers import rows, scalar

pytestmark = pytest.mark.db


@pytest.fixture
def persona(app: FastAPI, idp: FakeIdentityProvider) -> Persona:
    return make_persona(app, idp, "a")


@pytest.fixture
def other(app: FastAPI, idp: FakeIdentityProvider) -> Persona:
    return make_persona(app, idp, "b")


def events_of(owner: Session, contact_id: str) -> list[str]:
    return [
        item.event_type
        for item in rows(
            owner,
            "SELECT event_type FROM domain_events WHERE aggregate_type = 'contact' "
            "AND aggregate_id = :id ORDER BY recorded_at, id",
            id=contact_id,
        )
    ]


def test_create_stores_normalized_emails_with_a_manual_source(
    persona: Persona, owner_session: Session
) -> None:
    contact = create_contact(
        persona,
        "  Alex   Example ",
        ["  Alex.Example@Example.TEST ", "alex.example@example.test", "second@example.test"],
        headline="Recruiter",
        linkedin_url="https://example.test/in/alex",
    )

    assert contact["full_name"] == "Alex Example"
    assert [(item["address"], item["source"]) for item in contact["emails"]] == [
        ("alex.example@example.test", "manual"),
        ("second@example.test", "manual"),
    ]
    assert contact["source"] == "manual"
    assert events_of(owner_session, contact["id"]) == ["CONTACT_CREATED"]


@pytest.mark.parametrize(
    "payload",
    [
        {"full_name": "   "},
        {"full_name": "Alex Example", "emails": ["not-an-email"]},
        {"full_name": "Alex Example", "emails": ["a b@example.test"]},
        {"full_name": "Alex Example", "emails": ["alex@localhost"]},
        {"full_name": "Alex Example", "linkedin_url": "javascript:alert(1)"},
        {"full_name": "Alex Example", "unknown": 1},
        {"full_name": "A" * 201},
    ],
)
def test_invalid_contacts_are_rejected(persona: Persona, payload: dict[str, Any]) -> None:
    assert persona.request("POST", CONTACTS, json=payload).status_code == 422


def test_an_address_belongs_to_one_contact_per_user(persona: Persona, other: Persona) -> None:
    first = create_contact(persona, "Alex Example", ["alex@example.test"])

    clash = persona.request(
        "POST",
        CONTACTS,
        json={"full_name": "Another Alex", "emails": ["ALEX@example.test"]},
    )
    assert clash.status_code == 409
    assert error_code(clash) == "contact_email_taken"

    second = create_contact(persona, "Sam Example", ["sam@example.test"])
    taken = patch_contact(persona, second, emails=["alex@example.test"])
    assert taken.status_code == 409
    assert error_code(taken) == "contact_email_taken"
    assert get_contact(persona, second["id"])["emails"][0]["address"] == "sam@example.test"

    assert create_contact(other, "Alex Example", ["alex@example.test"])["id"] != first["id"]


def test_concurrent_creates_of_one_address_yield_one_contact(
    persona: Persona, owner_session: Session
) -> None:
    barrier = threading.Barrier(2)
    statuses: list[int] = []
    lock = threading.Lock()

    def attempt(name: str) -> None:
        barrier.wait()
        response = persona.request(
            "POST", CONTACTS, json={"full_name": name, "emails": ["race@example.test"]}
        )
        with lock:
            statuses.append(response.status_code)

    threads = [threading.Thread(target=attempt, args=(name,)) for name in ("A One", "B Two")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(statuses) == [201, 409]
    assert scalar(owner_session, "SELECT count(*) FROM contacts") == 1


def test_patch_adds_and_removes_addresses_and_keeps_each_source(
    persona: Persona, owner_session: Session
) -> None:
    contact = create_contact(persona, "Alex Example", ["keep@example.test", "drop@example.test"])
    owner_session.execute(
        text(
            "UPDATE contacts SET emails = jsonb_set(emails, '{items,0,source}', '\"gmail\"') "
            "WHERE id = :id"
        ),
        {"id": contact["id"]},
    )
    owner_session.commit()
    contact = get_contact(persona, contact["id"])

    updated = body_of(
        patch_contact(persona, contact, emails=["keep@example.test", "new@example.test"])
    )

    assert [(item["address"], item["source"]) for item in updated["emails"]] == [
        ("keep@example.test", "gmail"),
        ("new@example.test", "manual"),
    ]
    assert events_of(owner_session, contact["id"]) == ["CONTACT_CREATED", "CONTACT_EDITED"]


def test_patch_changes_fields_and_clears_optional_ones(persona: Persona) -> None:
    contact = create_contact(
        persona, headline="Recruiter", linkedin_url="https://example.test/in/a"
    )

    updated = body_of(
        patch_contact(persona, contact, headline=None, linkedin_url=None, notes="Met once")
    )

    assert updated["headline"] is None
    assert updated["linkedin_url"] is None
    assert updated["notes"] == "Met once"
    assert updated["full_name"] == "Alex Example"
    assert updated["updated_at"] != contact["updated_at"]


def test_an_unchanged_patch_writes_no_event(persona: Persona, owner_session: Session) -> None:
    contact = create_contact(persona, "Alex Example", ["alex@example.test"])

    body_of(patch_contact(persona, contact, full_name="Alex Example", emails=["alex@example.test"]))

    assert events_of(owner_session, contact["id"]) == ["CONTACT_CREATED"]


def test_a_stale_patch_is_a_conflict_and_changes_nothing(persona: Persona) -> None:
    contact = create_contact(persona)
    body_of(patch_contact(persona, contact, headline="First"))

    stale = patch_contact(persona, contact, headline="Second")

    assert stale.status_code == 409
    assert error_code(stale) == "conflict"
    assert get_contact(persona, contact["id"])["headline"] == "First"


def test_list_searches_names_and_addresses_and_filters_by_company(persona: Persona) -> None:
    alex = create_contact(persona, "Alex Example", ["alex.recruiter@example.test"])
    sam = create_contact(persona, "Sam 100%_Sample", ["sam@example.test"])
    company = create_company(persona)
    body_of(
        persona.request(
            "POST",
            f"{CONTACTS}/{alex['id']}/companies/{company['id']}",
            json={"relation": "recruiter"},
        )
    )

    def listed(**params: str) -> list[str]:
        return [
            item["id"] for item in body_of_list(persona.request("GET", CONTACTS, params=params))
        ]

    assert listed() == [sam["id"], alex["id"]]
    assert listed(q="alex") == [alex["id"]]
    assert listed(q="RECRUITER@") == [alex["id"]]
    assert listed(q="example.test") == [sam["id"], alex["id"]]
    assert listed(q="100%_") == [sam["id"]]
    assert listed(q="%") == [sam["id"]]
    assert listed(company_id=company["id"]) == [alex["id"]]
    assert listed(q="sam", company_id=company["id"]) == []
    opportunity = new_opportunity(persona, "contact filter")
    body_of(
        persona.request(
            "POST",
            f"{CONTACTS}/{sam['id']}/opportunities/{opportunity['id']}",
            json={"role": "referrer"},
        )
    )
    assert listed(opportunity_id=opportunity["id"]) == [sam["id"]]


def body_of_list(response: Any) -> list[dict[str, Any]]:
    assert response.status_code == 200, response.text
    body: list[dict[str, Any]] = response.json()
    return body


def test_company_links_are_created_updated_and_removed(
    persona: Persona, owner_session: Session
) -> None:
    contact = create_contact(persona)
    company = create_company(persona)
    path = f"{CONTACTS}/{contact['id']}/companies/{company['id']}"

    linked = body_of(persona.request("POST", path, json={"relation": "recruiter", "title": "Lead"}))
    assert linked["companies"] == [
        {
            "company_id": company["id"],
            "company_name": "Example Corp",
            "relation": "recruiter",
            "title": "Lead",
            "is_current": True,
        }
    ]

    again = body_of(
        persona.request("POST", path, json={"relation": "former_employee", "is_current": False})
    )
    assert [(link["relation"], link["is_current"]) for link in again["companies"]] == [
        ("former_employee", False)
    ]

    removed = body_of(persona.request("DELETE", path))
    assert removed["companies"] == []
    assert persona.request("DELETE", path).status_code == 404
    assert events_of(owner_session, contact["id"]) == [
        "CONTACT_CREATED",
        "CONTACT_LINKED",
        "CONTACT_LINKED",
        "CONTACT_UNLINKED",
    ]


def test_opportunity_links_are_unique_per_role(persona: Persona) -> None:
    contact = create_contact(persona)
    opportunity = new_opportunity(persona, "contact links")
    path = f"{CONTACTS}/{contact['id']}/opportunities/{opportunity['id']}"

    body_of(persona.request("POST", path, json={"role": "recruiter"}))
    body_of(persona.request("POST", path, json={"role": "recruiter"}))
    both = body_of(persona.request("POST", path, json={"role": "referrer"}))

    assert sorted(link["role"] for link in both["opportunities"]) == ["recruiter", "referrer"]
    assert persona.request("POST", path, json={"role": "mentor"}).status_code == 422
    assert persona.request("DELETE", path).status_code == 422

    left = body_of(persona.request("DELETE", path, params={"role": "recruiter"}))
    assert [link["role"] for link in left["opportunities"]] == ["referrer"]
    assert persona.request("DELETE", path, params={"role": "recruiter"}).status_code == 404


def test_links_to_a_foreign_target_are_not_found(persona: Persona, other: Persona) -> None:
    contact = create_contact(persona)
    foreign_company = create_company(other, "Other Corp")
    foreign_opportunity = new_opportunity(other, "foreign link")

    company_link = persona.request(
        "POST", f"{CONTACTS}/{contact['id']}/companies/{foreign_company['id']}", json={}
    )
    opportunity_link = persona.request(
        "POST",
        f"{CONTACTS}/{contact['id']}/opportunities/{foreign_opportunity['id']}",
        json={"role": "other"},
    )

    assert (company_link.status_code, opportunity_link.status_code) == (404, 404)
    detail = get_contact(persona, contact["id"])
    assert detail["companies"] == []
    assert detail["opportunities"] == []


def test_detail_shows_links_interactions_and_open_actions(persona: Persona) -> None:
    contact = create_contact(persona)
    interaction = body_of(create_interaction(persona, contact["id"], summary="Intro call"), 201)
    open_action = body_of(create_action(persona, contact_id=contact["id"]), 201)
    done = body_of(create_action(persona, contact_id=contact["id"], title="Done one"), 201)
    body_of(action_command(persona, done, "complete"))

    detail = get_contact(persona, contact["id"])

    assert [item["id"] for item in detail["interactions"]] == [interaction["id"]]
    assert [item["id"] for item in detail["actions"]] == [open_action["id"]]


def merge_fixture(persona: Persona) -> dict[str, Any]:
    survivor = create_contact(persona, "Alex Example", ["alex@example.test"])
    merged = create_contact(persona, "Alexander Example", ["alex2@example.test"])
    shared = create_company(persona, "Shared Corp")
    only_merged = create_company(persona, "Merged Only Corp")
    opportunity = new_opportunity(persona, "merge links")
    for contact_id, relation in ((survivor["id"], "recruiter"), (merged["id"], "employee")):
        body_of(
            persona.request(
                "POST",
                f"{CONTACTS}/{contact_id}/companies/{shared['id']}",
                json={"relation": relation},
            )
        )
    body_of(
        persona.request("POST", f"{CONTACTS}/{merged['id']}/companies/{only_merged['id']}", json={})
    )
    for contact_id in (survivor["id"], merged["id"]):
        body_of(
            persona.request(
                "POST",
                f"{CONTACTS}/{contact_id}/opportunities/{opportunity['id']}",
                json={"role": "recruiter"},
            )
        )
    body_of(
        persona.request(
            "POST",
            f"{CONTACTS}/{merged['id']}/opportunities/{opportunity['id']}",
            json={"role": "referrer"},
        )
    )
    return {
        "survivor": get_contact(persona, survivor["id"]),
        "merged": get_contact(persona, merged["id"]),
        "shared": shared,
        "only_merged": only_merged,
        "opportunity": opportunity,
    }


def test_merge_moves_everything_to_the_survivor(persona: Persona, owner_session: Session) -> None:
    fixture = merge_fixture(persona)
    survivor, merged = fixture["survivor"], fixture["merged"]
    interaction = body_of(create_interaction(persona, merged["id"], summary="From merged"), 201)
    action = body_of(create_action(persona, contact_id=merged["id"]), 201)
    own = body_of(create_interaction(persona, survivor["id"], summary="From survivor"), 201)

    result = body_of(
        merge(persona, get_contact(persona, survivor["id"]), get_contact(persona, merged["id"]))
    )

    assert result["id"] == survivor["id"]
    assert [(item["address"], item["source"]) for item in result["emails"]] == [
        ("alex@example.test", "manual"),
        ("alex2@example.test", "manual"),
    ]
    assert sorted(link["company_name"] for link in result["companies"]) == [
        "Merged Only Corp",
        "Shared Corp",
    ]
    shared_link = next(
        link for link in result["companies"] if link["company_name"] == "Shared Corp"
    )
    assert shared_link["relation"] == "recruiter"
    assert sorted(link["role"] for link in result["opportunities"]) == ["recruiter", "referrer"]
    assert {item["id"] for item in result["interactions"]} == {interaction["id"], own["id"]}
    assert [item["id"] for item in result["actions"]] == [action["id"]]
    assert persona.request("GET", f"{CONTACTS}/{merged['id']}").status_code == 404
    assert merged["id"] not in [
        item["id"] for item in body_of_list(persona.request("GET", CONTACTS))
    ]
    assert scalar(owner_session, "SELECT count(*) FROM contacts") == 1
    assert events_of(owner_session, survivor["id"])[-1] == "CONTACT_MERGED"
    stored = rows(
        owner_session,
        "SELECT payload FROM domain_events WHERE event_type = 'CONTACT_MERGED'",
    )
    assert stored[0].payload["merged_id"] == merged["id"]
    assert stored[0].payload["moved_interactions"] == 1
    assert stored[0].payload["moved_actions"] == 1


def test_merge_keeps_the_survivors_source_on_a_shared_address(
    persona: Persona, owner_session: Session
) -> None:
    survivor = create_contact(persona, "Alex Example", ["shared@example.test"])
    merged = create_contact(persona, "Alexander Example", ["other@example.test"])
    owner_session.execute(
        text(
            "UPDATE contacts SET emails = jsonb_set(emails, '{items,0,source}', '\"gmail\"') "
            "WHERE id = :id"
        ),
        {"id": merged["id"]},
    )
    owner_session.execute(
        text(
            "UPDATE contacts SET emails = jsonb_set(emails, '{items,0,address}', "
            "'\"shared@example.test\"') WHERE id = :id"
        ),
        {"id": merged["id"]},
    )
    owner_session.commit()

    result = body_of(
        merge(persona, get_contact(persona, survivor["id"]), get_contact(persona, merged["id"]))
    )

    assert [(item["address"], item["source"]) for item in result["emails"]] == [
        ("shared@example.test", "manual")
    ]


def test_merge_refuses_itself_stale_versions_and_merged_contacts(persona: Persona) -> None:
    first = create_contact(persona, "First Example")
    second = create_contact(persona, "Second Example")
    third = create_contact(persona, "Third Example")

    into_itself = merge(persona, first, first)
    assert (into_itself.status_code, error_code(into_itself)) == (409, "cannot_merge_into_self")

    body_of(patch_contact(persona, second, headline="changed"))
    stale = merge(persona, first, second)
    assert (stale.status_code, error_code(stale)) == (409, "conflict")
    assert get_contact(persona, second["id"])["headline"] == "changed"

    current_first, current_second = (get_contact(persona, item["id"]) for item in (first, second))
    body_of(merge(persona, current_first, current_second))
    again = merge(persona, get_contact(persona, third["id"]), current_second)
    assert (again.status_code, error_code(again)) == (409, "contact_already_merged")
    as_survivor = merge(persona, current_second, get_contact(persona, third["id"]))
    assert (as_survivor.status_code, error_code(as_survivor)) == (409, "contact_already_merged")
    assert (
        merge(
            persona, third, {"id": str(uuid.uuid4()), "updated_at": third["updated_at"]}
        ).status_code
        == 404
    )


def test_merge_with_a_foreign_contact_is_not_found(persona: Persona, other: Persona) -> None:
    mine = create_contact(persona, "Alex Example")
    theirs = create_contact(other, "Sam Example")

    assert merge(persona, mine, theirs).status_code == 404
    assert merge(other, theirs, mine).status_code == 404
    assert get_contact(other, theirs["id"])["full_name"] == "Sam Example"


@pytest.mark.parametrize("repeat", range(10))
def test_a_merge_racing_an_edit_of_the_merged_contact_yields_one_conflict(
    persona: Persona, owner_session: Session, repeat: int
) -> None:
    survivor = create_contact(persona, "Alex Example", [f"survivor{repeat}@example.test"])
    merged = create_contact(persona, "Alexander Example", [f"merged{repeat}@example.test"])
    barrier = threading.Barrier(2)
    results: dict[str, int] = {}
    lock = threading.Lock()

    def do_merge() -> None:
        barrier.wait()
        response = merge(persona, survivor, merged)
        with lock:
            results["merge"] = response.status_code

    def do_edit() -> None:
        barrier.wait()
        response = patch_contact(persona, merged, headline="edited while merging")
        with lock:
            results["edit"] = response.status_code

    threads = [threading.Thread(target=do_merge), threading.Thread(target=do_edit)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results.values()) == [200, 409], results
    remaining = scalar(owner_session, "SELECT count(*) FROM contacts")
    assert remaining == (1 if results["merge"] == 200 else 2)
