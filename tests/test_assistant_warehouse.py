from unittest.mock import Mock, patch
import stometric.web
from stometric import assistant, assistant_warehouse as aw, api_warehouse
from fastapi import HTTPException


def test_registered():
    assert assistant.TOOL_FN['get_warehouse'] is aw.get_warehouse
    assert any(t['name'] == 'get_warehouse' for t in assistant.TOOLS)


def test_denied_before_snapshot():
    c = Mock()
    c.execute.return_value.fetchone.return_value = {'id': 1}
    with patch.object(api_warehouse, 'access', side_effect=HTTPException(403, 'denied')), patch.object(api_warehouse, 'warehouse') as read:
        assert aw.get_warehouse(c, 1, 1, {}) == {'error': 'denied'}
        read.assert_not_called()


def test_workspace_boundary():
    c = Mock()
    c.execute.return_value.fetchone.side_effect = [{'id': 1}, {'workspace_id': 2}]
    with patch.object(api_warehouse, 'access', return_value=1), patch.object(api_warehouse, 'warehouse') as read:
        assert 'error' in aw.get_warehouse(c, 1, 1, {})
        read.assert_not_called()


def test_totals_pagination_and_missing_links():
    c = Mock()
    c.execute.return_value.fetchone.side_effect = [{'id': 1}, {'workspace_id': 1}]
    result = dict(products=[dict(sku=str(i), own=2, reserved=1) for i in range(12)], generated_at='now', target_days=28, lead_days=7, errors=[], source_shops=[{'id': 1}, {'id': 2}], links={1: 9}, unmatched=[])
    with patch.object(api_warehouse, 'access', return_value=1), patch.object(api_warehouse, 'warehouse', return_value=result):
        r = aw.get_warehouse(c, 1, 1, {})
    assert r['totals_all_products']['own'] == 24
    assert len(r['products']) == 10 and r['next_offset'] == 10
    assert r['unlinked_shops'] == [{'id': 2}]
