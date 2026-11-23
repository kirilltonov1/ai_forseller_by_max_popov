"""Read-only CRM connection and stock allocation preview for the installation owner."""
import json
import threading
import time
from datetime import timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from . import auth, config, vault
from .warehouse import identity, plan
from .web import _cached, conn, current_user

router = APIRouter()
_lock = threading.Lock()
_snapshot = None
_snapshot_at = 0.0


def access(c, u):
    # This installation's shared physical warehouse is visible only to the actual
    # configured owner, with unrestricted membership. Support/superadmin is no bypass.
    email = config.env().get('FIRST_ADMIN_EMAIL', '').strip().lower()
    if not email or u.get('email', '').lower() != email or u.get('_mcp'):
        raise HTTPException(403, 'Общий склад доступен владельцу установки')
    rows = c.execute("SELECT workspace_id FROM memberships WHERE user_id=%s AND role='owner' AND shop_ids IS NULL", (u['id'],)).fetchall()
    if len(rows) != 1:
        raise HTTPException(403, 'Для общего склада требуется один основной кабинет владельца')
    return rows[0]['workspace_id']


def snapshot():
    global _snapshot, _snapshot_at
    with _lock:
        if _snapshot is not None and time.monotonic() - _snapshot_at < 30:
            return _snapshot
        env = config.env()
        base, key = env.get('WAREHOUSE_CRM_URL', '').rstrip('/'), env.get('WAREHOUSE_EXPORT_KEY', '')
        if not base.startswith('https://') or len(key) < 32:
            raise HTTPException(503, 'Подключение к складской CRM ещё не настроено')
        try:
            # Only a server-configured HTTPS origin; no user-supplied URL, no redirects.
            with httpx.Client(timeout=20, follow_redirects=False) as client:
                with client.stream('GET', base + '/api/integrations/warehouse-export', headers={'Authorization': 'Bearer ' + key}) as r:
                    r.raise_for_status()
                    data = bytearray()
                    for chunk in r.iter_bytes():
                        data.extend(chunk)
                        if len(data) > 10_000_000:
                            raise ValueError('oversized')
            value = json.loads(data)
            if value.get('version') != 1 or any(not isinstance(value.get(k), list) for k in ('products','balances','shops','aliases','transfers','shipments')):
                raise ValueError('schema')
        except (httpx.HTTPError, ValueError):
            # Fail closed: stale physical quantities must not become a shipment plan.
            raise HTTPException(502, 'Не удалось обновить склад. План не рассчитан; повторите обновление.') from None
        _snapshot, _snapshot_at = value, time.monotonic()
        return value


def links_for(c, ws, shops, source):
    links = {r['source_shop_id']: r['account_id'] for r in c.execute('SELECT source_shop_id,account_id FROM warehouse_links WHERE workspace_id=%s', (ws,))}
    allowed = {s['id']: s for s in shops}
    sources = {s['id']: s for s in source['shops']}
    links = {k:v for k,v in links.items() if v in allowed and k in sources and sources[k]['marketplace'].lower() == allowed[v]['marketplace']}
    identities = {}
    for s in shops:
        try:
            account = c.execute('SELECT * FROM accounts WHERE id=%s', (s['id'],)).fetchone()
            token = vault.token_for(c, account)
            credential = json.loads(token)['client_id'] if s['marketplace'] == 'ozon' else token
            identities[s['id']] = identity(s['marketplace'], str(credential))
        except (SystemExit, ValueError, KeyError):
            continue
    for src in source['shops']:
        candidates = [sid for sid, ident in identities.items() if ident and ident == src.get('identity') and allowed[sid]['marketplace'] == src['marketplace'].lower()]
        if src['id'] not in links and len(candidates) == 1 and candidates[0] not in links.values():
            # Also require a unique source: duplicate source shops need explicit selection.
            if sum(s.get('identity') == src.get('identity') for s in source['shops']) == 1:
                links[src['id']] = candidates[0]
    return links


