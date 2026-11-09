"""
SASAA – Telephony Provider Registry
======================================
Single point of truth for which telephony adapter is active.

Usage:
    from app.telephony.registry import get_provider
    adapter = get_provider()
    health = await adapter.get_provider_health()

The active provider is controlled by the TELEPHONY_PROVIDER env variable:
  mock   – MockTelephonyAdapter (default for development/tests)
  exotel – ExotelAdapter (requires EXOTEL_* credentials in .env)
"""

from functools import lru_cache

from app.telephony.provider_base import TelephonyProviderBase


@lru_cache(maxsize=1)
def get_provider() -> TelephonyProviderBase:
    """
    Return the configured telephony provider adapter.
    Cached so the same instance is reused across all requests.
    """
    from app.core.config import settings

    provider_name = (settings.telephony_provider or "mock").lower().strip()

    if provider_name == "exotel":
        from app.telephony.exotel_adapter import ExotelAdapter
        return ExotelAdapter(
            account_sid=settings.exotel_account_sid or None,
            api_key=settings.exotel_api_key or None,
            api_token=settings.exotel_api_token or None,
            phone_number=settings.exotel_phone_number or None,
            webhook_secret=settings.exotel_webhook_secret or None,
            subdomain=settings.exotel_subdomain,
        )

    # Default: mock adapter (safe for development and tests)
    from app.telephony.mock_adapter import MockTelephonyAdapter
    return MockTelephonyAdapter()


def reset_provider_cache() -> None:
    """Clear the cached provider — used in tests to inject a fresh mock."""
    get_provider.cache_clear()
