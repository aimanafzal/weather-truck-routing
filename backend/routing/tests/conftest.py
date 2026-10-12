import pytest


@pytest.fixture(autouse=True)
def offline(settings):
    """Tests never touch the network: use the deterministic fake providers."""
    settings.PROVIDER_MODE = "fake"
    settings.ALLOWED_HOSTS = ["*"]
    from django.core.cache import cache

    cache.clear()
