"""Time helpers.

The framework called ``datetime.utcnow()`` in 303 places. That call is
deprecated from Python 3.12 and naive, which makes ``<``/``>`` comparisons
against timezone-aware values raise ``TypeError`` while ``==`` silently
returns ``False``.

``utc_now()`` is a drop-in replacement: same naive-UTC semantics, no
DeprecationWarning, and defined in exactly one place.

Migrating to timezone-aware datetimes (``datetime.now(timezone.utc)``) is a
deliberate breaking change for the public API -- ~200 test call sites build
naive literals and several of them compare with ``==``, which would flip to
False without raising. That migration must happen as its own reviewed change;
when it lands, this file is the only place that needs editing.
"""

from datetime import datetime, timezone

__all__ = ["utc_now"]


def utc_now() -> datetime:
    """Return the current UTC time, naive (same as ``datetime.utcnow()``)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
