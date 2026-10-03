import math
import uuid

import pytest

from app.db.models import Opportunity, QualificationCategory, QualificationKind, WorkplaceType
from app.llm.prompts.jd_extract import JdExtraction
from app.opportunities.duplicates import duplicate_reason
from app.opportunities.extraction import clean_extraction
from app.opportunities.normalize import (
    LEGAL_SUFFIXES,
    clamp_min_years,
    normalize_company_name,
    normalize_domain,
    normalize_skill_keys,
    normalize_text,
)
from app.opportunities.schemas import (
    CompanyCreate,
    IngestRequest,
    LocationItem,
    OpportunityPatch,
    QualificationPatch,
    clean_url,
)
from tests.db.opportunity_helpers import (
    Q_AUTH,
    Q_PYTHON,
    Q_YEARS,
    SYNTHETIC_JD,
    default_qualifications,
    extraction_json,
    qualification,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Example Corp", "example"),
        ("Example, Inc.", "example"),
        ("EXAMPLE CORPORATION", "example"),
        ("Example Co Ltd", "example"),
        ("Example Pvt. Ltd.", "example"),
        ("Example Private Limited", "example"),
        ("Example GmbH", "example"),
        ("Example PLC", "example"),
        ("Ｅxample  Corp", "example"),
        ("AT&T Inc", "att"),
        ("Example-Widgets Ltd", "examplewidgets"),
        ("  Example   Widgets  ", "example widgets"),
        ("Corp", "corp"),
        ("Inc.", "inc"),
        ("Incorporated Widgets", "incorporated widgets"),
        ("Co Widgets", "co widgets"),
        ("Example Sa", "example"),
        ("Example AG", "example"),
        ("Example BV", "example"),
        ("Example LLC", "example"),
    ],
)
def test_company_names_normalize_case_punctuation_and_trailing_legal_suffixes(
    raw: str, expected: str
) -> None:
    assert normalize_company_name(raw) == expected


def test_only_listed_suffixes_are_stripped_and_only_at_the_end() -> None:
    assert LEGAL_SUFFIXES == {
        "inc",
        "llc",
        "ltd",
        "limited",
        "corp",
        "corporation",
        "co",
        "gmbh",
        "plc",
        "sa",
        "ag",
        "bv",
        "pvt",
        "private",
    }
    assert normalize_company_name("Private Example") == "private example"
    assert normalize_company_name("Example Holdings") == "example holdings"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Example.com", "example.com"),
        ("https://www.Example.com/careers?x=1", "example.com"),
        ("HTTP://careers.example.co.uk:8080/a#b", "careers.example.co.uk"),
        ("  www.example.org  ", "example.org"),
        ("example.com.", "example.com"),
        ("bücher.example", "xn--bcher-kva.example"),
    ],
)
def test_domains_are_lowercased_and_stripped_of_scheme_path_and_www(
    raw: str, expected: str
) -> None:
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "localhost",
        "fake",
        "exa mple.com",
        "-bad.example.com",
        "example..com",
        "example.c",
        "example.123",
        "user@example.com",
        "http://",
        "a" * 64 + ".com",
    ],
)
def test_invalid_domains_are_rejected(raw: str) -> None:
    assert normalize_domain(raw) is None


def test_skill_keys_are_trimmed_lowercased_deduplicated_and_capped() -> None:
    keys = normalize_skill_keys(
        ["  Python ", "python", "SQL", "", "   ", "x" * 80, *[f"k{i}" for i in range(20)]]
    )

    assert keys[:3] == ["python", "sql", "x" * 40]
    assert len(keys) == 10
    assert len(set(keys)) == 10


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), (-3, 0), (0, 0), (4.4, 4), (4.6, 5), (500, 50), (math.nan, None)],
)
def test_min_years_are_clamped_to_zero_through_fifty(
    value: float | None, expected: int | None
) -> None:
    assert clamp_min_years(value) == expected


def test_text_normalization_for_comparison_ignores_case_punctuation_and_spacing() -> None:
    assert normalize_text("Senior  Widget-Engineer (Remote)!") == "senior widgetengineer remote"


@pytest.mark.parametrize(
    "value", ["https://example.test/jobs/1", " http://example.test ", None, ""]
)
def test_urls_accept_http_and_https_only(value: str | None) -> None:
    cleaned = clean_url(value)

    assert cleaned == (value.strip() if value and value.strip() else None)


@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(1)",
        "ftp://example.test/file",
        "file:///etc/passwd",
        "example.test/jobs",
        "http://",
        "https://exa mple.test",
        "https://example.test/" + "a" * 2100,
        "data:text/html,<script>1</script>",
    ],
)
def test_other_url_shapes_are_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="http or https"):
        clean_url(value)


