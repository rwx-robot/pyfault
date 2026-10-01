"""Time helpers.

The framework used to read the clock through ``datetime.utcnow()`` in 303
places. That call is deprecated from Python 3.12 and returns a **naive**
datetime, so ``<``/``>`` against an aware value raise ``TypeError`` while
``==`` silently returns ``False``.

The migration to timezone-aware UTC lives here:
``utc_now()`` now returns an aware datetime, and every value crossing a
serialisation boundary goes through :func:`parse_iso` / :func:`to_utc`,
which read a missing offset as UTC. That keeps records written before the
migration comparable with records written after it.
"""

from datetime import datetime, timezone

__all__ = ["utc_now", "parse_iso", "to_utc"]


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def to_utc(value: datetime) -> datetime:
    """Normalise a datetime to aware UTC; a naive value is read as UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 string into an aware UTC datetime.

    Legacy records carry no UTC offset; without normalising them they would
    compare as ``TypeError`` against freshly generated aware timestamps.
    """
    return to_utc(datetime.fromisoformat(str(value)))
