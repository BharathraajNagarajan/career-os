import time
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.auth.fake_idp import FakeIdentityProvider
from tests.db.auth_helpers import Persona, make_persona
from tests.db.contact_helpers import body_of, error_code
from tests.db.evidence_helpers import (
    CLAIMS,
    SKILLS,
    create_claim,
    create_claim_response,
    create_skill,
    events_of,
    get_claim,
    get_skill,
    mark_gap,
    merge_skills,
    professional,
    reclassify,
    skill_updated_at,
    upload_resume,
)

pytestmark = pytest.mark.db


@pytest.fixture
def persona(app: FastAPI, idp: FakeIdentityProvider) -> Persona:
    return make_persona(app, idp, "a")


@pytest.fixture
def other(app: FastAPI, idp: FakeIdentityProvider) -> Persona:
    return make_persona(app, idp, "b")


def test_adding_a_skill_records_the_event_and_starts_as_not_recorded(
    persona: Persona, owner_session: Session
) -> None:
    skill = create_skill(persona, "  Widget   Design ", aliases=["widget-design", "Widgets"])

    assert skill["canonical_name"] == "Widget Design"
    assert skill["aliases"] == ["Widgets"]
    assert skill["confirmation_status"] == "confirmed"
    assert skill["origin"] == "user"
    assert skill["headline"] == {"category": "not_recorded", "engagement_type": None}
    assert skill["categories"] == ["not_recorded"]
    assert skill["user_marked_gap"] is False
    assert events_of(owner_session, "skill", skill["id"]) == ["SKILL_ADDED"]


def test_names_and_aliases_are_unique_per_user(persona: Persona, other: Persona) -> None:
    create_skill(persona, "Widgets", aliases=["Widget craft"])

    for name, aliases in [
        ("widgets", []),
        ("Gadgets", ["WIDGET-craft"]),
        ("Widget Craft", []),
    ]:
        response = persona.request(
            "POST", SKILLS, json={"canonical_name": name, "aliases": aliases}
        )
        assert response.status_code == 409
        assert error_code(response) == "skill_exists"
    assert create_skill(other, "Widgets")["canonical_name"] == "Widgets"
    assert persona.request("POST", SKILLS, json={"canonical_name": " - "}).status_code == 422


def test_not_recorded_is_never_a_gap(persona: Persona) -> None:
    create_skill(persona, "Gadgets")

    (listed,) = persona.request("GET", SKILLS).json()
    assert listed["categories"] == ["not_recorded"]
    assert listed["user_marked_gap"] is False
    assert persona.request("GET", SKILLS, params={"category": "gap"}).json() == []
    not_recorded = persona.request("GET", SKILLS, params={"category": "not_recorded"}).json()
    assert [item["id"] for item in not_recorded] == [listed["id"]]


def test_only_the_user_marks_a_gap_and_it_shows_as_the_headline(
    persona: Persona, owner_session: Session
) -> None:
    skill = create_skill(persona, "Gadgets")

    marked = body_of(mark_gap(persona, skill, "Never used"))

    assert marked["user_marked_gap"] is True
    assert marked["gap_note"] == "Never used"
    assert marked["headline"]["category"] == "gap"
    assert marked["categories"] == ["gap"]
    assert events_of(owner_session, "skill", skill["id"]) == ["SKILL_ADDED", "SKILL_GAP_MARKED"]
    again = mark_gap(persona, marked)
    assert (again.status_code, error_code(again)) == (409, "invalid_state")
    cleared = body_of(
        persona.request(
            "POST",
            f"{SKILLS}/{skill['id']}/clear-gap",
            json={"expected_state_version": marked["state_version"]},
        )
    )
    assert cleared["categories"] == ["not_recorded"]
    assert cleared["gap_note"] is None
    assert events_of(owner_session, "skill", skill["id"])[-1] == "SKILL_GAP_CLEARED"


