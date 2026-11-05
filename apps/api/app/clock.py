from datetime import datetime, timezone


def utcnow() -> datetime:
    """Injected as a dependency so tests can move time past a match's lock."""
    return datetime.now(timezone.utc)
