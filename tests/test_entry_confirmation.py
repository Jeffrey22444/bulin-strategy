from bbmr.entry_confirmation import (
    long_entry_confirmed,
    pending_expired,
    pending_invalidated,
    short_entry_confirmed,
)
from bbmr.signals import EntryReference


def test_15m_entry_confirmation_uses_frozen_reference():
    ref = EntryReference("t", 90.0, 100.0, 110.0, 5.0, "long")
    assert long_entry_confirmed(91.0, ref) is True
    assert long_entry_confirmed(90.0, ref) is False
    assert short_entry_confirmed(109.0, ref) is True
    assert short_entry_confirmed(110.0, ref) is False


def test_pending_expiry_uses_reentry_bars():
    assert pending_expired(13, 12) is True
    assert pending_expired(12, 12) is False


def test_pending_invalidation_predicates():
    assert pending_invalidated("long", False, False, True, False, 1.0, 1.8) is True
    assert pending_invalidated("short", False, False, False, True, 1.0, 1.8) is True
    assert pending_invalidated("long", False, False, False, False, 1.8, 1.8) is True
    assert pending_invalidated("long", False, False, False, True, 1.0, 1.8) is False