@pytest.mark.parametrize(
    ("evidence_class", "engagement"),
    [("professional", "internship"), ("academic_research", None), ("project", None)],
)
def test_gap_marking_is_refused_while_confirmed_evidence_exists(
    persona: Persona, evidence_class: str, engagement: str | None
) -> None:
    skill = create_skill(persona, "Gadgets")
    claim = create_claim(
        persona,
        skill["id"],
        evidence_class=evidence_class,
        **({} if engagement is None else {"engagement_type": engagement}),
    )

    refused = mark_gap(persona, get_skill(persona, skill["id"]))

    assert (refused.status_code, error_code(refused)) == (409, "gap_refused_evidence_exists")
    assert get_skill(persona, skill["id"])["user_marked_gap"] is False
    rejected = persona.request(
        "POST",
        f"{CLAIMS}/{claim['id']}/reject",
        json={"expected_state_version": claim["state_version"]},
    )
    assert rejected.status_code == 200
    assert mark_gap(persona, get_skill(persona, skill["id"])).status_code == 200


def test_learning_evidence_may_coexist_with_a_gap(persona: Persona) -> None:
    skill = create_skill(persona, "Gadgets")
    create_claim(persona, skill["id"], evidence_class="learning")

    response = mark_gap(persona, get_skill(persona, skill["id"]))

    marked = body_of(response)
    assert marked["categories"] == ["learning", "gap"]
    assert marked["headline"]["category"] == "gap"


def test_downgrading_the_evidence_first_allows_the_gap(persona: Persona) -> None:
    skill = create_skill(persona, "Gadgets")
    claim = create_claim(persona, skill["id"], evidence_class="project")
    assert mark_gap(persona, get_skill(persona, skill["id"])).status_code == 409

    assert reclassify(persona, claim, "learning").status_code == 200

    assert mark_gap(persona, get_skill(persona, skill["id"])).status_code == 200


def test_evidence_cannot_be_added_to_a_gap_marked_skill_except_learning(
    persona: Persona,
) -> None:
    skill = create_skill(persona, "Gadgets")
    assert mark_gap(persona, skill).status_code == 200

    refused = create_claim_response(persona, evidence_class="project", skill_ids=[skill["id"]])

    assert (refused.status_code, error_code(refused)) == (409, "gap_marked")
    assert (
        create_claim_response(
            persona, evidence_class="learning", skill_ids=[skill["id"]]
        ).status_code
        == 201
    )
    loose = create_claim(persona, evidence_class="project")
    link = persona.request("POST", f"{CLAIMS}/{loose['id']}/skills", json={"skill_id": skill["id"]})
    assert (link.status_code, error_code(link)) == (409, "gap_marked")


def test_badges_are_derived_from_claims_and_several_show_at_once(persona: Persona) -> None:
    skill = create_skill(persona, "Widgets")
    professional(
        persona, skill["id"], engagement="full_time", start_date="2020-01-01", end_date="2022-06-30"
    )
    create_claim(persona, skill["id"], evidence_class="academic_research")
    create_claim(persona, skill["id"], evidence_class="project", start_date="2023-01-01")

    detail = get_skill(persona, skill["id"])

    assert [(b["evidence_class"], b["engagement_type"]) for b in detail["badges"]] == [
        ("professional", "full_time"),
        ("academic_research", None),
        ("project", None),
    ]
    assert all(badge["confirmed"] for badge in detail["badges"])
    assert detail["categories"] == ["professional", "academic_research", "project"]
    assert detail["headline"] == {"category": "professional", "engagement_type": "full_time"}
    assert detail["latest_end_date"] == "2022-06-30"
    assert detail["is_current"] is True
    assert "evidence_class" not in detail
    assert len(detail["claims"]) == 3


