"""Веб-сервис: API для фронта + отдача собранного фронта (web/frontend/dist). Слушает 127.0.0.1:8100, снаружи — nginx/HTTPS.

Запуск: .venv/bin/uvicorn stometric.web:app --host 127.0.0.1 --port 8100
"""

import json
import re
import time
from datetime import date, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, db, legal
from .config import today_msk
from .tabs import BY_KEY, OZ_TABS, TABS, YM_TABS, tabs_for

DIST = Path(__file__).resolve().parents[1] / "web" / "frontend" / "dist"
COOKIE = "ais_session"

app = FastAPI(title="Seller Analytics", docs_url=None, redoc_url=None, openapi_url=None)

from fastapi.middleware.gzip import GZipMiddleware  
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)


def conn():
    c = db.connect(timeout_s=55)     
    try:
        yield c
    finally:
        c.close()


SEC_HEADERS = {"Strict-Transport-Security": "max-age=31536000", "X-Frame-Options": "SAMEORIGIN",
               "Content-Security-Policy": "frame-ancestors 'self'", "X-Content-Type-Options": "nosniff",
               "Referrer-Policy": "strict-origin-when-cross-origin"}


@app.middleware("http")
async def sec_headers(request: Request, call_next):
    """Защитные заголовки (аудит 28.10): сайт нельзя встроить в чужую страницу (кликджекинг согласия OAuth, «Применить»), только HTTPS,
    браузер не угадывает тип файла."""
    resp = await call_next(request)
    for k, v in SEC_HEADERS.items():
        resp.headers.setdefault(k, v)
    return resp


@app.middleware("http")
async def mcp_guard(request: Request, call_next):
    """Запрос к API с токеном подключения нейросети (mcp_…): права подключения (mcp.check), лимит, журнал. Cookie при этом не смотрим."""
    h = request.headers.get("authorization") or ""
    if not request.url.path.startswith("/api/") or not h.lower().startswith("bearer "):
        return await call_next(request)
    import time as _t
    from fastapi.concurrency import run_in_threadpool
    from . import mcp

    def _grant():
        with db.connect() as c:
            return mcp.grant_by_token(c, h[7:].strip())
    g = await run_in_threadpool(_grant)
    if not g:
        detail = ("Код плагина недействителен, отозван или истёк. Получите новый в «Настройки аккаунта → Плагин Chrome» и подключите плагин заново."
                  if request.url.path.startswith("/api/plugin/") else "Токен подключения нейросети недействителен, отозван или истёк")
        return JSONResponse({"detail": detail}, 401)
    body = None
    if request.method not in ("GET", "HEAD"):
        try:
            body = json.loads(await request.body() or b"null")
        except ValueError:
            body = None
    path, t0, err = request.url.path, _t.monotonic(), None
    try:
        mcp.check(g, request.method, path, body)
        if not mcp.rate_ok(g["id"]):
            err = f"слишком часто: не больше {mcp.RATE_MIN} вызовов в минуту"
    except mcp.Denied as e:
        err = str(e)
    if err:
        resp = JSONResponse({"detail": "Нет права: " + err}, 429 if "часто" in err else 403)
    else:
        request.state.mcp = g
        resp = await call_next(request)
        if resp.status_code >= 400:
            err = f"HTTP {resp.status_code}"
    m = re.match(r"^/api/shops/(\d+)", path)

    def _log():
        with db.connect() as c:
            mcp.log(c, g["id"], "api", err is None, shop=int(m.group(1)) if m else None, method=request.method, path=path, error=err,
                    ms=int((_t.monotonic() - t0) * 1000))
            c.commit()
    await run_in_threadpool(_log)
    return resp


def current_user(request: Request, c=Depends(conn)):
    g = getattr(request.state, "mcp", None)
    if g:                                   
        u = c.execute("SELECT * FROM users WHERE id=%s AND is_active", (g["user_id"],)).fetchone()
        if not u:
            raise HTTPException(401, "Нужно войти")
        c._ai_actor_id = u["id"]
        return {**u, "is_superadmin": False, "_mcp": g}
    u = auth.session_user(c, request.cookies.get(COOKIE))
    if not u:
        raise HTTPException(401, "Нужно войти")
    c._ai_actor_id = u["id"]
    return u


class Login(BaseModel):
    email: str
    password: str


_fails: dict[str, list[float]] = {}     
FAIL_WINDOW, FAIL_EMAIL, FAIL_IP = 900, 8, 30


def _recent(key: str) -> list[float]:
    now = time.monotonic()
    q = [t for t in _fails.get(key, []) if now - t < FAIL_WINDOW]
    _fails[key] = q
    return q


def _throttle(request: Request, email: str) -> None:
    """Перебор паролей: больше 8 неудач на почту или 30 с одного IP за 15 минут — пауза."""
    ip = request.client.host if request.client else "-"
    if len(_recent("e:" + email)) >= FAIL_EMAIL or len(_recent("i:" + ip)) >= FAIL_IP:
        raise HTTPException(429, "Слишком много попыток входа — подождите 15 минут")


def _failed(request: Request, email: str) -> None:
    ip = request.client.host if request.client else "-"
    for k in ("e:" + email, "i:" + ip):
        _recent(k).append(time.monotonic())
    if len(_fails) > 50000:
        _fails.clear()


@app.post("/api/auth/login")
def login(body: Login, request: Request, response: Response, c=Depends(conn)):
    email = body.email.strip().lower()
    _throttle(request, email)
    u = c.execute("SELECT * FROM users WHERE email=%s AND is_active", (email,)).fetchone()
    ok = auth.check_password(body.password, u["password_hash"] if u else None)
    if not u or not ok:
        _failed(request, email)
        raise HTTPException(401, "Неверный логин или пароль")
    tok = auth.new_session(c, u["id"], request.client.host if request.client else None, request.headers.get("user-agent"))
    response.set_cookie(COOKIE, tok, max_age=auth.SESSION_DAYS * 86400, httponly=True, secure=True, samesite="lax")
    return {"ok": True}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response, c=Depends(conn)):
    tok = request.cookies.get(COOKIE)
    if tok:
        auth.drop_session(c, tok)
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/api/me")
def me(u=Depends(current_user), c=Depends(conn)):
    shops = auth.shops_for(c, u)
    dflt = u.get("default_shop_id")
    shops.sort(key=lambda s: s["id"] != dflt)          
    return {"user": {"id": u["id"], "email": u["email"], "name": u["name"], "superadmin": u["is_superadmin"], "google_email": u.get("google_email")},
            "default_shop": dflt if any(s["id"] == dflt for s in shops) else None,
            "shops": shops, "workspaces": auth.workspaces_for(c, u),
            "tabs": [{"key": k, "title": t, "group": g, "help": " ".join((fn.__doc__ or "").split())} for k, t, g, fn in TABS],
            "oz_tabs": [{"key": k, "title": t, "group": g, "help": " ".join((fn.__doc__ or "").split())} for k, t, g, fn in OZ_TABS],
            "ym_tabs": [{"key": k, "title": t, "group": g, "help": " ".join((fn.__doc__ or "").split())} for k, t, g, fn in YM_TABS],
            "hidden_tabs": u.get("hidden_tabs") or {}, "tabbar": u.get("tabbar") or {}, "gsheet": _gsheet_ready(c),
            "terms_need": legal.need_terms(c, u), "terms_version": legal.VERSION,
            "news_unread": c.execute("SELECT count(*) n FROM service_news WHERE id > %s", (u.get("news_seen_id") or 0,)).fetchone()["n"]}


class HiddenIn(BaseModel):
    mp: str
    keys: list[str]


@app.put("/api/me/tabbar")
def set_tabbar(body: HiddenIn, u=Depends(current_user), c=Depends(conn)):
    """Свои вкладки в горизонтальной панели — в этом порядке (пусто — все, как раньше)."""
    if body.mp not in ("wb", "ozon", "ym"):
        raise HTTPException(400, "Маркетплейс: wb, ozon или ym")
    known = {k for k, *_ in tabs_for(body.mp)}
    keys = list(dict.fromkeys(k for k in body.keys if k in known))
    c.execute("UPDATE users SET tabbar = tabbar || jsonb_build_object(%s::text, %s::jsonb) WHERE id=%s", (body.mp, json.dumps(keys), u["id"]))
    c.commit()
    return {"mp": body.mp, "keys": keys}


@app.put("/api/me/hidden_tabs")
def set_hidden_tabs(body: HiddenIn, u=Depends(current_user), c=Depends(conn)):
    """Скрыть вкладки в меню (только у себя). «Главную» скрыть нельзя."""
    if body.mp not in ("wb", "ozon", "ym"):
        raise HTTPException(400, "Маркетплейс: wb, ozon или ym")
    known = {k for k, *_ in tabs_for(body.mp)} - {"home"}
    keys = sorted(set(body.keys) & known)
    c.execute("UPDATE users SET hidden_tabs = hidden_tabs || jsonb_build_object(%s::text, %s::jsonb) WHERE id=%s",
              (body.mp, json.dumps(keys), u["id"]))
    c.commit()
    return {"mp": body.mp, "keys": keys}



