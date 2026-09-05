def verification_url(value: str) -> str:
    """Return a browser-safe TIDAL device authorization URL."""
    return value if value.startswith(("https://", "http://")) else f"https://{value}"