def test_internship_is_distinct_from_full_time(persona: Persona) -> None:
    interned = create_skill(persona, "Widgets")
    employed = create_skill(persona, "Gadgets")
    professional(persona, interned["id"], engagement="internship")
    professional(persona, employed["id"], engagement="full_time")

    interned_detail = get_skill(persona, interned["id"])

    assert interned_detail["headline"] == {
        "category": "professional",
        "engagement_type": "internship",
    }
    only_full_time = persona.request(
        "GET", SKILLS, params={"category": "professional", "engagement": "full_time"}
    ).json()
    only_internship = persona.request(
        "GET", SKILLS, params={"category": "professional", "engagement": "internship"}
    ).json()
    assert [item["id"] for item in only_full_time] == [employed["id"]]
    assert [item["id"] for item in only_internship] == [interned["id"]]


def test_unspecified_professional_evidence_is_not_presented_as_counted(persona: Persona) -> None:
    skill = create_skill(persona, "Widgets")
    professional(persona, skill["id"], engagement="unspecified")
    create_claim(persona, skill["id"], evidence_class="academic_research")

    detail = get_skill(persona, skill["id"])

    assert detail["headline"] == {"category": "professional", "engagement_type": "unspecified"}
    assert [(b["evidence_class"], b["engagement_type"]) for b in detail["badges"]] == [
        ("professional", "unspecified"),
        ("academic_research", None),
    ]


def test_claims_need_a_source_and_a_valid_class_and_engagement_pair(persona: Persona) -> None:
    base = {"statement": "Built things", "evidence_class": "project"}

    no_sources = persona.request("POST", CLAIMS, json={**base, "sources": []})
    blank = persona.request(
        "POST",
        CLAIMS,
        json={**base, "sources": [{"source_type": "user_assertion", "assertion_text": "  "}]},
    )
    bad_url = persona.request(
        "POST",
        CLAIMS,
        json={**base, "sources": [{"source_type": "project_url", "url": "javascript:alert(1)"}]},
    )
    missing_type = create_claim_response(persona, evidence_class="professional")
    stray_type = create_claim_response(persona, engagement_type="full_time")
    unknown = create_claim_response(persona, evidence_class="employment")

    assert no_sources.status_code == 422
    assert (blank.status_code, error_code(blank)) == (422, "invalid_source")
    assert (bad_url.status_code, error_code(bad_url)) == (422, "invalid_source")
    assert (missing_type.status_code, error_code(missing_type)) == (422, "engagement_type_required")
    assert (stray_type.status_code, error_code(stray_type)) == (
        422,
        "engagement_type_only_professional",
    )
    assert unknown.status_code == 422
    assert persona.request("GET", CLAIMS).json() == []


def test_a_project_url_source_and_the_users_own_words_are_stored(persona: Persona) -> None:
    claim = create_claim(
        persona,
        sources=[
            {"source_type": "project_url", "url": "https://example.test/projects/widgets"},
            {"source_type": "user_assertion", "assertion_text": "  I built it myself  "},
        ],
    )

    assert [(s["source_type"], s["url"], s["assertion_text"]) for s in claim["sources"]] == [
        ("project_url", "https://example.test/projects/widgets", None),
        ("user_assertion", None, "I built it myself"),
    ]


def test_classification_change_needs_explicit_confirmation_and_records_old_and_new(
    persona: Persona, owner_session: Session
) -> None:
    skill = create_skill(persona, "Widgets")
    claim = professional(persona, skill["id"], engagement="unspecified")

    unconfirmed = reclassify(persona, claim, "professional", "full_time", confirm=False)

    assert (unconfirmed.status_code, error_code(unconfirmed)) == (422, "confirmation_required")
    assert get_claim(persona, claim["id"])["engagement_type"] == "unspecified"
    changed = body_of(reclassify(persona, claim, "professional", "internship"))
    assert (changed["evidence_class"], changed["engagement_type"]) == ("professional", "internship")
    assert changed["state_version"] == claim["state_version"] + 1
    events = events_of(owner_session, "claim", claim["id"])
    assert events == ["CLAIM_CONFIRMED", "EVIDENCE_CLASS_CHANGED"]
    payload: dict[str, Any] = owner_session.execute(
        text("SELECT payload FROM domain_events WHERE event_type = 'EVIDENCE_CLASS_CHANGED'")
    ).scalar_one()
    assert payload == {
        "schema_version": 1,
        "claim_id": claim["id"],
        "old_evidence_class": "professional",
        "new_evidence_class": "professional",
        "old_engagement_type": "unspecified",
        "new_engagement_type": "internship",
        "review_item_id": None,
    }