def demand(c, shop):
    dt = config.today_msk() - timedelta(days=1)
    f = {'date_from': dt - timedelta(days=27), 'date_to': dt, 'nm_ids': None, 'group': None}
    key = 'oz_svod' if shop['marketplace'] == 'ozon' else 'stock_plan'
    r = _cached(c, key, shop['id'], f)
    out = []
    for row in r['rows']:
        if shop['marketplace'] == 'ozon':
            # Same period and values as the existing Ozon summary, excluding cancellations.
            q = row.get('orders_qty')
            daily = max(0, float(q) - float(row.get('cancel_qty') or 0)) / 28 if q is not None else None
            stock = float(row['stock']) if row.get('stock') is not None else None
            sku = row.get('offer_id')
        else:
            daily = float(row['avg_orders']) if row.get('avg_orders') is not None else None
            stock = float(row['stock']) if row.get('stock') is not None else None
            sku = row.get('vendor_code')
        if sku:
            out.append({'sku': str(sku), 'daily': daily, 'stock': stock})
    return {'title': shop['title'] or shop['name'], 'rows': out, 'stale': bool(r.get('stale')), 'data_at': r.get('cached_at')}


@router.get('/api/warehouse')
def warehouse(target_days: int = Query(28, ge=1, le=180), lead_days: int = Query(7, ge=0, le=90), u=Depends(current_user), c=Depends(conn)):
    ws = access(c, u)
    source = snapshot()
    shops = [s for s in auth.shops_for(c, u) if s['workspace_id'] == ws and s['marketplace'] in ('wb','ozon')]
    links = links_for(c, ws, shops, source)
    reports, errors = {}, []
    for source_id, shop_id in links.items():
        shop = next(s for s in shops if s['id'] == shop_id)
        try:
            reports[source_id] = demand(c, shop)
        except Exception:
            c.rollback()
            errors.append({'shop': shop['title'] or shop['name'], 'message': 'Данные аналитики ещё не готовы; поставка не рассчитана'})
    result = plan(source, links, reports, target_days, lead_days)
    return jsonable_encoder({**result, 'generated_at': source['generated_at'], 'source_url': config.env().get('WAREHOUSE_CRM_URL'),
        'target_days': target_days, 'lead_days': lead_days, 'errors': errors, 'links': links,
        'source_shops': [{k:s[k] for k in ('id','name','marketplace')} for s in source['shops']],
        'shops': [{'id':s['id'], 'title':s['title'] or s['name'], 'marketplace':s['marketplace']} for s in shops]})


class Link(BaseModel):
    source_shop_id: int
    shop_id: int


@router.put('/api/warehouse/link')
def save_link(body: Link, u=Depends(current_user), c=Depends(conn)):
    ws = access(c, u)
    shops = [s for s in auth.shops_for(c,u) if s['workspace_id'] == ws]
    dest = next((s for s in shops if s['id'] == body.shop_id), None)
    src = next((s for s in snapshot()['shops'] if s['id'] == body.source_shop_id), None)
    if not dest or not src or dest['marketplace'] != src['marketplace'].lower():
        raise HTTPException(422, 'Выберите доступный магазин того же маркетплейса')
    conflict = c.execute('SELECT source_shop_id FROM warehouse_links WHERE workspace_id=%s AND account_id=%s AND source_shop_id<>%s', (ws,body.shop_id,body.source_shop_id)).fetchone()
    if conflict:
        raise HTTPException(409, 'Этот магазин уже связан с другим магазином CRM')
    c.execute('INSERT INTO warehouse_links(workspace_id,source_shop_id,account_id) VALUES(%s,%s,%s) ON CONFLICT(workspace_id,source_shop_id) DO UPDATE SET account_id=EXCLUDED.account_id,updated_at=now()', (ws,body.source_shop_id,body.shop_id))
    c.commit()
    return {'ok': True}
