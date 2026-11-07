"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from limits.storage import MemoryStorage
from limits.strategies import FixedWindowRateLimiter

from gateway.limiter import limiter


@pytest.fixture(autouse=True)
def isolated_rate_limiter() -> Iterator[None]:
    """Use fresh in-memory counters so tests never depend on shared Redis state."""
    storage = MemoryStorage()
    previous_storage = limiter._storage
    previous_limiter = limiter._limiter
    previous_storage_dead = limiter._storage_dead
    limiter._storage = storage
    limiter._limiter = FixedWindowRateLimiter(storage)
    limiter._storage_dead = False
    try:
        yield
    finally:
        limiter._storage = previous_storage
        limiter._limiter = previous_limiter
        limiter._storage_dead = previous_storage_dead