def test_classification_change_validates_the_pair_and_the_version(persona: Persona) -> None:
    claim = create_claim(persona, evidence_class="project")

    no_type = reclassify(persona, claim, "professional")
    stray = reclassify(persona, claim, "learning", "internship")
    same = reclassify(persona, claim, "project")
    unknown = reclassify(persona, claim, "employment")
    stale = reclassify(persona, {**claim, "state_version": 9}, "learning")

    assert (no_type.status_code, error_code(no_type)) == (422, "engagement_type_required")
    assert (stray.status_code, error_code(stray)) == (422, "engagement_type_only_professional")
    assert (same.status_code, error_code(same)) == (422, "unchanged")
    assert unknown.status_code == 422
    assert (stale.status_code, error_code(stale)) == (409, "conflict")
    downgraded = body_of(reclassify(persona, claim, "learning"))
    assert (downgraded["evidence_class"], downgraded["engagement_type"]) == ("learning", None)


def test_changing_to_professional_on_a_gap_marked_skill_is_refused(persona: Persona) -> None:
    skill = create_skill(persona, "Gadgets")
    claim = create_claim(persona, skill["id"], evidence_class="learning")
    assert mark_gap(persona, get_skill(persona, skill["id"])).status_code == 200

    refused = reclassify(persona, claim, "professional", "full_time")

    assert (refused.status_code, error_code(refused)) == (409, "gap_marked")
    assert get_claim(persona, claim["id"])["evidence_class"] == "learning"


def test_claim_edits_are_events_and_reject_removes_it_from_the_badges(
    persona: Persona, owner_session: Session
) -> None:
    skill = create_skill(persona, "Widgets")
    claim = create_claim(persona, skill["id"], evidence_class="project", start_date="2021-01-01")

    edited = body_of(
        persona.request(
            "PATCH",
            f"{CLAIMS}/{claim['id']}",
            json={
                "expected_state_version": claim["state_version"],
                "statement": "Built widgets",
                "end_date": "2021-12-31",
                "organization_label": "Example Corp",
            },
        )
    )
    backwards = persona.request(
        "PATCH",
        f"{CLAIMS}/{claim['id']}",
        json={"expected_state_version": edited["state_version"], "end_date": "2020-01-01"},
    )
    rejected = body_of(
        persona.request(
            "POST",
            f"{CLAIMS}/{claim['id']}/reject",
            json={"expected_state_version": edited["state_version"]},
        )
    )

    assert (edited["statement"], edited["organization_label"]) == ("Built widgets", "Example Corp")
    assert (backwards.status_code, error_code(backwards)) == (422, "dates_out_of_order")
    assert rejected["confirmation_status"] == "rejected"
    assert events_of(owner_session, "claim", claim["id"]) == [
        "CLAIM_CONFIRMED",
        "CLAIM_EDITED",
        "CLAIM_REJECTED",
    ]
    detail = get_skill(persona, skill["id"])
    assert detail["badges"] == []
    assert detail["categories"] == ["not_recorded"]
    stale = persona.request(
        "PATCH",
        f"{CLAIMS}/{claim['id']}",
        json={"expected_state_version": claim["state_version"], "statement": "Late edit"},
    )
    assert (stale.status_code, error_code(stale)) == (409, "conflict")


