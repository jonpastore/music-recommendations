from datetime import datetime


def verification_url(value: str) -> str:
    """Return a browser-safe TIDAL device authorization URL."""
    return value if value.startswith(("https://", "http://")) else f"https://{value}"


def session_data_for_storage(token_type, access_token, refresh_token, expiry_time, is_pkce=False):
    """Make TIDAL's OAuth state safe to write as JSON."""
    return {
        "token_type": token_type,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expiry_time": expiry_time.isoformat() if expiry_time else None,
        "is_pkce": is_pkce,
    }


def expiry_time_from_storage(value):
    return datetime.fromisoformat(value) if value else None
