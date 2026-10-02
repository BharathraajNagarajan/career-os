import time

from app.core.ids import new_id


def test_new_id_is_uuid_version_7_with_rfc_variant() -> None:
    value = new_id()

    assert value.version == 7
    assert value.variant == "specified in RFC 4122"


def test_new_ids_are_time_ordered() -> None:
    first = new_id()
    time.sleep(0.002)
    later = new_id()

    assert first < later


def test_new_ids_are_unique_and_monotonic_within_a_burst() -> None:
    ids = [new_id() for _ in range(1000)]

    assert len(set(ids)) == len(ids)
    assert ids == sorted(ids)
