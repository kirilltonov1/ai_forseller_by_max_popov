"""Join a read-only CRM snapshot to marketplace demand. Never mutate warehouse stock."""
import base64
import hashlib
import json
import math
from collections import defaultdict


def identity(marketplace, credential):
    if not credential:
        return None
    if marketplace == 'wb':
        try:
            oid = json.loads(base64.urlsafe_b64decode(credential.split('.')[1] + '==')).get('oid')
        except (ValueError, IndexError):
            oid = None
        credential = 'oid:' + str(oid) if oid else 'token:' + credential
    return hashlib.sha256((marketplace.lower() + ':' + credential.strip()).encode()).hexdigest()


def plan(snapshot, links, reports, target_days=28, lead_days=7):
    products = {p['id']: dict(p, own=0, fulfillment=0, incoming=0, reserved=0, sent=0, channels=[]) for p in snapshot['products']}
    for b in snapshot['balances']:
        p = products.get(b['product_id'])
        if p and b['location'] in ('own', 'fulfillment'):
            p[b['location']] += b['quantity']
    for b in snapshot['shipments']:
        if b['product_id'] in products:
            products[b['product_id']]['incoming'] += b['quantity']
    outstanding = defaultdict(int)
    for t in snapshot['transfers']:
        if t['product_id'] in products:
            products[t['product_id']]['reserved' if t['status'] == 'packing' else 'sent'] += t['quantity']
            if t['model'] == 'FBO':
                outstanding[t['product_id'], t['shop_id']] += t['quantity']
    aliases = defaultdict(lambda: defaultdict(set))
    for a in snapshot['aliases']:
        aliases[a['shop_id']][a['sku']].add(a['product_id'])
    unmatched = []
    for source_id, report in reports.items():
        grouped = defaultdict(list)
        for r in report['rows']:
            # Exact seller SKU in the selected shop. Never fuzzy-match different needle sizes.
            ids = aliases[source_id].get(r['sku'], set())
            if len(ids) != 1:
                unmatched.append({'shop': report['title'], 'sku': r['sku'], 'reason': 'Нет однозначной связи с товаром CRM'})
                continue
            grouped[next(iter(ids))].append(r)
        for pid, items in grouped.items():
            if pid not in products:
                continue
            valid = all(r.get('stock') is not None and r.get('daily') is not None for r in items)
            stock = sum(r['stock'] for r in items) if valid else None
            daily = sum(r['daily'] for r in items) if valid else None
            transit = outstanding[pid, source_id]
            need = max(0, math.ceil(daily * (target_days + lead_days) - stock - transit)) if valid and daily > 0 else None
            products[pid]['channels'].append({
                'source_shop_id': source_id, 'shop_id': links[source_id], 'shop': report['title'],
                'skus': [r['sku'] for r in items], 'stock': stock, 'daily': daily, 'in_transit': transit,
                'days_left': round(stock / daily, 1) if valid and daily > 0 else None,
                'need': need, 'allocated': 0, 'data_at': report.get('data_at'), 'stale': report.get('stale', False),
            })
    result = list(products.values())
    for p in result:
        # One shared pool, allocated once. Lowest cover gets priority; stable ID tie-break.
        pool = max(0, int(p['own']))
        channels = sorted(p['channels'], key=lambda r: (r['days_left'] is None, r['days_left'] or 0, r['shop_id']))
        for ch in channels:
            ch['allocated'] = min(pool, ch['need'] or 0) if not ch['stale'] else 0
            pool -= ch['allocated']
        p['to_ship'] = sum(ch['allocated'] for ch in channels)
        p['unallocated'] = pool
        p['shortage'] = sum(ch['need'] or 0 for ch in channels) - p['to_ship']
    return {'products': result, 'unmatched': unmatched}