@app.get("/api/public/about")
def public_about(c=Depends(conn)):
    v = legal.get(c)
    return {"ready": v["ready"], "version": v["version"], "about": legal.ABOUT, "support_bot": v.get("support_bot") or None,
            "channel": v.get("channel") or None, "email": v.get("email") or None, "org": v.get("org") or None}


@app.get("/api/public/legal/{doc}")
def public_legal(doc: str, request: Request, c=Depends(conn)):
    if doc not in legal.DOCS:
        raise HTTPException(404, "Нет такого документа")
    u = auth.session_user(c, request.cookies.get(COOKIE))
    return legal.document(c, doc, preview=bool(u and u["is_superadmin"]))


@app.post("/api/me/terms")
def accept_terms(u=Depends(current_user), c=Depends(conn)):
    if not legal.get(c)["ready"]:
        raise HTTPException(400, "Документы ещё не опубликованы")
    c.execute("UPDATE users SET terms_version=%s, terms_accepted_at=now() WHERE id=%s", (legal.VERSION, u["id"]))
    _audit(c, u, None, "terms/accept", {"version": legal.VERSION, "via": "site"})
    c.commit()
    return {"ok": True}


PLANS = {
    "basic": {"title": "Обычный", "about": "Все таблицы и графики по данным WB; позже — доп. модули.", "ready": True},
    "ai": {"title": "Наша нейросеть (API)", "about": "Будущий тариф: Гномик и аналитика через API сервиса. Пока не подключён.", "ready": False},
    "owner": {"title": "VIP (подписка владельца)", "about": "Codex для разрешённых магазинов владельца и их тестовых пользователей, с сохранением прав доступа.", "ready": True, "hidden": True},
    "mcp": {"title": "Ваша нейросеть (API)", "about": "Будущий тариф: Гномик и аналитика через API-ключ клиента. Пока не подключён. MCP-доступ настраивается отдельно.", "ready": False},
}
ROLE_TITLE = {"owner": "Владелец", "admin": "Админ", "editor": "Редактор", "viewer": "Просмотр"}


@app.get("/api/workspaces/{ws_id}")
def workspace(ws_id: int, u=Depends(current_user), c=Depends(conn)):
    """Кабинет: магазины и (для админа и выше) пользователи с их ролями."""
    role = auth.workspace_role(c, u, ws_id)
    if not auth.can(role, "viewer"):
        raise HTTPException(403, "Нет доступа к кабинету")
    ws = c.execute("SELECT id,name,created_at,plan,plan_changed_at,compare_fresh_days FROM workspaces WHERE id=%s", (ws_id,)).fetchone()
    shops = c.execute("""SELECT a.id,a.name,a.title,a.marketplace,a.is_active,a.created_at, t.info token, t.added_at token_at,
                                (SELECT jsonb_build_object('added_at', x.added_at) || x.info FROM account_ad_tokens x WHERE x.account_id=a.id) ad_token,
                                (a.token_env IS NOT NULL) token_server,
                                (SELECT count(*) FROM collector_state s WHERE s.account_id=a.id AND s.last_ok_at IS NOT NULL) loaded,
                                (SELECT max(last_ok_at) FROM collector_state s WHERE s.account_id=a.id) last_ok
                         FROM accounts a LEFT JOIN account_tokens t ON t.account_id=a.id
                         WHERE a.workspace_id=%s AND a.archived_at IS NULL ORDER BY a.id""", (ws_id,)).fetchall()
    from .collectors_ozon import AD_COLLECTORS as OZ_AD, FIRST_LOAD as OZ_FIRST
    from .collectors_ym import FIRST_LOAD as YM_FIRST
    for sh in shops:
        if sh["marketplace"] == "ym":
            sh["load_total"] = len(YM_FIRST)
        if sh["marketplace"] == "ozon":
            sh["load_total"] = len(OZ_FIRST) + (len(OZ_AD) if sh.get("ad_token") else 0)
        if not auth.can(role, "admin"):
            sh.pop("token", None)
            sh.pop("ad_token", None)
        elif not sh["token"] and sh["token_server"]:   
            from . import vault
            from .config import env as _env
            tok = _env().get(c.execute("SELECT token_env FROM accounts WHERE id=%s", (sh["id"],)).fetchone()["token_env"] or "")
            sh["token"] = {k: v for k, v in vault.info(tok).items() if k != "error"} if tok else None
    members = None
    if auth.can(role, "admin"):
        members = c.execute("""SELECT u.id,u.email,u.name,m.role,m.shop_ids,u.last_login_at,u.is_active FROM memberships m
                               JOIN users u ON u.id=m.user_id WHERE m.workspace_id=%s
                               ORDER BY array_position(ARRAY['owner','admin','editor','viewer'], m.role), u.email""", (ws_id,)).fetchall()
    from .__main__ import FIRST_LOAD
    return jsonable_encoder({**ws, "first_load_total": len(FIRST_LOAD), "role": role, "role_title": ROLE_TITLE.get(role, role), "roles": ROLE_TITLE,
                             "shops": shops, "members": members, "plans": PLANS, "can_set_plan": bool(u["is_superadmin"])})


class PlanIn(BaseModel):
    plan: str


@app.put("/api/workspaces/{ws_id}/plan")
def set_plan(ws_id: int, body: PlanIn, u=Depends(current_user), c=Depends(conn)):
    """Пока оплаты нет — тариф переключает только владелец сервиса (суперадмин)."""
    if not u["is_superadmin"]:
        raise HTTPException(403, "Тариф меняется через оплату (скоро)")
    if body.plan not in PLANS:
        raise HTTPException(400, "Нет такого тарифа")
    c.execute("UPDATE workspaces SET plan=%s, plan_changed_at=now() WHERE id=%s", (body.plan, ws_id))
    c.execute("INSERT INTO audit_log(user_id,workspace_id,action,details) VALUES (%s,%s,'workspace/plan',%s)",
              (u["id"], ws_id, json.dumps({"plan": body.plan})))
    c.commit()
    return {"ok": True}


class NameIn(BaseModel):
    name: str


@app.put("/api/workspaces/{ws_id}/name")
def rename_workspace(ws_id: int, body: NameIn, u=Depends(current_user), c=Depends(conn)):
    if not auth.can(auth.workspace_role(c, u, ws_id), "admin"):
        raise HTTPException(403, "Переименовать кабинет может админ или владелец")
    name = body.name.strip()
    if not 1 <= len(name) <= 80:
        raise HTTPException(400, "Название — от 1 до 80 символов")
    c.execute("UPDATE workspaces SET name=%s WHERE id=%s", (name, ws_id))
    c.execute("INSERT INTO audit_log(user_id,workspace_id,action,details) VALUES (%s,%s,'workspace/rename',%s)",
              (u["id"], ws_id, json.dumps({"name": name}, ensure_ascii=False)))
    c.commit()
    return {"ok": True}


class DefaultShopIn(BaseModel):
    shop_id: int | None


@app.put("/api/me/default_shop")
def set_default_shop(body: DefaultShopIn, u=Depends(current_user), c=Depends(conn)):
    if body.shop_id is not None and not auth.shop_role(c, u, body.shop_id):
        raise HTTPException(403, "Нет доступа к магазину")
    c.execute("UPDATE users SET default_shop_id=%s WHERE id=%s", (body.shop_id, u["id"]))
    c.commit()
    return {"ok": True}


@app.put("/api/me/name")
def rename_me(body: NameIn, u=Depends(current_user), c=Depends(conn)):
    name = body.name.strip()
    if len(name) > 80:
        raise HTTPException(400, "Имя — до 80 символов")
    c.execute("UPDATE users SET name=%s WHERE id=%s", (name or None, u["id"]))
    c.commit()
    return {"ok": True}


class GmailIn(BaseModel):
    email: str = ""


@app.put("/api/me/google_email")
def set_google_email(body: GmailIn, u=Depends(current_user), c=Depends(conn)):
    """Почта Google-аккаунта для доступа к выгрузкам в Google Таблицы (пусто — почта входа)."""
    import re
    e = body.email.strip().lower()
    if e and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", e):
        raise HTTPException(400, "Не похоже на почту")
    c.execute("UPDATE users SET google_email=%s WHERE id=%s", (e or None, u["id"]))
    c.commit()
    return {"ok": True}



class ShopIn(BaseModel):
    title: str
    token: str
    marketplace: str = "wb"
    client_id: str | None = None      
    ad_client_id: str | None = None   
    ad_client_secret: str | None = None


def _check_token(token: str) -> dict:
    from . import vault
    inf = vault.info(token)
    if inf.get("error"):
        raise HTTPException(400, inf["error"])
    err = vault.ping(token)
    if err:
        raise HTTPException(400, err)
    return inf


