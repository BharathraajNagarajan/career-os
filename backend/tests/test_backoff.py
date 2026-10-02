import random

import pytest

from app.jobs.queue import backoff_seconds


@pytest.mark.parametrize(("attempt", "ceiling"), [(1, 10), (2, 20), (3, 40), (4, 80), (8, 300)])
def test_backoff_is_exponential_with_jitter_and_capped(attempt: int, ceiling: float) -> None:
    rng = random.Random(7)
    delays = [backoff_seconds(attempt, base=10, cap=300, rng=rng) for _ in range(200)]

    assert all(ceiling / 2 <= delay <= ceiling for delay in delays)
    assert len(set(delays)) > 1
