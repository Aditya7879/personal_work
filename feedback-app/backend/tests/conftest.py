import pytest

from app.cache import read_cache


@pytest.fixture(autouse=True)
def isolate_response_cache():
    read_cache.invalidate()
    yield
    read_cache.invalidate()
