"""Tests for approval.service.get_variation_matrix helper (PR 2)."""
from __future__ import annotations

from unittest.mock import MagicMock

from src.db.models import VariationRow
from src.modules.approval.service import get_variation_matrix


def _rows_sample() -> list[VariationRow]:
    """Rows are returned already ordered by (finish, length_inches, multi_count).

    The helper's job is to flatten, not to sort — the session-side .order_by()
    handles the ordering.
    """
    return [
        VariationRow(
            product_id=1, finish="Gold", length_inches=16, multi_count=None,
            price_cents=3200, sku_suffix="GO-L16", is_loss_leader=False,
        ),
        VariationRow(
            product_id=1, finish="Gold", length_inches=18, multi_count=None,
            price_cents=3300, sku_suffix="GO-L18", is_loss_leader=False,
        ),
        VariationRow(
            product_id=1, finish="Rose", length_inches=12, multi_count=None,
            price_cents=1500, sku_suffix="RO-L12", is_loss_leader=True,
        ),
    ]


def _session_with_rows(rows: list[VariationRow]) -> MagicMock:
    session = MagicMock()
    chain = session.query.return_value.filter_by.return_value.order_by.return_value
    chain.all.return_value = rows
    return session


def test_empty_product_returns_empty_list():
    session = _session_with_rows([])
    assert get_variation_matrix(session, product_id=99) == []


def test_flattens_rows_preserving_order_and_loss_leader():
    rows = _rows_sample()
    session = _session_with_rows(rows)

    result = get_variation_matrix(session, product_id=1)

    assert len(result) == 3
    assert [r["finish"] for r in result] == ["Gold", "Gold", "Rose"]
    assert [r["length_inches"] for r in result] == [16, 18, 12]
    assert [r["price_cents"] for r in result] == [3200, 3300, 1500]
    assert [r["sku_suffix"] for r in result] == ["GO-L16", "GO-L18", "RO-L12"]
    assert [r["is_loss_leader"] for r in result] == [False, False, True]


def test_ordering_arguments_include_finish_length_and_multi_count():
    """Regression guard: helper must query with the tri-key order_by so the
    payload builder and UI see rows in the same order."""
    session = _session_with_rows([])
    get_variation_matrix(session, product_id=1)

    session.query.assert_called_with(VariationRow)
    order_by_call = session.query.return_value.filter_by.return_value.order_by
    order_by_call.assert_called_once()
    args = order_by_call.call_args.args
    assert len(args) == 3
    assert args[0] is VariationRow.finish
    assert args[1] is VariationRow.length_inches
    assert args[2] is VariationRow.multi_count
