"""Owner-only, read-only shared CRM warehouse tool for web and Telegram."""
PROMPT = """
- «Мой склад», «наш склад», «общий склад», Viper Склад, CRM и «Общий склад и поставки» означают собственный склад пользователя: вызывай get_warehouse, а не fbs/остатки складов WB. Он общий для магазинов. Не выдавай склады маркетплейса за собственный склад.
- get_warehouse возвращает текущий снимок CRM, время снимка, остатки и расчёт поставок. own — свободно на своём складе, fulfillment — на фулфилменте, incoming — ожидается от поставщика; reserved/sent уже исключены из свободного остатка. Не вычитай их повторно. allocated — только рекомендация, не созданная поставка. null и ошибки аналитики не равны нулю. Указывай несвязанные магазины и устаревшие данные; не обещай покрытие без данных. При ошибке доступа/подключения прямо сообщи её, не подменяй источник отчётами WB.
"""
TOOLS = [{"name": "get_warehouse", "description": "Текущий собственный общий склад CRM (Viper Склад), товар в пути, резервы, дни запаса по связанным магазинам и рекомендованные поставки. Не склады WB/Ozon. Только чтение.", "input_schema": {"type": "object", "properties": {"query": {"type": "string", "description": "Артикул или часть названия; пусто — все товары"}, "offset": {"type": "integer", "minimum": 0}, "target_days": {"type": "integer", "minimum": 1, "maximum": 180}, "lead_days": {"type": "integer", "minimum": 0, "maximum": 90}}}}]


def get_warehouse(c, shop, uid, args):
    from . import api_warehouse
    from fastapi import HTTPException
    u = c.execute('SELECT * FROM users WHERE id=%s', (uid,)).fetchone()
    if not u:
        return {'error': 'Пользователь недоступен'}
    try:
        ws = api_warehouse.access(c, u)
        account = c.execute('SELECT workspace_id FROM accounts WHERE id=%s', (shop,)).fetchone()
        if not account or account['workspace_id'] != ws:
            return {'error': 'Общий склад недоступен в этом рабочем пространстве'}
        result = api_warehouse.warehouse(target_days=max(1, min(180, int(args.get('target_days', 28)))),
                                         lead_days=max(0, min(90, int(args.get('lead_days', 7)))), u=u, c=c)
    except HTTPException as e:
        return {'error': e.detail}
    products = result['products']
    totals = {k: sum(p.get(k, 0) for p in products) for k in ('own', 'fulfillment', 'incoming', 'reserved', 'sent')}
    query = str(args.get('query') or '').strip().casefold()
    selected = [p for p in products if not query or query in (str(p.get('sku', '')) + ' ' + str(p.get('title', ''))).casefold()]
    offset = max(0, int(args.get('offset', 0)))
    page = selected[offset:offset + 10]
    return {'source': 'Собственный общий склад CRM', 'generated_at': result['generated_at'],
            'totals_all_products': totals, 'products': page, 'matching_products': len(selected),
            'next_offset': offset + 10 if offset + 10 < len(selected) else None,
            'target_days': result['target_days'], 'lead_days': result['lead_days'], 'errors': result['errors'],
            'unlinked_shops': [s for s in result['source_shops'] if str(s['id']) not in {str(k) for k in result['links']}],
            'unmatched_count': len(result['unmatched']), 'unmatched_sample': result['unmatched'][:10]}


TOOL_FN = {'get_warehouse': get_warehouse}