def _start_first_load(name: str) -> bool:
    import subprocess
    try:
        subprocess.run(["systemctl", "--user", "start", "--no-block", f"ai-stometric-onboard@{name}.service"], check=True, timeout=20)
        return True
    except Exception:  
        return False


@app.post("/api/workspaces/{ws_id}/shops")
def add_shop(ws_id: int, body: ShopIn, u=Depends(current_user), c=Depends(conn)):
    """Новый магазин (кабинет WB / юрлицо) в кабинете — админ и выше. Ключ проверяется и хранится зашифрованным."""
    from . import vault
    _admin_of(c, u, ws_id)
    if body.marketplace not in ("wb", "ozon", "ym"):
        raise HTTPException(400, "Маркетплейс: Wildberries, Ozon или Яндекс Маркет")
    title = body.title.strip()
    if not 1 <= len(title) <= 80:
        raise HTTPException(400, "Название магазина — от 1 до 80 символов")
    if body.marketplace == "ozon":
        return _add_ozon(c, u, ws_id, title, body)
    if body.marketplace == "ym":
        return _add_ym(c, u, ws_id, title, body)
    inf = _check_token(body.token)
    oid = inf.get("seller_oid")
    dup = c.execute("SELECT title, archived_at FROM accounts WHERE workspace_id=%s AND seller_oid=%s", (ws_id, oid)).fetchone() if oid else None
    if dup:
        if dup["archived_at"]:
            raise HTTPException(409, f"Магазин «{dup['title']}» удалён в архив. Восстановите его через админку сервиса.")
        raise HTTPException(400, f"Этот кабинет WB уже подключён: «{dup['title']}». Чтобы обновить ключ — «Заменить ключ».")
    name = f"wb{oid}" if oid else f"wb_ws{ws_id}_{int(__import__('time').time())}"
    if c.execute("SELECT 1 FROM accounts WHERE name=%s", (name,)).fetchone():
        name += f"_ws{ws_id}"
    acc = c.execute("INSERT INTO accounts(name,title,token_env,workspace_id,seller_oid,marketplace) VALUES (%s,%s,NULL,%s,%s,'wb') RETURNING id",
                    (name, title, ws_id, oid)).fetchone()
    c.execute("INSERT INTO account_tokens(account_id,enc,info,added_by) VALUES (%s,%s,%s,%s)",
              (acc["id"], vault.encrypt(body.token.strip()), json.dumps(inf, default=str, ensure_ascii=False), u["id"]))
    _audit(c, u, ws_id, "shop/add", {"shop": acc["id"], "title": title, "seller_oid": oid, "exp": str(inf.get("exp"))})
    c.commit()
    started = _start_first_load(name)
    return {"ok": True, "shop_id": acc["id"], "first_load": started}


def _add_ozon(c, u, ws_id: int, title: str, body: ShopIn):
    from . import ozon, vault
    inf = ozon.check(body.client_id or "", body.token)
    if inf.get("error"):
        raise HTTPException(400, inf["error"])
    ad = None
    if (body.ad_client_id or "").strip() or (body.ad_client_secret or "").strip():
        from . import ozon_perf
        ad = ozon_perf.check(body.ad_client_id, body.ad_client_secret)
        if ad.get("error"):
            raise HTTPException(400, "Рекламный ключ: " + ad["error"])
    oid = inf["seller_oid"]
    dup = c.execute("SELECT title, archived_at FROM accounts WHERE workspace_id=%s AND seller_oid=%s AND marketplace='ozon'", (ws_id, oid)).fetchone()
    if dup:
        if dup["archived_at"]:
            raise HTTPException(409, f"Магазин «{dup['title']}» удалён в архив. Восстановите его через админку сервиса.")
        raise HTTPException(400, f"Этот кабинет Ozon уже подключён: «{dup['title']}». Чтобы обновить ключ — «Заменить ключ».")
    name = f"oz{oid}"
    if c.execute("SELECT 1 FROM accounts WHERE name=%s", (name,)).fetchone():
        name += f"_ws{ws_id}"
    acc = c.execute("INSERT INTO accounts(name,title,token_env,workspace_id,seller_oid,marketplace) VALUES (%s,%s,NULL,%s,%s,'ozon') RETURNING id",
                    (name, title, ws_id, oid)).fetchone()
    blob = json.dumps({"client_id": str(oid), "api_key": body.token.strip()})
    c.execute("INSERT INTO account_tokens(account_id,enc,info,added_by) VALUES (%s,%s,%s,%s)",
              (acc["id"], vault.encrypt(blob), json.dumps(inf, default=str, ensure_ascii=False), u["id"]))
    _audit(c, u, ws_id, "shop/add", {"shop": acc["id"], "title": title, "marketplace": "ozon", "client_id": oid, "roles": inf.get("roles")})
    if ad:
        _save_ad_token(c, u, acc["id"], ws_id, body.ad_client_id, body.ad_client_secret, ad)
    c.commit()
    return {"ok": True, "shop_id": acc["id"], "first_load": _start_first_load(name), "roles": inf.get("roles")}


def _add_ym(c, u, ws_id: int, title: str, body: ShopIn):
    from . import vault, ym
    inf = ym.check(body.token)
    if inf.get("error"):
        raise HTTPException(400, inf["error"])
    oid = inf["seller_oid"]
    dup = c.execute("SELECT title, archived_at FROM accounts WHERE workspace_id=%s AND seller_oid=%s AND marketplace='ym'", (ws_id, oid)).fetchone()
    if dup:
        if dup["archived_at"]:
            raise HTTPException(409, f"Магазин «{dup['title']}» удалён в архив. Восстановите его через админку сервиса.")
        raise HTTPException(400, f"Этот кабинет Яндекс Маркета уже подключён: «{dup['title']}». Чтобы обновить ключ — «Заменить ключ».")
    name = f"ym{oid}"
    if c.execute("SELECT 1 FROM accounts WHERE name=%s", (name,)).fetchone():
        name += f"_ws{ws_id}"
    acc = c.execute("INSERT INTO accounts(name,title,token_env,workspace_id,seller_oid,marketplace) VALUES (%s,%s,NULL,%s,%s,'ym') RETURNING id",
                    (name, title, ws_id, oid)).fetchone()
    c.execute("INSERT INTO account_tokens(account_id,enc,info,added_by) VALUES (%s,%s,%s,%s)",
              (acc["id"], vault.encrypt(body.token.strip()), json.dumps(inf, default=str, ensure_ascii=False), u["id"]))
    _audit(c, u, ws_id, "shop/add", {"shop": acc["id"], "title": title, "marketplace": "ym", "business": oid, "scopes": inf.get("scopes")})
    c.commit()
    return {"ok": True, "shop_id": acc["id"], "first_load": _start_first_load(name), "read_only": inf.get("read_only"),
            "campaigns": inf.get("campaigns")}


class TokenIn(BaseModel):
    token: str
    client_id: str | None = None
    provider: str | None = None      
    model: str | None = None


@app.put("/api/shops/{shop_id}/token")
def replace_token(shop_id: int, body: TokenIn, u=Depends(current_user), c=Depends(conn)):
    from . import vault
    acc = c.execute("SELECT * FROM accounts WHERE id=%s", (shop_id,)).fetchone()
    if not acc or not auth.can(auth.shop_role(c, u, shop_id), "admin"):
        raise HTTPException(403, "Менять ключ может админ или владелец кабинета")
    if acc["marketplace"] == "ym":
        from . import ym
        inf = ym.check(body.token)
        if inf.get("error"):
            raise HTTPException(400, inf["error"])
        if acc["seller_oid"] and inf["seller_oid"] != acc["seller_oid"]:
            raise HTTPException(400, "Это ключ от другого кабинета Маркета — для него добавьте отдельный магазин")
        c.execute("""INSERT INTO account_tokens(account_id,enc,info,added_by) VALUES (%s,%s,%s,%s) ON CONFLICT (account_id) DO UPDATE
                     SET enc=EXCLUDED.enc, info=EXCLUDED.info, added_by=EXCLUDED.added_by, added_at=now()""",
                  (shop_id, vault.encrypt(body.token.strip()), json.dumps(inf, default=str, ensure_ascii=False), u["id"]))
        _audit(c, u, acc["workspace_id"], "shop/token", {"shop": shop_id, "marketplace": "ym"})
        c.commit()
        return {"ok": True}
    if acc["marketplace"] == "ozon":
        from . import ozon
        inf = ozon.check(body.client_id or str(acc["seller_oid"] or ""), body.token)
        if inf.get("error"):
            raise HTTPException(400, inf["error"])
        if acc["seller_oid"] and inf["seller_oid"] != acc["seller_oid"]:
            raise HTTPException(400, "Это ключ от другого кабинета Ozon — для него добавьте отдельный магазин")
        blob = json.dumps({"client_id": str(inf["seller_oid"]), "api_key": body.token.strip()})
        c.execute("""INSERT INTO account_tokens(account_id,enc,info,added_by) VALUES (%s,%s,%s,%s) ON CONFLICT (account_id) DO UPDATE
                     SET enc=EXCLUDED.enc, info=EXCLUDED.info, added_by=EXCLUDED.added_by, added_at=now()""",
                  (shop_id, vault.encrypt(blob), json.dumps(inf, default=str, ensure_ascii=False), u["id"]))
        _audit(c, u, acc["workspace_id"], "shop/token", {"shop": shop_id, "marketplace": "ozon"})
        c.commit()
        return {"ok": True}
    inf = _check_token(body.token)
    if acc["seller_oid"] and inf.get("seller_oid") and acc["seller_oid"] != inf["seller_oid"]:
        raise HTTPException(400, "Это ключ от другого кабинета WB — для него добавьте отдельный магазин")
    c.execute("""INSERT INTO account_tokens(account_id,enc,info,added_by) VALUES (%s,%s,%s,%s) ON CONFLICT (account_id) DO UPDATE
                 SET enc=EXCLUDED.enc, info=EXCLUDED.info, added_by=EXCLUDED.added_by, added_at=now()""",
              (shop_id, vault.encrypt(body.token.strip()), json.dumps(inf, default=str, ensure_ascii=False), u["id"]))
    c.execute("UPDATE accounts SET seller_oid=COALESCE(seller_oid,%s) WHERE id=%s", (inf.get("seller_oid"), shop_id))
    _audit(c, u, acc["workspace_id"], "shop/token", {"shop": shop_id, "exp": str(inf.get("exp"))})
    c.commit()
    return {"ok": True}


