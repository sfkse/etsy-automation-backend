"""
Tests for the operational-integration seed loader.

We can't use a real DB (JSONB rules out SQLite in-memory), so we drive a
MagicMock session that tracks .add() calls and returns the "already exists"
signal for a second run to confirm idempotency.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.db import seed_shop_defaults


def _empty_session() -> MagicMock:
    """Session that returns None for every filter_by(...).first() lookup."""
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None
    return session


def _populated_session() -> MagicMock:
    """Session where every existence lookup finds a row (idempotency case).

    The row is a MagicMock so that seed_description_templates can re-apply the
    Finish / Best Gift sections onto existing rows (attribute assignment) without
    inserting anything new.
    """
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = MagicMock()
    return session


def test_seed_all_inserts_on_empty_db():
    session = _empty_session()
    seed_shop_defaults.seed_all(session)
    # At minimum: 1 ShopSettings + 1 PricingStrategy + 4 templates + 4 defaults
    # + 4 variation presets + 6 personalization templates = 20 inserts
    assert session.add.call_count >= 20
    assert session.commit.called


def test_seed_all_is_idempotent():
    session = _populated_session()
    seed_shop_defaults.seed_all(session)
    # Nothing inserted when every unique key resolves
    assert session.add.call_count == 0


def test_seed_variation_presets_inserts_four_when_empty():
    session = _empty_session()
    seed_shop_defaults.seed_variation_presets(session)
    assert session.add.call_count == 4


def test_seed_personalization_templates_inserts_library_when_empty():
    session = _empty_session()
    seed_shop_defaults.seed_personalization_templates(session)
    # See PersonalizationTemplate list in seed_shop_defaults.py (currently 6 rows)
    assert session.add.call_count == 6


def test_seed_universal_keywords_inserts_nine_when_empty():
    session = _empty_session()
    seed_shop_defaults.seed_universal_keywords(session)
    assert session.add.call_count == 9
    # every universal row is pillar-agnostic and flagged
    for call in session.add.call_args_list:
        row = call.args[0]
        assert row.is_universal is True
        assert row.carrier_pillar is None


def test_seed_universal_keywords_is_idempotent():
    session = _populated_session()
    seed_shop_defaults.seed_universal_keywords(session)
    assert session.add.call_count == 0


def test_seed_universal_keywords_logs_count_on_first_seed():
    session = _empty_session()
    with patch.object(seed_shop_defaults, "_log") as mock_log:
        seed_shop_defaults.seed_universal_keywords(session)
    mock_log.info.assert_called_once_with("universal_keywords_seeded", count=9)


def test_seed_universal_keywords_no_log_when_nothing_inserted():
    session = _populated_session()
    with patch.object(seed_shop_defaults, "_log") as mock_log:
        seed_shop_defaults.seed_universal_keywords(session)
    mock_log.info.assert_not_called()
