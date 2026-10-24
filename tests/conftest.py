import pytest

from gpload_loader import load_gpload


@pytest.fixture(scope="session")
def gpload():
    return load_gpload()