class AdTokenIn(BaseModel):
    client_id: str
    client_secret: str


def _save_ad_token(c, u, shop_id: int, ws_id: int, client_id: str, client_secret: str, inf: dict):
    from . import vault
    blob = json.dumps({"client_id": client_id.strip(), "client_secret": client_secret.strip()})
    c.execute("""INSERT INTO account_ad_tokens(account_id,enc,info,added_by) VALUES (%s,%s,%s,%s) ON CONFLICT (account_id) DO UPDATE
                 SET enc=EXCLUDED.enc, info=EXCLUDED.info, added_by=EXCLUDED.added_by, added_at=now()""",
              (shop_id, vault.encrypt(blob), json.dumps(inf, default=str, ensure_ascii=False), u["id"]))
    _audit(c, u, ws_id, "shop/ad_token", {"shop": shop_id, "marketplace": "ozon", "campaigns": inf.get("campaigns")})


@app.put("/api/shops/{shop_id}/ad_token")
def replace_ad_token(shop_id: int, body: AdTokenIn, u=Depends(current_user), c=Depends(conn)):
    """Ключ рекламного кабинета Ozon (Performance API): Client ID + Client Secret. Проверяем и храним зашифрованным, отдельно от Seller-ключа."""
    from . import ozon_perf
    acc = c.execute("SELECT * FROM accounts WHERE id=%s", (shop_id,)).fetchone()
    if not acc or not auth.can(auth.shop_role(c, u, shop_id), "admin"):
        raise HTTPException(403, "Менять ключ может админ или владелец кабинета")
    if acc["marketplace"] != "ozon":
        raise HTTPException(400, "Рекламный ключ отдельно нужен только для Ozon")
    inf = ozon_perf.check(body.client_id, body.client_secret)
    if inf.get("error"):
        raise HTTPException(400, inf["error"])
    _save_ad_token(c, u, shop_id, acc["workspace_id"], body.client_id, body.client_secret, inf)
    c.commit()
    return {"ok": True, **inf}



INVITE_DAYS = 7
from .config import site_url
SITE = site_url()


def _admin_of(c, u, ws_id: int) -> str:
    role = auth.workspace_role(c, u, ws_id)
    if not auth.can(role, "admin"):
        raise HTTPException(403, "Управлять доступом может админ или владелец кабинета")
    return role


def _check_grant(c, my_role: str, role: str, shop_ids: list[int] | None, ws_id: int):
    if role not in ("admin", "editor", "viewer"):
        raise HTTPException(400, "Роль: админ, редактор или просмотр")
    if shop_ids is not None:
        if not shop_ids:
            raise HTTPException(400, "Выберите хотя бы один магазин или «все»")
        own = {r["id"] for r in c.execute("SELECT id FROM accounts WHERE workspace_id=%s", (ws_id,))}
        if not set(shop_ids) <= own:
            raise HTTPException(400, "Магазин не из этого кабинета")


def _audit(c, u, ws_id, action, details):
    c.execute("INSERT INTO audit_log(user_id,workspace_id,action,details) VALUES (%s,%s,%s,%s)",
              (u["id"], ws_id, action, json.dumps(details, ensure_ascii=False, default=str)))


class InviteIn(BaseModel):
    email: str
    role: str
    shop_ids: list[int] | None = None


@app.get("/api/workspaces/{ws_id}/invites")
def list_invites(ws_id: int, u=Depends(current_user), c=Depends(conn)):
    _admin_of(c, u, ws_id)
    return jsonable_encoder(c.execute(
        """SELECT left(token_hash,12) id,email,role,shop_ids,expires_at,created_at FROM invites i
           LEFT JOIN LATERAL (SELECT at created_at FROM audit_log a WHERE a.action='invite/create' AND a.details->>'id'=left(i.token_hash,12) LIMIT 1) x ON true
           WHERE workspace_id=%s AND used_at IS NULL AND expires_at>now() ORDER BY expires_at DESC""", (ws_id,)).fetchall())


@app.post("/api/workspaces/{ws_id}/invites")
def create_invite(ws_id: int, body: InviteIn, u=Depends(current_user), c=Depends(conn)):
    my = _admin_of(c, u, ws_id)
    email = body.email.strip().lower()
    if "@" not in email or len(email) > 200:
        raise HTTPException(400, "Нужен e-mail сотрудника — он будет логином")
    _check_grant(c, my, body.role, body.shop_ids, ws_id)
    if c.execute("SELECT 1 FROM memberships m JOIN users x ON x.id=m.user_id WHERE x.email=%s AND m.workspace_id=%s", (email, ws_id)).fetchone():
        raise HTTPException(400, "У этого пользователя уже есть доступ — поменяйте роль в списке")
    tok = __import__("secrets").token_urlsafe(24)
    c.execute("DELETE FROM invites WHERE workspace_id=%s AND email=%s AND used_at IS NULL", (ws_id, email))
    c.execute("INSERT INTO invites(token_hash,workspace_id,email,role,shop_ids,created_by,expires_at) "
              "VALUES (%s,%s,%s,%s,%s,%s, now() + make_interval(days => %s))",
              (auth._h(tok), ws_id, email, body.role, body.shop_ids, u["id"], INVITE_DAYS))
    _audit(c, u, ws_id, "invite/create", {"id": auth._h(tok)[:12], "email": email, "role": body.role, "shop_ids": body.shop_ids})
    c.commit()
    return {"link": f"{SITE}/invite/{tok}", "days": INVITE_DAYS}


@app.delete("/api/workspaces/{ws_id}/invites/{inv_id}")
def revoke_invite(ws_id: int, inv_id: str, u=Depends(current_user), c=Depends(conn)):
    _admin_of(c, u, ws_id)
    n = c.execute("DELETE FROM invites WHERE workspace_id=%s AND left(token_hash,12)=%s AND used_at IS NULL", (ws_id, inv_id)).rowcount
    _audit(c, u, ws_id, "invite/revoke", {"id": inv_id})
    c.commit()
    return {"ok": bool(n)}


class MemberIn(BaseModel):
    role: str
    shop_ids: list[int] | None = None