def test_every_claim_and_skill_change_bumps_the_skills_updated_at(
    persona: Persona, owner_session: Session
) -> None:
    skill = create_skill(persona, "Widgets")
    spare = create_skill(persona, "Gadgets")
    stamps = [skill_updated_at(owner_session, skill["id"])]

    def moved() -> bool:
        stamp = skill_updated_at(owner_session, skill["id"])
        changed = stamp > stamps[-1]
        stamps.append(stamp)
        return bool(changed)

    time.sleep(0.01)
    claim = create_claim(persona, skill["id"], evidence_class="project")
    assert moved()
    claim = body_of(
        persona.request(
            "PATCH",
            f"{CLAIMS}/{claim['id']}",
            json={"expected_state_version": claim["state_version"], "statement": "Edited"},
        )
    )
    assert moved()
    claim = body_of(reclassify(persona, claim, "learning"))
    assert moved()
    assert (
        persona.request(
            "POST",
            f"{CLAIMS}/{claim['id']}/sources",
            json={"source_type": "project_url", "url": "https://example.test/p"},
        ).status_code
        == 200
    )
    assert moved()
    assert (
        persona.request(
            "POST", f"{CLAIMS}/{claim['id']}/skills", json={"skill_id": spare["id"]}
        ).status_code
        == 200
    )
    assert not moved()
    assert (
        persona.request("DELETE", f"{CLAIMS}/{claim['id']}/skills/{skill['id']}").status_code == 200
    )
    assert moved()
    assert (
        persona.request(
            "POST", f"{CLAIMS}/{claim['id']}/skills", json={"skill_id": skill["id"]}
        ).status_code
        == 200
    )
    assert moved()
    patched = body_of(
        persona.request(
            "PATCH",
            f"{SKILLS}/{skill['id']}",
            json={"expected_state_version": skill["state_version"], "user_note": "A note"},
        )
    )
    assert moved()
    assert mark_gap(persona, patched).status_code == 200
    assert moved()


def test_skill_edits_check_collisions_and_versions(persona: Persona) -> None:
    widgets = create_skill(persona, "Widgets")
    gadgets = create_skill(persona, "Gadgets", aliases=["Gizmos"])

    renamed = body_of(
        persona.request(
            "PATCH",
            f"{SKILLS}/{widgets['id']}",
            json={
                "expected_state_version": widgets["state_version"],
                "canonical_name": "Widget Engineering",
                "aliases": ["Widgets", "widgets"],
                "user_note": "Core skill",
            },
        )
    )
    collision = persona.request(
        "PATCH",
        f"{SKILLS}/{gadgets['id']}",
        json={
            "expected_state_version": gadgets["state_version"],
            "aliases": ["widget engineering"],
        },
    )
    stale = persona.request(
        "PATCH",
        f"{SKILLS}/{widgets['id']}",
        json={"expected_state_version": widgets["state_version"], "user_note": "Late"},
    )
    nulled = persona.request(
        "PATCH",
        f"{SKILLS}/{widgets['id']}",
        json={"expected_state_version": renamed["state_version"], "canonical_name": None},
    )

    assert (renamed["canonical_name"], renamed["aliases"], renamed["user_note"]) == (
        "Widget Engineering",
        ["Widgets"],
        "Core skill",
    )
    assert renamed["state_version"] == widgets["state_version"] + 1
    assert (collision.status_code, error_code(collision)) == (409, "skill_exists")
    assert (stale.status_code, error_code(stale)) == (409, "conflict")
    assert nulled.status_code == 422


def test_merge_moves_links_redirects_the_merged_skill_and_keeps_its_names(
    persona: Persona, owner_session: Session
) -> None:
    survivor = create_skill(persona, "Widgets")
    duplicate = create_skill(persona, "Widget Craft", aliases=["Widgeting"])
    both = create_claim(persona, survivor["id"], duplicate["id"], evidence_class="project")
    only_duplicate = create_claim(persona, duplicate["id"], evidence_class="learning")
    survivor = get_skill(persona, survivor["id"])
    duplicate = get_skill(persona, duplicate["id"])

    merged = body_of(merge_skills(persona, survivor, duplicate))

    assert {claim["id"] for claim in merged["claims"]} == {both["id"], only_duplicate["id"]}
    assert merged["aliases"] == ["Widget Craft", "Widgeting"]
    assert [ref["id"] for ref in get_claim(persona, both["id"])["skills"]] == [survivor["id"]]
    redirected = get_skill(persona, duplicate["id"])
    assert redirected["merged_into_skill_id"] == survivor["id"]
    assert redirected["claims"] == []
    assert events_of(owner_session, "skill", survivor["id"])[-1] == "SKILL_MERGED"
    listed = persona.request("GET", SKILLS).json()
    assert [item["id"] for item in listed] == [survivor["id"]]
    everything = persona.request("GET", SKILLS, params={"include_merged": True}).json()
    assert {item["id"] for item in everything} == {survivor["id"], duplicate["id"]}
    reused = create_claim_response(persona, evidence_class="project", skill_ids=[duplicate["id"]])
    assert [ref["id"] for ref in body_of(reused, 201)["skills"]] == [survivor["id"]]
    again = persona.request("POST", SKILLS, json={"canonical_name": "widgeting"})
    assert (again.status_code, error_code(again)) == (409, "skill_exists")


