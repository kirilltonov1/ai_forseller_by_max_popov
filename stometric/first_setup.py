"""One-time, owner-authorized browser bootstrap for a new private deployment."""
import hmac
import html
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from . import auth, db

class SetupInput(BaseModel):
    code: str
    email: str
    password: str

def register_first_setup(app: FastAPI):
    @app.get("/first-setup", response_class=HTMLResponse)
    def setup_page():
        with db.connect() as c:
            complete = bool(c.execute("SELECT 1 FROM users LIMIT 1").fetchone())
        if complete:
            return HTMLResponse('<html lang="ru"><meta charset="utf-8"><p>Администратор уже создан. <a href="/">Перейти ко входу</a>.</p></html>')
        return HTMLResponse("""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Первый вход — Seller Analytics</title>
<style>
*{box-sizing:border-box}body{background:#0d1016;color:#eef1f8;font:16px system-ui;display:grid;place-items:center;min-height:100vh;margin:0}
main{background:#181d27;border:1px solid #343b4a;border-radius:16px;padding:28px;width:min(440px,92vw)}
h1{font-size:24px;margin:0 0 8px}p{color:#b6bfce;line-height:1.4}
label{display:block;margin-top:16px}input{display:block;width:100%;margin-top:7px;padding:13px;border:1px solid #51596b;border-radius:8px;background:#202633;color:#fff;font:inherit}
button{background:#9c7ceb;color:white;width:100%;padding:13px;margin-top:20px;border:0;border-radius:8px;font:inherit;cursor:pointer}
#error{min-height:20px;color:#ffa8a8}</style></head>
<body><main><h1>Создать администратора</h1><p>Это делается один раз. Код установки возьми в Railway → ai-for-seller-app → Variables → FIRST_SETUP_CODE. Никому его не отправляй.</p>
<form id="form">
<label>Код установки<input name="code" type="password" required autocomplete="off"></label>
<label>Твоя почта<input name="email" type="email" required autocomplete="email"></label>
<label>Придумай пароль для сайта (от 12 символов)<input name="password" type="password" minlength="12" required autocomplete="new-password"></label>
<button type="submit">Создать аккаунт</button>
<p id="error" role="status"></p></form></main>
<script>
document.getElementById('form').addEventListener('submit',async e=>{
 e.preventDefault(); const el=e.currentTarget,button=el.querySelector('button');button.disabled=true;
 const data=Object.fromEntries(new FormData(el));const error=document.getElementById('error');
 error.textContent='';try{
  const r=await fetch('/api/first-setup',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify(data)});
  const j=await r.json();if(!r.ok)throw Error(j.detail||'Не удалось создать аккаунт');
  location.href='/';
 }catch(err){error.textContent=err.message;button.disabled=false;}
});</script></body></html>""",headers={"Cache-Control":"no-store","X-Robots-Tag":"noindex"})

    @app.post("/api/first-setup")
    def setup_admin(body: SetupInput, request: Request):
        configured = os.environ.get("FIRST_SETUP_CODE", "")
        if len(configured) < 32:
            raise HTTPException(503, "В Railway код FIRST_SETUP_CODE должен содержать минимум 32 символа. Измените его и примените Deploy.")
        if len(body.code) < 32:
            raise HTTPException(400, "Введённый код слишком короткий: требуется минимум 32 символа.")
        if not hmac.compare_digest(body.code.encode(), configured.encode()):
            raise HTTPException(403, "Код не совпадает с FIRST_SETUP_CODE в Railway. Скопируйте его целиком, без пробелов.")
        if body.email.strip().lower() != os.environ.get("FIRST_ADMIN_EMAIL","").strip().lower():
            raise HTTPException(403, "Укажи почту владельца, указанную при настройке")
        if len(body.password) < 12 or len(body.password) > 256:
            raise HTTPException(400, "Пароль должен быть от 12 до 256 символов")
        from scripts.bootstrap import create
        try:
            with db.connect() as c:
                create(c, body.email, body.password, "My Seller Analytics")
        except ValueError as e:
            raise HTTPException(409, str(e))
        # Setup can never create another admin: bootstrap locks and refuses a nonempty installation.
        return JSONResponse({"ok": True},headers={"Cache-Control":"no-store"})