@app.post("/api/workspaces/{ws_id}/members")
def add_existing_member(ws_id: int, body: InviteIn, u=Depends(current_user), c=Depends(conn)):
    """Connect an existing login to this workspace; never move its shops or copy a plan."""
    _admin_of(c, u, ws_id)
    
    
    actor = c.execute("SELECT role, shop_ids FROM memberships WHERE workspace_id=%s AND user_id=%s FOR SHARE",
                      (ws_id, u["id"])).fetchone()
    if not actor or not auth.can(actor["role"], "admin") or actor["shop_ids"] is not None:
        raise HTTPException(403, "Добавлять пользователей напрямую может владелец или админ всего кабинета")
    email = body.email.strip().lower()
    if "@" not in email or len(email) > 200 or any(x.isspace() for x in email):
        raise HTTPException(400, "Укажите e-mail, с которым пользователь входит в сервис")
    _check_grant(c, actor["role"], body.role, body.shop_ids, ws_id)
    if body.shop_ids is not None:
        available = {r["id"] for r in c.execute(
            "SELECT id FROM accounts WHERE workspace_id=%s AND archived_at IS NULL", (ws_id,))}
        if not set(body.shop_ids) <= available:
            raise HTTPException(400, "Удалённый магазин нельзя выбрать для нового доступа")
    target = c.execute("SELECT id, email, name, is_active FROM users WHERE email=%s FOR SHARE", (email,)).fetchone()
    if not target:
        raise HTTPException(404, "Пользователь с этой почтой ещё не зарегистрирован. Создайте приглашение по ссылке.")
    if not target["is_active"]:
        raise HTTPException(409, "Пользователь заблокирован. Сначала проверьте его статус в админке.")
    added = c.execute("""INSERT INTO memberships(user_id,workspace_id,role,shop_ids) VALUES (%s,%s,%s,%s)
                         ON CONFLICT (user_id,workspace_id) DO NOTHING RETURNING user_id""",
                      (target["id"], ws_id, body.role, body.shop_ids)).fetchone()
    if not added:
        raise HTTPException(409, "Пользователь уже в этом кабинете. Измените его доступ в списке участников.")
    c.execute("UPDATE invites SET used_at=now() WHERE workspace_id=%s AND email=%s AND used_at IS NULL", (ws_id, email))
    _audit(c, u, ws_id, "member/add_existing", {"user_id": target["id"], "role": body.role, "shop_ids": body.shop_ids})
    c.commit()
    return {"ok": True, "user_id": target["id"], "email": target["email"], "workspace_id": ws_id}


def _target(c, ws_id: int, user_id: int) -> dict:
    m = c.execute("SELECT * FROM memberships WHERE workspace_id=%s AND user_id=%s", (ws_id, user_id)).fetchone()
    if not m:
        raise HTTPException(404, "Нет такого пользователя в кабинете")
    if m["role"] == "owner":
        raise HTTPException(403, "Доступ владельца не меняется")
    return m


@app.put("/api/workspaces/{ws_id}/members/{user_id}")
def update_member(ws_id: int, user_id: int, body: MemberIn, u=Depends(current_user), c=Depends(conn)):
    my = _admin_of(c, u, ws_id)
    _target(c, ws_id, user_id)
    _check_grant(c, my, body.role, body.shop_ids, ws_id)
    c.execute("UPDATE memberships SET role=%s, shop_ids=%s WHERE workspace_id=%s AND user_id=%s", (body.role, body.shop_ids, ws_id, user_id))
    _audit(c, u, ws_id, "member/update", {"user_id": user_id, "role": body.role, "shop_ids": body.shop_ids})
    c.commit()
    return {"ok": True}


@app.delete("/api/workspaces/{ws_id}/members/{user_id}")
def remove_member(ws_id: int, user_id: int, u=Depends(current_user), c=Depends(conn)):
    """Забрать доступ к кабинету (сам пользователь и его данные остаются; можно пригласить снова)."""
    _admin_of(c, u, ws_id)
    _target(c, ws_id, user_id)
    c.execute("DELETE FROM memberships WHERE workspace_id=%s AND user_id=%s", (ws_id, user_id))
    _audit(c, u, ws_id, "member/remove", {"user_id": user_id})
    c.commit()
    return {"ok": True}


def _invite(c, tok: str) -> dict:
    inv = c.execute("""SELECT i.*, w.name ws_name FROM invites i JOIN workspaces w ON w.id=i.workspace_id
                       WHERE token_hash=%s AND used_at IS NULL AND expires_at>now()""", (auth._h(tok),)).fetchone()
    if not inv:
        raise HTTPException(404, "Приглашение не найдено, использовано или истекло — попросите новое")
    return inv


@app.get("/api/invites/{tok}")
def invite_info(tok: str, c=Depends(conn)):
    inv = _invite(c, tok)
    user = c.execute("SELECT 1 FROM users WHERE email=%s", (inv["email"],)).fetchone()
    return {"email": inv["email"], "workspace": inv["ws_name"], "role": ROLE_TITLE[inv["role"]], "has_account": bool(user)}


class AcceptIn(BaseModel):
    password: str
    name: str | None = None


@app.post("/api/invites/{tok}/accept")
def invite_accept(tok: str, body: AcceptIn, request: Request, response: Response, c=Depends(conn)):
    inv = _invite(c, tok)
    _throttle(request, inv["email"])
    user = c.execute("SELECT * FROM users WHERE email=%s", (inv["email"],)).fetchone()
    if user and user["password_hash"]:
        if not auth.check_password(body.password, user["password_hash"]):
            _failed(request, inv["email"])
            raise HTTPException(401, "Неверный пароль от вашего аккаунта")
        uid = user["id"]
    elif user:   
        raise HTTPException(409, "Аккаунт с этой почтой уже есть, но пароль ещё не задан — задайте его по ссылке из бота регистрации "
                                 "(/start), войдите и откройте приглашение снова")
    else:
        if len(body.password) < 10:
            raise HTTPException(400, "Пароль — не короче 10 символов")
        r = c.execute("""INSERT INTO users(email,name,password_hash) VALUES (%s,%s,%s) ON CONFLICT (email) DO NOTHING RETURNING id""",
                      (inv["email"], (body.name or "").strip() or None, auth.hash_password(body.password))).fetchone()
        if not r:
            raise HTTPException(409, "Аккаунт с этой почтой уже есть — войдите и откройте приглашение снова")
        uid = r["id"]
    
    added = c.execute("""INSERT INTO memberships(user_id,workspace_id,role,shop_ids) VALUES (%s,%s,%s,%s)
                         ON CONFLICT (user_id,workspace_id) DO NOTHING RETURNING user_id""",
                      (uid, inv["workspace_id"], inv["role"], inv["shop_ids"])).fetchone()
    c.execute("UPDATE invites SET used_at=now() WHERE token_hash=%s", (inv["token_hash"],))
    c.execute("INSERT INTO audit_log(user_id,workspace_id,action,details) VALUES (%s,%s,'invite/accept',%s)",
              (uid, inv["workspace_id"], json.dumps({"id": inv["token_hash"][:12], "role": inv["role"] if added else None,
                                                     "membership_created": bool(added)})))
    c.commit()
    s_tok = auth.new_session(c, uid, request.client.host if request.client else None, request.headers.get("user-agent"))
    response.set_cookie(COOKIE, s_tok, max_age=auth.SESSION_DAYS * 86400, httponly=True, secure=True, samesite="lax")
    return {"ok": True}



def _magic(c, tok: str) -> dict:
    r = c.execute("""SELECT t.*, u.email FROM login_tokens t JOIN users u ON u.id=t.user_id
                     WHERE token_hash=%s AND used_at IS NULL AND expires_at>now() AND u.is_active""",
                  (__import__("hashlib").sha256(tok.encode()).hexdigest(),)).fetchone()
    if not r:
        raise HTTPException(404, "Ссылка устарела или уже использована — запросите новую в боте регистрации (/start)")
    return r


@app.get("/api/auth/magic/{tok}")
def magic_info(tok: str, c=Depends(conn)):
    r = _magic(c, tok)
    return {"email": r["email"], "purpose": r["purpose"]}


class MagicIn(BaseModel):
    password: str | None = None


@app.post("/api/auth/magic/{tok}")
def magic_use(tok: str, body: MagicIn, request: Request, response: Response, c=Depends(conn)):
    r = _magic(c, tok)
    if r["purpose"] == "set_password":
        if not body.password or len(body.password) < 10:
            raise HTTPException(400, "Пароль — не короче 10 символов")
        c.execute("UPDATE users SET password_hash=%s WHERE id=%s", (auth.hash_password(body.password), r["user_id"]))
        c.execute("DELETE FROM sessions WHERE user_id=%s", (r["user_id"],))      
    c.execute("UPDATE login_tokens SET used_at=now() WHERE token_hash=%s", (r["token_hash"],))
    c.execute("INSERT INTO audit_log(user_id,action,details) VALUES (%s,%s,'{}')", (r["user_id"], "auth/magic:" + r["purpose"]))
    c.commit()
    s_tok = auth.new_session(c, r["user_id"], request.client.host if request.client else None, request.headers.get("user-agent"))
    response.set_cookie(COOKIE, s_tok, max_age=auth.SESSION_DAYS * 86400, httponly=True, secure=True, samesite="lax")
    return {"ok": True}


_BOT_NAME: dict = {}


def _notify_bot_username() -> str | None:
    if "n" not in _BOT_NAME:
        from .bots import Bot
        try:
            _BOT_NAME["n"] = Bot("TG_BOT_NOTIFY_TOKEN").username
        except Exception:  
            return None
    return _BOT_NAME["n"]