def test_request_models_reject_unknown_and_null_required_fields() -> None:
    with pytest.raises(ValueError, match="source_url|http"):
        IngestRequest(jd_text="x", source_url="ftp://example.test")
    with pytest.raises(ValueError, match="cannot be null"):
        OpportunityPatch(expected_state_version=1, workplace_type=None)
    with pytest.raises(ValueError, match="cannot be null"):
        OpportunityPatch(expected_state_version=1, locations=None)
    with pytest.raises(ValueError, match="text_verbatim|Extra"):
        QualificationPatch.model_validate({"text_verbatim": "changed"})
    with pytest.raises(ValueError, match="cannot be null"):
        QualificationPatch(kind=None)
    with pytest.raises(ValueError, match="ISO"):
        LocationItem(country="ZZ")
    assert LocationItem(country=" us ").country == "US"
    company = CompanyCreate(
        name="  Example   Corp ",
        aliases=["Ex", "ex", " EX "],
        domains=["https://WWW.Example.com/x", "example.com"],
    )
    assert company.name == "Example Corp"
    assert company.aliases == ["Ex"]
    assert company.domains == ["example.com"]


def raw_extraction(**overrides: object) -> JdExtraction:
    return JdExtraction.model_validate_json(extraction_json(**overrides))


def test_grounded_qualifications_are_kept_with_normalized_fields() -> None:
    clean = clean_extraction(raw_extraction(), SYNTHETIC_JD)

    assert [item.text_verbatim for item in clean.qualifications][:3] == [Q_YEARS, Q_PYTHON, Q_AUTH]
    assert clean.dropped_qualifications == 0
    python = clean.qualifications[1]
    assert python.skill_keys == ["python", "sql"]
    assert python.kind is QualificationKind.MINIMUM
    assert clean.qualifications[2].category is QualificationCategory.AUTHORIZATION
    assert clean.qualifications[2].is_hard_constraint is True
    assert clean.qualifications[0].min_years == 5
    assert clean.workplace_type is WorkplaceType.HYBRID
    assert clean.company_domain == "example.test"
    assert clean.locations.model_dump()["items"] == [
        {"city": "Springfield", "region": "IL", "country": "US"}
    ]


def test_a_qualification_not_present_in_the_posting_is_dropped_and_counted() -> None:
    invented = qualification("Ten years of experience with imaginary gadgets")
    clean = clean_extraction(
        raw_extraction(qualifications=[*default_qualifications(), invented]), SYNTHETIC_JD
    )

    assert len(clean.qualifications) == 5
    assert clean.dropped_qualifications == 1
    assert all("imaginary" not in item.text_verbatim for item in clean.qualifications)


def test_grounding_ignores_whitespace_differences_but_not_wording() -> None:
    spaced = qualification("Proficiency   in Python\nand SQL")
    reworded = qualification("Proficiency in Python and also SQL")

    clean = clean_extraction(raw_extraction(qualifications=[spaced, reworded]), SYNTHETIC_JD)

    assert [item.text_verbatim for item in clean.qualifications] == [Q_PYTHON]
    assert clean.dropped_qualifications == 1


def test_duplicate_qualification_lines_are_kept_once() -> None:
    line = qualification(Q_PYTHON)

    clean = clean_extraction(raw_extraction(qualifications=[line, line]), SYNTHETIC_JD)

    assert len(clean.qualifications) == 1
    assert clean.dropped_qualifications == 1


def test_invalid_values_are_discarded_instead_of_failing_the_extraction() -> None:
    clean = clean_extraction(
        raw_extraction(
            company_domain="not a domain",
            locations=[
                {"city": "Springfield", "region": None, "country": "ZZ"},
                {"city": None, "region": None, "country": "QQ"},
                {"city": "  ", "region": "", "country": None},
            ],
            qualifications=[qualification(Q_YEARS, min_years=900)],
            title="   ",
        ),
        SYNTHETIC_JD,
    )

    assert clean.company_domain is None
    assert clean.locations.model_dump()["items"] == [
        {"city": "Springfield", "region": None, "country": None}
    ]
    assert clean.qualifications[0].min_years == 50
    assert clean.title is None


def opportunity(**values: object) -> Opportunity:
    base: dict[str, object] = {
        "id": uuid.uuid4(),
        "company_id": uuid.UUID(int=1),
        "title": "Senior Widget Engineer",
        "external_job_id": None,
        "location_text": "Springfield, IL",
    }
    base.update(values)
    return Opportunity(**base)


def test_exact_job_id_in_the_same_company_is_a_duplicate() -> None:
    a = opportunity(external_job_id="EX-1", title="One")
    b = opportunity(external_job_id="EX-1", title="Completely different")

    assert duplicate_reason(a, b) == ("exact_job_id", 1.0)


def test_similar_titles_in_the_same_company_with_matching_or_empty_location() -> None:
    a = opportunity()
    similar = opportunity(title="Senior Widget Engineer (m/f/d)", location_text=None)
    other_city = opportunity(location_text="Shelbyville, IL")

    found = duplicate_reason(a, similar)
    assert found is not None
    assert found[0] == "similar_title"
    assert found[1] >= 0.9
    assert duplicate_reason(a, other_city) is None


def test_different_company_or_dissimilar_title_is_not_a_duplicate() -> None:
    a = opportunity()

    assert duplicate_reason(a, opportunity(company_id=uuid.UUID(int=2))) is None
    assert duplicate_reason(a, opportunity(title="Junior Gadget Designer")) is None
    assert duplicate_reason(a, opportunity(title=None)) is None
    assert duplicate_reason(opportunity(company_id=None), opportunity(company_id=None)) is None