def test_merge_guards(persona: Persona) -> None:
    first = create_skill(persona, "Widgets")
    second = create_skill(persona, "Gadgets")
    third = create_skill(persona, "Gizmos")

    same = merge_skills(persona, first, first)
    stale = merge_skills(persona, first, {**second, "state_version": 7})
    assert merge_skills(persona, first, second).status_code == 200
    again = merge_skills(persona, get_skill(persona, third["id"]), second)
    onto_merged = merge_skills(persona, second, get_skill(persona, third["id"]))

    assert (same.status_code, error_code(same)) == (422, "merge_same_skill")
    assert (stale.status_code, error_code(stale)) == (409, "conflict")
    assert (again.status_code, error_code(again)) == (409, "conflict")
    assert (onto_merged.status_code, error_code(onto_merged)) == (409, "conflict")


def test_merging_evidence_into_a_gap_marked_survivor_clears_the_gap(
    persona: Persona, owner_session: Session
) -> None:
    survivor = create_skill(persona, "Widgets")
    duplicate = create_skill(persona, "Widget Craft")
    create_claim(persona, duplicate["id"], evidence_class="project")
    survivor = body_of(mark_gap(persona, survivor))

    merged = body_of(merge_skills(persona, survivor, get_skill(persona, duplicate["id"])))

    assert merged["user_marked_gap"] is False
    assert merged["categories"] == ["project"]
    assert events_of(owner_session, "skill", survivor["id"])[-2:] == [
        "SKILL_MERGED",
        "SKILL_GAP_CLEARED",
    ]


def test_merging_a_gap_marked_skill_clears_its_marker(persona: Persona) -> None:
    survivor = create_skill(persona, "Widgets")
    duplicate = body_of(mark_gap(persona, create_skill(persona, "Widget Craft")))

    merged = body_of(merge_skills(persona, survivor, duplicate))

    assert merged["user_marked_gap"] is False
    assert get_skill(persona, duplicate["id"])["user_marked_gap"] is False


def test_search_and_category_filters(persona: Persona) -> None:
    widgets = create_skill(persona, "Widgets", aliases=["Sprockets"])
    create_skill(persona, "Gadgets")
    create_claim(persona, widgets["id"], evidence_class="learning")

    by_name = persona.request("GET", SKILLS, params={"q": "widg"}).json()
    by_alias = persona.request("GET", SKILLS, params={"q": "SPROCK"}).json()
    learning = persona.request("GET", SKILLS, params={"category": "learning"}).json()
    project = persona.request("GET", SKILLS, params={"category": "project"}).json()
    bad = persona.request("GET", SKILLS, params={"category": "expert"})

    assert [item["id"] for item in by_name] == [widgets["id"]]
    assert [item["id"] for item in by_alias] == [widgets["id"]]
    assert [item["id"] for item in learning] == [widgets["id"]]
    assert project == []
    assert bad.status_code == 422