@app.get("/api/me/notify")
def notify_get(u=Depends(current_user), c=Depends(conn)):
    c.execute("INSERT INTO notify_settings(user_id) VALUES (%s) ON CONFLICT DO NOTHING", (u["id"],))
    s = c.execute("SELECT * FROM notify_settings WHERE user_id=%s", (u["id"],)).fetchone()
    code = __import__("secrets").token_urlsafe(12)
    c.execute("INSERT INTO tg_link_codes(code,user_id,expires_at) VALUES (%s,%s, now() + interval '30 minutes')", (code, u["id"]))
    c.commit()
    from .bots import assistant_username
    asb = assistant_username(c)
    bot = asb or _notify_bot_username()      
    
    on = s["chat_id"] is not None and (not asb or (s["bot"] == "assistant" and u.get("telegram_id") == s["chat_id"]))
    from .news import KINDS
    return {"connected": on, "old_bot": s["chat_id"] is not None and not on, "assistant": bool(asb),
            "daily": s["daily"], "daily_time": s["daily_time"].strftime("%H:%M"), "alerts": s["alerts"], "ai": s["ai"],
            "daily_mine": s["daily_mine"],
            "shops": [{"id": x["id"], "title": x["title"] or x["name"], "mp": x["marketplace"], "workspace": x["workspace"],
                       "on": x["id"] not in (s["muted_shops"] or [])} for x in auth.shops_for(c, u)], "is_staff": bool(c.execute("SELECT 1 FROM staff WHERE user_id=%s", (u["id"],)).fetchone()),
            "send_from": s["send_from"].strftime("%H:%M"), "send_to": s["send_to"].strftime("%H:%M"),
            "kinds": [{"key": k, "title": tt, "on": (s["kinds"] or {}).get(k) is not False} for k, tt, _ in KINDS],
            "bot": bot, "link": f"https://t.me/{bot}?start={code}" if bot else None}


class NotifyIn(BaseModel):
    daily: bool
    daily_time: str
    alerts: bool
    ai: bool = True
    kinds: dict[str, bool] | None = None
    send_from: str | None = None       
    send_to: str | None = None
    daily_mine: bool | None = None     
    muted_shops: list[int] | None = None   


@app.put("/api/me/notify")
def notify_put(body: NotifyIn, u=Depends(current_user), c=Depends(conn)):
    if not __import__("re").match(r"^([01]\d|2[0-3]):[0-5]\d$", body.daily_time):
        raise HTTPException(400, "Время — ЧЧ:ММ")
    c.execute("""INSERT INTO notify_settings(user_id,daily,daily_time,alerts,ai) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (user_id)
                 DO UPDATE SET daily=EXCLUDED.daily, daily_time=EXCLUDED.daily_time, alerts=EXCLUDED.alerts, ai=EXCLUDED.ai, updated_at=now()""",
              (u["id"], body.daily, body.daily_time, body.alerts, body.ai))
    if body.send_from is not None and body.send_to is not None:
        if not all(__import__("re").match(r"^([01]\d|2[0-3]):[0-5]\d$", x) for x in (body.send_from, body.send_to)):
            raise HTTPException(400, "Время — ЧЧ:ММ")
        c.execute("UPDATE notify_settings SET send_from=%s, send_to=%s WHERE user_id=%s", (body.send_from, body.send_to, u["id"]))
    if body.muted_shops is not None:
        mine_ids = {x["id"] for x in auth.shops_for(c, u)}
        c.execute("UPDATE notify_settings SET muted_shops=%s WHERE user_id=%s", (sorted(set(body.muted_shops) & mine_ids), u["id"]))
    if body.daily_mine is not None:
        c.execute("UPDATE notify_settings SET daily_mine=%s WHERE user_id=%s", (body.daily_mine, u["id"]))
    if body.kinds is not None:
        from .news import KIND_KEYS
        c.execute("UPDATE notify_settings SET kinds = kinds || %s::jsonb WHERE user_id=%s",
                  (json.dumps({k: bool(v) for k, v in body.kinds.items() if k in KIND_KEYS}), u["id"]))
    c.commit()
    return {"ok": True}


@app.post("/api/me/notify/test")
def notify_test(u=Depends(current_user), c=Depends(conn)):
    from .bots import send_daily
    s = c.execute("SELECT chat_id FROM notify_settings WHERE user_id=%s", (u["id"],)).fetchone()
    if not s or not s["chat_id"]:
        raise HTTPException(400, "Сначала подключите Telegram")
    return {"ok": send_daily(c, u["id"], s["chat_id"], force=True)}


@app.get("/api/shops/{shop_id}/tab/{key}")
def tab(shop_id: int, key: str, date_from: date | None = None, date_to: date | None = None, nm_ids: str | None = None, group: str | None = None,
        p1_from: date | None = None, p1_to: date | None = None, per_unit: bool = False, campaign: int | None = None,
        limit: int = 0, offset: int = 0, sort: str | None = None, desc: bool = False, staff: int | None = None,
        u=Depends(current_user), c=Depends(conn)):
    if not auth.can(auth.shop_role(c, u, shop_id), "viewer"):
        raise HTTPException(403, "Нет доступа к магазину")
    if key not in BY_KEY:
        raise HTTPException(404, "Нет такой вкладки")
    dt = date_to or today_msk()
    f = {"date_from": date_from or dt - timedelta(days=29), "date_to": dt,
         "nm_ids": [int(x) for x in nm_ids.split(",") if x.strip().isdigit()] if nm_ids else None, "group": group}
    if staff:                                   
        from . import staff as _staff
        f["nm_ids"] = _staff.narrow(c, shop_id, staff, f["nm_ids"])
    if p1_from and p1_to:                       
        f["p1_from"], f["p1_to"] = p1_from, p1_to
    if per_unit:                                
        f["per_unit"] = True
    if campaign:                                
        f["campaign"] = campaign
    f["user_id"] = u["id"]
    import psycopg
    from .materialize import NotReady
    try:
        res = _cached(c, key, shop_id, f)
    except (NotReady, psycopg.errors.QueryCanceled) as e:     
        c.rollback()
        msg = str(e) if isinstance(e, NotReady) else ("В связи с большим объёмом артикулов данные на этой вкладке появятся позже: "
                                                     "расчёт не уложился в минуту. Попробуйте позже или выберите меньший период / артикулы.")
        res = {"columns": [{"field": "msg", "title": "Данные готовятся", "type": "text"}], "rows": [{"msg": msg}], "plain": True, "note": msg}
    f.pop("user_id", None)
    from .exclusions import excluded
    ex = excluded(c, shop_id)
    if ex and res.get("rows") and isinstance(res["rows"][0], dict) and "nm_id" in res["rows"][0]:   
        res = {**res, "rows": [r for r in res["rows"] if r.get("nm_id") not in ex]}
    res = _page(res, limit, offset, sort, desc)
    return JSONResponse(jsonable_encoder({"key": key, "title": BY_KEY[key][1], "filters": {k: str(v) if v else None for k, v in f.items()},
                         **res}), headers={"Cache-Control": "no-store"})


@app.get("/api/shops/{shop_id}/tab/{key}/xlsx")
def tab_xlsx(shop_id: int, key: str, date_from: date | None = None, date_to: date | None = None, nm_ids: str | None = None, group: str | None = None,
             p1_from: date | None = None, p1_to: date | None = None, per_unit: bool = False, campaign: int | None = None,
             sort: str | None = None, desc: bool = False, staff: int | None = None, cols: str | None = None,
             u=Depends(current_user), c=Depends(conn)):
    """Self-hosted application component."""
    from urllib.parse import quote
    body, name = _xlsx(shop_id, key, date_from, date_to, nm_ids, group, p1_from, p1_to, per_unit, campaign, sort, desc, staff, cols, u, c)
    return Response(body, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename=\"export.xlsx\"; filename*=UTF-8''{quote(name)}",
                             "Cache-Control": "no-store"})


def _xlsx(shop_id, key, date_from, date_to, nm_ids, group, p1_from, p1_to, per_unit, campaign, sort, desc, staff, cols, u, c) -> tuple[bytes, str]:
    from . import export
    r = tab(shop_id, key, date_from, date_to, nm_ids, group, p1_from, p1_to, per_unit, campaign, -1, 0, sort, desc, staff, u=u, c=c)
    res = json.loads(r.body)
    if res.get("custom") or not res.get("columns"):
        raise HTTPException(400, "Эту вкладку выгрузить пока нельзя — это не таблица")
    acc = c.execute("SELECT coalesce(title, name) t FROM accounts WHERE id=%s", (shop_id,)).fetchone()
    dt = date_to or today_msk()
    name = export.filename(acc["t"] if acc else str(shop_id), res["title"], date_from or dt - timedelta(days=29), dt)
    return export.build(res, [x for x in (cols or "").split(",") if x], res["title"]), name


def _gsheet_ready(c) -> bool:
    from . import gdrive
    try:
        return gdrive.ready(c)
    except Exception:  
        return False


