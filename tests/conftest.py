"""
Shared pytest fixtures.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.db.models import Product, ProductStatus


@pytest.fixture
def sample_product() -> Product:
    """
    A bare Product ORM object with sensible defaults.
    Not persisted to any database.
    """
    product = Product(
        id=1,
        sku="TAKI-0001",
        carrier_pillar="cross",
        material="925 Sterling Silver",
        color="Silver",
        has_stone=False,
        selling_price=29.99,
        status=ProductStatus.MANUAL_INPUT.value,
    )
    return product


@pytest.fixture
def mock_session() -> MagicMock:
    """
    A MagicMock that mimics a SQLAlchemy Session with typical query chaining.

    Usage::

        mock_session.query(Model).filter_by(...).all.return_value = [...]
    """
    session = MagicMock()
    # Make query().filter().all() / .first() return sensible defaults
    session.query.return_value.filter.return_value.all.return_value = []
    session.query.return_value.filter.return_value.first.return_value = None
    session.query.return_value.filter_by.return_value.all.return_value = []
    session.query.return_value.filter_by.return_value.first.return_value = None
    session.query.return_value.order_by.return_value.first.return_value = None
    return session