def test_resume_exposure_reports_stated_and_mentioned_resumes(
    persona: Persona, owner_session: Session
) -> None:
    skill = create_skill(persona, "Widgets", aliases=["Sprocket design"])
    stated = upload_resume(persona, owner_session, tag="stated", text_body="Nothing relevant here")
    mentioned = upload_resume(
        persona, owner_session, tag="mentioned", text_body="Led sprocket design and testing"
    )
    unrelated = upload_resume(persona, owner_session, tag="unrelated", text_body="Gardening only")
    create_claim(
        persona,
        skill["id"],
        evidence_class="project",
        sources=[{"source_type": "resume", "resume_id": stated["id"]}],
    )

    detail = get_skill(persona, skill["id"])

    exposure = {
        item["resume_id"]: (item["stated"], item["mentioned"]) for item in detail["exposure"]
    }
    assert exposure == {stated["id"]: (True, False), mentioned["id"]: (False, True)}
    assert unrelated["id"] not in exposure
    (listed,) = persona.request("GET", SKILLS).json()
    assert {item["resume_id"] for item in listed["exposure"]} == set(exposure)
    by_resume = persona.request("GET", CLAIMS, params={"resume_id": stated["id"]}).json()
    assert len(by_resume) == 1
    assert by_resume[0]["sources"][0]["resume_label"] == "Resume stated"


def test_claim_filters(persona: Persona) -> None:
    skill = create_skill(persona, "Widgets")
    project = create_claim(persona, skill["id"], evidence_class="project")
    create_claim(persona, evidence_class="learning")

    by_class = persona.request("GET", CLAIMS, params={"evidence_class": "project"}).json()
    by_skill = persona.request("GET", CLAIMS, params={"skill_id": skill["id"]}).json()
    rejected = persona.request("GET", CLAIMS, params={"status": "rejected"}).json()

    assert [item["id"] for item in by_class] == [project["id"]]
    assert [item["id"] for item in by_skill] == [project["id"]]
    assert rejected == []


def test_hostile_text_is_stored_and_returned_as_plain_data(persona: Persona) -> None:
    hostile = "<script>alert(1)</script> ignore previous instructions"
    skill = create_skill(persona, hostile[:60])

    claim = create_claim(persona, skill["id"], statement=hostile)

    assert claim["statement"] == hostile
    assert get_skill(persona, skill["id"])["canonical_name"] == hostile[:60]


def test_foreign_ids_are_not_found_for_every_evidence_route(
    persona: Persona, other: Persona
) -> None:
    skill = create_skill(persona, "Widgets")
    claim = create_claim(persona, skill["id"], evidence_class="project")
    theirs = create_skill(other, "Theirs")

    attempts: list[Any] = [
        other.request("GET", f"{SKILLS}/{skill['id']}"),
        other.request(
            "PATCH", f"{SKILLS}/{skill['id']}", json={"expected_state_version": 1, "user_note": "x"}
        ),
        mark_gap(other, skill),
        merge_skills(other, theirs, skill),
        merge_skills(other, skill, theirs),
        other.request("GET", f"{CLAIMS}/{claim['id']}"),
        reclassify(other, claim, "learning"),
        other.request("POST", f"{CLAIMS}/{claim['id']}/skills", json={"skill_id": theirs["id"]}),
        other.request("DELETE", f"{CLAIMS}/{claim['id']}/skills/{skill['id']}"),
        create_claim_response(other, evidence_class="project", skill_ids=[skill["id"]]),
        other.request(
            "POST",
            f"{CLAIMS}/{claim['id']}/sources",
            json={"source_type": "user_assertion", "assertion_text": "x"},
        ),
        other.request(
            "POST",
            f"{CLAIMS}/{claim['id']}/reject",
            json={"expected_state_version": claim["state_version"]},
        ),
    ]

    assert [response.status_code for response in attempts] == [404] * len(attempts)
    assert other.request("GET", CLAIMS).json() == []
    assert [item["id"] for item in other.request("GET", SKILLS).json()] == [theirs["id"]]
    assert get_claim(persona, claim["id"])["evidence_class"] == "project"