@app.post("/api/shops/{shop_id}/tab/{key}/gsheet")
def tab_gsheet(shop_id: int, key: str, date_from: date | None = None, date_to: date | None = None, nm_ids: str | None = None, group: str | None = None,
               p1_from: date | None = None, p1_to: date | None = None, per_unit: bool = False, campaign: int | None = None,
               sort: str | None = None, desc: bool = False, staff: int | None = None, cols: str | None = None,
               u=Depends(current_user), c=Depends(conn)):
    """Вкладка → новая Google Таблица в папке выгрузок (Диск владельца сервиса), доступ — на почту пользователя."""
    from . import gdrive
    if not gdrive.ready(c):
        raise HTTPException(400, "Выгрузка в Google Таблицы ещё не подключена")
    body, name = _xlsx(shop_id, key, date_from, date_to, nm_ids, group, p1_from, p1_to, per_unit, campaign, sort, desc, staff, cols, u, c)
    from datetime import datetime
    from zoneinfo import ZoneInfo
    try:
        out = gdrive.upload(c, body, name[:-5] + f" · {datetime.now(ZoneInfo('Europe/Moscow')):%H:%M}", u.get("google_email") or u["email"])
    except gdrive.GError as e:
        raise HTTPException(502, str(e)) from None
    ws = c.execute("SELECT workspace_id FROM accounts WHERE id=%s", (shop_id,)).fetchone()
    _audit(c, u, ws and ws["workspace_id"], "export/gsheet", {"shop": shop_id, "tab": key, "url": out["url"]})
    c.commit()
    return out


PAGE_FROM = 300      
PAGE = 100


def _page(res: dict, limit: int, offset: int, sort: str | None, desc: bool) -> dict:
    """Большая таблица: сортировка по всем строкам на сервере, отдаём страницу; ИТОГО — по всем строкам (суммы ₽ и штук)."""
    rows = res.get("rows") or []
    if res.get("layout") == "sheet" or res.get("editable") or not rows or not isinstance(rows[0], dict) or (len(rows) <= PAGE_FROM and not limit):
        return res
    if sort and sort in rows[0]:
        num = all(isinstance(r.get(sort), (int, float)) or r.get(sort) is None for r in rows[:200])
        key = (lambda r: (r.get(sort) is None, -(r[sort] or 0) if desc else (r[sort] or 0))) if num else\
              (lambda r: (r.get(sort) is None, str(r.get(sort) or "")))
        rows = sorted(rows, key=key)
        if desc and not num:
            rows = [r for r in rows if r.get(sort) is not None][::-1] + [r for r in rows if r.get(sort) is None]
    n = len(rows)
    lim = n if limit < 0 else (limit or PAGE)
    out = {**res, "rows": rows[offset:offset + lim], "rows_total": n, "offset": offset, "limit": lim}
    if not res.get("total_row") and not res.get("plain"):
        t: dict = {}
        cols = res.get("columns") or []
        first = next((c for c in cols if c.get("type") in ("text", "label")), None)
        for c in cols:
            if c.get("type") in ("int", "money") and not c["field"].endswith("_id") and c["field"] != "nm_id":
                t[c["field"]] = sum(float(r.get(c["field"]) or 0) for r in rows if isinstance(r.get(c["field"]), (int, float)))
        if first:
            t[first["field"]] = "ИТОГО"
        out["total_row"] = t
    return out


class CheckIn(BaseModel):
    day: date
    sku: int
    field: str
    value: str | None = None


@app.put("/api/shops/{shop_id}/checklist")
def set_check(shop_id: int, body: CheckIn, u=Depends(current_user), c=Depends(conn)):
    """Чек-лист Ozon (Version2): ячейка «день × артикул × поле» — редактор кабинета и выше."""
    from .tabs.ozon import CHECK_FIELDS
    if not auth.can(auth.shop_role(c, u, shop_id), "editor"):
        raise HTTPException(403, "Править чек-лист может редактор кабинета и выше")
    if body.field not in dict(CHECK_FIELDS):
        raise HTTPException(400, "Нет такого поля")
    v = (body.value or "").strip()[:1000]
    if v:
        c.execute("""INSERT INTO oz_checklist(account_id,day,sku,field,value,updated_by) VALUES (%s,%s,%s,%s,%s,%s)
                     ON CONFLICT (account_id,day,sku,field) DO UPDATE SET value=EXCLUDED.value, updated_by=EXCLUDED.updated_by, updated_at=now()""",
                  (shop_id, body.day, body.sku, body.field, v, u["id"]))
    else:
        c.execute("DELETE FROM oz_checklist WHERE account_id=%s AND day=%s AND sku=%s AND field=%s", (shop_id, body.day, body.sku, body.field))
    _audit(c, u, None, "checklist", {"shop": shop_id, "day": str(body.day), "sku": body.sku, "field": body.field})
    c.commit()
    return {"ok": True}


class PrefIn(BaseModel):
    value: list | dict | None


@app.put("/api/shops/{shop_id}/prefs/{key}")
def set_pref(shop_id: int, key: str, body: PrefIn, u=Depends(current_user), c=Depends(conn)):
    """Личные настройки вида (раскладка колонок и т.п.); value=null — сбросить к стандартной."""
    if not auth.can(auth.shop_role(c, u, shop_id), "viewer"):
        raise HTTPException(403, "Нет доступа к магазину")
    if key not in ("svodwb_layout", "pnl_ads"):
        raise HTTPException(400, "Неизвестная настройка")
    if body.value is None:
        c.execute("DELETE FROM user_prefs WHERE user_id=%s AND shop_id=%s AND key=%s", (u["id"], shop_id, key))
    else:
        c.execute("""INSERT INTO user_prefs(user_id,shop_id,key,value) VALUES (%s,%s,%s,%s)
                     ON CONFLICT (user_id,shop_id,key) DO UPDATE SET value=EXCLUDED.value, updated_at=now()""",
                  (u["id"], shop_id, key, json.dumps(body.value, ensure_ascii=False)))
    c.commit()
    return {"ok": True}


class TaxIn(BaseModel):
    regime: str
    rate: float
    vat_rate: float = 0
    vat_deduct_wb: float = 0
    cost_vat: bool = False
    valid_from: date | None = None


@app.put("/api/shops/{shop_id}/tax")
def set_tax(shop_id: int, body: TaxIn, u=Depends(current_user), c=Depends(conn)):
    """Система налогообложения — админ кабинета и выше; новая запись с датой действия (по умолчанию 1-е число месяца)."""
    from .tabs.basic import TAX_REGIMES
    if not auth.can(auth.shop_role(c, u, shop_id), "admin"):
        raise HTTPException(403, "Менять СНО может админ кабинета или владелец")
    if body.regime not in TAX_REGIMES or not (0 <= body.rate <= 0.5) or not (0 <= body.vat_rate <= 0.3) or not (0 <= body.vat_deduct_wb <= 0.3):
        raise HTTPException(400, "Проверьте значения: ставки — доли (8 % = 0.08)")
    vf = body.valid_from or today_msk().replace(day=1)
    c.execute("""INSERT INTO tax_settings(account_id,valid_from,regime,rate,vat_rate,vat_deduct_wb,cost_vat) VALUES (%s,%s,%s,%s,%s,%s,%s)
                 ON CONFLICT (account_id,valid_from) DO UPDATE SET regime=EXCLUDED.regime, rate=EXCLUDED.rate,
                 vat_rate=EXCLUDED.vat_rate, vat_deduct_wb=EXCLUDED.vat_deduct_wb, cost_vat=EXCLUDED.cost_vat""",
              (shop_id, vf, body.regime, body.rate, body.vat_rate, body.vat_deduct_wb, body.cost_vat))
    c.execute("INSERT INTO audit_log(user_id,workspace_id,action,details) SELECT %s, workspace_id, 'tax', %s FROM accounts WHERE id=%s",
              (u["id"], json.dumps({"shop": shop_id, **body.model_dump(mode="json"), "valid_from": str(vf)}, ensure_ascii=False), shop_id))
    from .materialize import mark_cost_dirty
    
    
    mark_cost_dirty(c, shop_id, date(2000, 1, 1))
    c.commit()
    return {"ok": True}


