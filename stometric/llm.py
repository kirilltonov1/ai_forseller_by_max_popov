"""Self-hosted application component."""

import json
import urllib.error
import urllib.request

ANTHROPIC = "anthropic"
CLAUDE_MODEL = "claude-sonnet-5-5"


PROVIDERS = {
    ANTHROPIC: {"title": "Claude (Anthropic)", "model": CLAUDE_MODEL, "keys": "console.anthropic.com → API Keys"},
    "openai": {"title": "ChatGPT (OpenAI)", "base": "https://api.openai.com/v1", "model": "gpt-5", "max": "max_completion_tokens",
               "images": True, "pdf": True, "keys": "platform.openai.com → API keys"},
    "gemini": {"title": "Gemini (Google)", "base": "https://generativelanguage.googleapis.com/v1beta/openai", "model": "gemini-2.5-pro",
               "max": "max_tokens", "images": True, "pdf": False, "keys": "aistudio.google.com → Get API key"},
    "deepseek": {"title": "DeepSeek", "base": "https://api.deepseek.com", "model": "deepseek-chat", "max": "max_tokens",
                 "images": False, "pdf": False, "keys": "platform.deepseek.com → API keys"},
}


class AiKey(str):
    """Ключ нейросети: сама строка — ключ (как раньше), плюс провайдер и модель."""
    provider: str = ANTHROPIC
    model: str | None = None

    def __new__(cls, key: str, provider: str = ANTHROPIC, model: str | None = None):
        o = super().__new__(cls, key)
        o.provider = provider if provider in PROVIDERS else ANTHROPIC
        o.model = (model or "").strip() or None
        return o


def from_secret(text: str) -> AiKey:
    """Расшифрованный ключ кабинета: JSON {provider, key, model} или просто ключ Claude (как хранили до 21.10)."""
    t = text.strip()
    if t.startswith("{"):
        d = json.loads(t)
        return AiKey(d["key"], d.get("provider") or ANTHROPIC, d.get("model"))
    return AiKey(t)


def to_secret(provider: str, key: str, model: str | None) -> str:
    return json.dumps({"provider": provider, "key": key.strip(), "model": (model or "").strip() or None})


def provider_of(key) -> str:
    return getattr(key, "provider", ANTHROPIC)


def model_of(key) -> str:
    return getattr(key, "model", None) or PROVIDERS[provider_of(key)]["model"]


def title_of(key) -> str:
    return PROVIDERS[provider_of(key)]["title"]


class AiError(RuntimeError):
    pass


def _http(url: str, headers: dict, body: dict | None, timeout: int) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 method="POST" if body is not None else "GET", headers={"content-type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error")
            msg = msg.get("message") if isinstance(msg, dict) else msg
        except Exception:  
            msg = None
        raise AiError(f"нейросеть ответила ошибкой {e.code}" + (f": {str(msg)[:200]}" if msg else "")) from None


def _headers(key) -> dict:
    if provider_of(key) == ANTHROPIC:
        return {"x-api-key": str(key), "anthropic-version": "2023-06-01"}
    return {"Authorization": f"Bearer {key}"}



def _oa_part(b: dict, p: dict):
    t = b.get("type")
    if t == "text":
        return {"type": "text", "text": b.get("text") or ""}
    if t == "image":
        if not p["images"]:
            return {"type": "text", "text": "[картинка: эта нейросеть не принимает изображения]"}
        s = b["source"]
        return {"type": "image_url", "image_url": {"url": f"data:{s['media_type']};base64,{s['data']}"}}
    if t == "document":
        if not p["pdf"]:
            return {"type": "text", "text": "[PDF: эта нейросеть не принимает PDF — пришлите таблицей или текстом]"}
        return {"type": "file", "file": {"filename": "file.pdf", "file_data": f"data:application/pdf;base64,{b['source']['data']}"}}
    return {"type": "text", "text": json.dumps(b, ensure_ascii=False)[:2000]}


def _to_openai(body: dict, p: dict) -> dict:
    msgs = [{"role": "system", "content": body["system"]}] if body.get("system") else []
    for m in body["messages"]:
        content = m["content"]
        if isinstance(content, str):
            msgs.append({"role": m["role"], "content": content})
            continue
        if m["role"] == "assistant":
            text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
            calls = [{"id": b["id"], "type": "function", "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {}, ensure_ascii=False)}}
                     for b in content if b.get("type") == "tool_use"]
            msgs.append({"role": "assistant", "content": text or None, **({"tool_calls": calls} if calls else {})})
            continue
        results = [b for b in content if b.get("type") == "tool_result"]
        for b in results:
            c = b.get("content")
            msgs.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)})
        parts = [_oa_part(b, p) for b in content if b.get("type") != "tool_result"]
        if parts:
            msgs.append({"role": "user", "content": parts})
    out = {"model": body["model"], "messages": msgs, p["max"]: body.get("max_tokens") or 2000}
    if body.get("tools"):
        out["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                                          "parameters": t.get("input_schema") or {"type": "object", "properties": {}}}}
                        for t in body["tools"]]
    choice = body.get("tool_choice")
    if choice:
        if choice.get("type") in ("none", "auto"):
            out["tool_choice"] = choice["type"]
        elif choice.get("type") == "any":
            out["tool_choice"] = "required"
        elif choice.get("type") == "tool":
            out["tool_choice"] = {"type": "function", "function": {"name": choice["name"]}}
    return out


def _from_openai(res: dict) -> dict:
    ch = (res.get("choices") or [{}])[0]
    msg = ch.get("message") or {}
    blocks = [{"type": "text", "text": msg["content"]}] if msg.get("content") else []
    for tc in msg.get("tool_calls") or []:
        f = tc.get("function") or {}
        try:
            args = json.loads(f.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        blocks.append({"type": "tool_use", "id": tc.get("id"), "name": f.get("name"), "input": args if isinstance(args, dict) else {}})
    return {"content": blocks, "stop_reason": "tool_use" if msg.get("tool_calls") else ch.get("finish_reason")}


def messages(key, body: dict, timeout: int = 180) -> dict:
    """Запрос в формате Claude Messages API к нейросети кабинета → ответ в формате Claude ({"content": [блоки]}).
    model в body не нужен — берём модель ключа."""
    prov = provider_of(key)
    body = {**body, "model": model_of(key)}
    if prov == ANTHROPIC:
        return _http("https://api.anthropic.com/v1/messages", _headers(key), body, timeout)
    p = PROVIDERS[prov]
    return _from_openai(_http(p["base"] + "/chat/completions", _headers(key), _to_openai(body, p), timeout))


def text(res: dict) -> str:
    return "".join(b.get("text", "") for b in res.get("content") or [] if b.get("type") == "text").strip()


def check(key) -> str | None:
    """Проверка ключа без генерации (список моделей). None — ок."""
    prov = provider_of(key)
    url = "https://api.anthropic.com/v1/models?limit=1000" if prov == ANTHROPIC else PROVIDERS[prov]["base"] + "/models"
    name = PROVIDERS[prov]["title"]
    try:
        res = _http(url, _headers(key), None, 30)
        ids = {str(m.get("id") or "").removeprefix("models/") for m in res.get("data") or []}
        if getattr(key, "model", None) and ids and key.model not in ids:     
            return f"{name}: модели «{key.model}» нет у этого ключа. Например: {', '.join(sorted(ids)[:8])}"
        return None
    except AiError as e:
        return f"{name} не принял ключ (неверный или отключён)" if " 401" in str(e) or " 403" in str(e) else f"{name}: {e}"
    except Exception as e:  
        return f"{name} не ответил: {str(e)[:120]}"