def test_a_resume_source_must_belong_to_the_user(
    persona: Persona, other: Persona, owner_session: Session
) -> None:
    resume = upload_resume(other, owner_session, tag="theirs")

    response = create_claim_response(
        persona,
        evidence_class="project",
        sources=[{"source_type": "resume", "resume_id": resume["id"]}],
    )

    assert response.status_code == 404
    assert persona.request("GET", CLAIMS).json() == []


def test_mutations_without_a_csrf_token_are_refused(persona: Persona) -> None:
    skill = create_skill(persona, "Widgets")

    created = persona.client.post(SKILLS, json={"canonical_name": "Gadgets"})
    gap = persona.client.post(
        f"{SKILLS}/{skill['id']}/mark-gap", json={"expected_state_version": 1}
    )

    assert created.status_code == gap.status_code == 403


def test_learning_evidence_added_to_a_gap_marked_skill_does_not_clear_the_gap(
    persona: Persona, owner_session: Session
) -> None:
    skill = create_skill(persona, "Gadgets")
    marked = body_of(mark_gap(persona, skill, "Never used"))

    create_claim(persona, skill["id"], evidence_class="learning")

    detail = get_skill(persona, skill["id"])
    assert detail["user_marked_gap"] is True
    assert detail["gap_note"] == "Never used"
    assert detail["categories"] == ["learning", "gap"]
    assert events_of(owner_session, "skill", skill["id"]) == ["SKILL_ADDED", "SKILL_GAP_MARKED"]
    cleared = body_of(
        persona.request(
            "POST",
            f"{SKILLS}/{skill['id']}/clear-gap",
            json={"expected_state_version": marked["state_version"]},
        )
    )
    assert cleared["user_marked_gap"] is False
    assert events_of(owner_session, "skill", skill["id"])[-1] == "SKILL_GAP_CLEARED"


def test_a_rejected_claim_keeps_its_row_sources_links_and_events(
    persona: Persona, owner_session: Session
) -> None:
    skill = create_skill(persona, "Widgets")
    claim = create_claim(
        persona, skill["id"], evidence_class="project", start_date="2021-01-01", end_date=None
    )
    assert get_skill(persona, skill["id"])["is_current"] is True

    rejected = body_of(
        persona.request(
            "POST",
            f"{CLAIMS}/{claim['id']}/reject",
            json={"expected_state_version": claim["state_version"]},
        )
    )

    assert rejected["confirmation_status"] == "rejected"
    assert [source["assertion_text"] for source in rejected["sources"]] == [
        claim["sources"][0]["assertion_text"]
    ]
    assert [ref["id"] for ref in rejected["skills"]] == [skill["id"]]
    assert (
        persona.request("GET", CLAIMS, params={"status": "rejected"}).json()[0]["id"] == claim["id"]
    )
    assert events_of(owner_session, "claim", claim["id"]) == ["CLAIM_CONFIRMED", "CLAIM_REJECTED"]
    owner_session.rollback()
    kept = owner_session.execute(
        text(
            "SELECT (SELECT count(*) FROM claims), (SELECT count(*) FROM evidence_sources), "
            "(SELECT count(*) FROM claim_skills)"
        )
    ).one()
    assert tuple(kept) == (1, 1, 1)
    detail = get_skill(persona, skill["id"])
    assert detail["badges"] == []
    assert detail["is_current"] is False
    assert detail["latest_end_date"] is None
    assert mark_gap(persona, detail).status_code == 200


def test_resume_exposure_never_includes_another_users_resumes(
    persona: Persona, other: Persona, owner_session: Session
) -> None:
    mine = create_skill(persona, "Widgets")
    theirs = create_skill(other, "Widgets")
    upload_resume(persona, owner_session, tag="mine", text_body="Nothing relevant here")
    upload_resume(other, owner_session, tag="theirs", text_body="Years of widgets experience")

    assert get_skill(persona, mine["id"])["exposure"] == []
    assert [item["label"] for item in get_skill(other, theirs["id"])["exposure"]] == [
        "Resume theirs"
    ]
    (listed,) = persona.request("GET", SKILLS).json()
    assert listed["exposure"] == []