@app.get("/api/shops/{shop_id}/articles")
def articles(shop_id: int, u=Depends(current_user), c=Depends(conn)):
    """Справочник артикулов магазина для выпадающего списка: фото-миниатюра, артикул продавца, название, заказы за 30 дней
    (по ним сортируем — ходовые сверху)."""
    if not auth.can(auth.shop_role(c, u, shop_id), "viewer"):
        raise HTTPException(403, "Нет доступа к магазину")
    mp = c.execute("SELECT marketplace FROM accounts WHERE id=%s", (shop_id,)).fetchone()["marketplace"]
    if mp == "ym":
        return c.execute(
            """SELECT p.market_sku nm_id, p.offer_id vendor_code, p.name title, p.category subject, p.photo, coalesce(o.n, 0) orders_30d, g.group_name grp
               FROM ym_offers p LEFT JOIN (SELECT coalesce(i.market_sku, f.market_sku) sku, sum(i.initial_qty) n FROM ym_order_items i
                                           JOIN ym_orders o ON o.account_id=i.account_id AND o.order_id=i.order_id
                                           LEFT JOIN ym_offers f ON f.account_id=i.account_id AND f.offer_id=i.offer_id
                                           WHERE i.account_id=%s AND o.order_day >= current_date - 30 GROUP BY 1) o ON o.sku=p.market_sku
               LEFT JOIN article_groups g ON g.account_id=p.account_id AND g.nm_id=p.market_sku
               WHERE p.account_id=%s AND p.market_sku IS NOT NULL ORDER BY coalesce(o.n, 0) DESC, p.offer_id""", (shop_id, shop_id)).fetchall()
    if mp == "ozon":
        return c.execute(
            """SELECT p.sku nm_id, p.offer_id vendor_code, p.name title, t.type_name subject, p.photo, coalesce(o.n, 0) orders_30d, g.group_name grp
               FROM oz_products p LEFT JOIN (SELECT sku, sum(qty) n FROM oz_postings WHERE account_id=%s AND order_day >= current_date - 30
                                             GROUP BY 1) o ON o.sku=p.sku
               LEFT JOIN oz_types t ON t.type_id=p.type_id LEFT JOIN article_groups g ON g.account_id=p.account_id AND g.nm_id=p.sku
               WHERE p.account_id=%s AND p.sku IS NOT NULL ORDER BY coalesce(o.n, 0) DESC, p.offer_id""", (shop_id, shop_id)).fetchall()
    from .exclusions import excluded
    ex = excluded(c, shop_id)
    return [r for r in c.execute(
        """SELECT n.nm_id, n.vendor_code, n.title, n.subject, n.data->'photos'->0->>'tm' AS photo, coalesce(o.n, 0) orders_30d, g.group_name grp
           FROM nomenclature n LEFT JOIN (SELECT nm_id, count(*) n FROM orders WHERE account_id=%s AND order_dt >= now() - interval '30 days'
                                          GROUP BY 1) o ON o.nm_id=n.nm_id
           LEFT JOIN article_groups g ON g.account_id=n.account_id AND g.nm_id=n.nm_id
           WHERE n.account_id=%s ORDER BY coalesce(o.n, 0) DESC, n.vendor_code""", (shop_id, shop_id)).fetchall() if r["nm_id"] not in ex]


@app.get("/api/shops/{shop_id}/groups")
def groups(shop_id: int, u=Depends(current_user), c=Depends(conn)):
    if not auth.can(auth.shop_role(c, u, shop_id), "viewer"):
        raise HTTPException(403, "Нет доступа к магазину")
    from .tabs.basic import card_groups
    own = [{"key": r["group_name"], "title": r["group_name"], "kind": "own"}
           for r in c.execute("SELECT DISTINCT group_name FROM article_groups WHERE account_id=%s ORDER BY 1", (shop_id,))]
    mp = c.execute("SELECT marketplace FROM accounts WHERE id=%s", (shop_id,)).fetchone()["marketplace"]
    if mp == "ym":
        return own
    if mp == "ozon":
        models = c.execute("""SELECT model_id, count(*) n, min(offer_id) vc, max(name) title FROM oz_products
                              WHERE account_id=%s AND model_id IS NOT NULL AND sku IS NOT NULL AND NOT archived
                              GROUP BY 1 HAVING count(*) > 1 ORDER BY count(*) DESC""", (shop_id,)).fetchall()
        return own + [{"key": f"model:{r['model_id']}", "title": f"{(r['title'] or '')[:50]} · {r['n']} SKU ({r['vc']})", "kind": "card"}
                      for r in models]
    cards = [{"key": r["key"], "title": f"{(r['title'] or '')[:50]} · {r['n']} арт. ({r['vc']})", "kind": "card"} for r in card_groups(c, shop_id)]
    return own + cards


class GroupIn(BaseModel):
    nm_id: int
    group_name: str | None


@app.put("/api/shops/{shop_id}/group")
def set_group(shop_id: int, body: GroupIn, u=Depends(current_user), c=Depends(conn)):
    if not auth.can(auth.shop_role(c, u, shop_id), "editor"):
        raise HTTPException(403, "Менять группы может редактор или выше")
    g = (body.group_name or "").strip()[:100]
    if g:
        c.execute("""INSERT INTO article_groups(account_id,nm_id,group_name) VALUES (%s,%s,%s)
                     ON CONFLICT (account_id,nm_id) DO UPDATE SET group_name=EXCLUDED.group_name""", (shop_id, body.nm_id, g))
    else:
        c.execute("DELETE FROM article_groups WHERE account_id=%s AND nm_id=%s", (shop_id, body.nm_id))
    c.execute("INSERT INTO audit_log(user_id,workspace_id,action,details) SELECT %s, workspace_id, 'group', %s FROM accounts WHERE id=%s",
              (u["id"], json.dumps({"shop": shop_id, "nm_id": body.nm_id, "group": g}, ensure_ascii=False), shop_id))
    c.commit()
    return {"ok": True}


class CostIn(BaseModel):
    nm_id: int
    cost: float
    valid_from: date | None = None


@app.put("/api/shops/{shop_id}/cost")
def set_cost(shop_id: int, body: CostIn, u=Depends(current_user), c=Depends(conn)):
    """Себестоимость — роль «редактор» и выше. Новая запись с датой действия (по умолчанию сегодня), прошлое не трогаем."""
    if not auth.can(auth.shop_role(c, u, shop_id), "editor"):
        raise HTTPException(403, "Менять себестоимость может редактор или выше")
    if body.cost < 0 or body.cost > 10_000_000:
        raise HTTPException(400, "Странная себестоимость")
    vf = body.valid_from or today_msk()
    if not c.execute("SELECT 1 FROM cost_price WHERE account_id=%s AND nm_id=%s", (shop_id, body.nm_id)).fetchone():
        vf = date(2000, 1, 1)          
    c.execute("""INSERT INTO cost_price(account_id,nm_id,valid_from,cost,note) VALUES (%s,%s,%s,%s,%s)
                 ON CONFLICT (account_id,nm_id,valid_from) DO UPDATE SET cost=EXCLUDED.cost, note=EXCLUDED.note""",
              (shop_id, body.nm_id, vf, body.cost, f"вручную: {u['email']}"))
    c.execute("INSERT INTO audit_log(user_id,workspace_id,action,details) SELECT %s, workspace_id, 'cost', %s FROM accounts WHERE id=%s",
              (u["id"], json.dumps({"shop": shop_id, "nm_id": body.nm_id, "cost": body.cost, "valid_from": str(vf)}), shop_id))
    from .materialize import mark_cost_dirty
    mark_cost_dirty(c, shop_id, vf)
    c.commit()
    return {"ok": True}


def _cached(c, key, shop_id, f):
    """Готовый расчёт вкладки из общего кэша (tabcache): свежий — сразу; данные обновились — прошлый сразу + пересчёт фоном."""
    from . import tabcache
    return tabcache.get(c, shop_id, key, tabcache.tab_params(c, key, shop_id, f), lambda cc: BY_KEY[key][3](cc, shop_id, f))


@app.get("/api/shops/{shop_id}/news")
def news_feed(shop_id: int, kind: str | None = None, nm_id: int | None = None, before: int | None = None, u=Depends(current_user), c=Depends(conn)):
    if not auth.can(auth.shop_role(c, u, shop_id), "viewer"):
        raise HTTPException(403, "Нет доступа к магазину")
    from . import news
    return jsonable_encoder(news.feed(c, shop_id, kind or None, nm_id, before))


@app.get("/api/health")
def health(c=Depends(conn)):
    c.execute("SELECT 1")
    return {"ok": True}


from . import api_actions, api_ads, api_assistant, api_billing, api_cards, api_compare, api_kb, api_manager, api_questions, api_rnp, api_seo, api_service_news, api_staff, api_total, api_visual, api_mcp, api_plugin, api_ai_tasks  

app.include_router(api_manager.router)
app.include_router(api_plugin.router)
app.include_router(api_rnp.router)
app.include_router(api_compare.router)
app.include_router(api_assistant.router)
app.include_router(api_billing.router)
app.include_router(api_actions.router)
app.include_router(api_questions.router)
app.include_router(api_ads.router)
app.include_router(api_total.router)
app.include_router(api_kb.router)
app.include_router(api_visual.router)
app.include_router(api_staff.router)
app.include_router(api_cards.router)
app.include_router(api_seo.router)
app.include_router(api_service_news.router)
app.include_router(api_mcp.router)
app.include_router(api_ai_tasks.router)
from . import api_calendar  
app.include_router(api_calendar.router)

if DIST.exists():
    class _Assets(StaticFiles):
        """Файлы сборки с хэшем в имени — браузер хранит год и не качает заново при каждом открытии."""
        async def get_response(self, path, scope):
            r = await super().get_response(path, scope)
            if r.status_code == 200:
                r.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return r

    app.mount("/assets", _Assets(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = (DIST / path).resolve()
        ok = path and f.is_file() and f.is_relative_to(DIST.resolve())
        return FileResponse(f if ok else DIST / "index.html")
