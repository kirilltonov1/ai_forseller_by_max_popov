import { useMemo, useState } from "react";
import type { Me, Tab, Workspace } from "./api";
import { Logo } from "./Logo";

export type Page = "tab" | "account" | "calendar" | "members" | "billing" | "referral" | "admin" | "about" | "service_news" | "reviews" | "questions" | "actions" | "cards" | "seo" | "visual" | "ads" | "total" | "warehouse" | "kb" | "ai";

const ROLE: Record<string, string> = { owner: "Владелец", admin: "Админ", editor: "Редактор", viewer: "Просмотр" };

type Props = {
  me: Me; ws: Workspace | undefined; open: boolean; onToggle: () => void;
  page: Page; tab: string; onTab: (k: string) => void; onPage: (p: Page) => void;
  theme: "light" | "dark"; onTheme: () => void; onLogout: () => void; onAssistant?: () => void;
  allTabs?: Tab[]; hidden?: string[]; onHidden?: (keys: string[]) => void;
};

export function Sidebar({ me, ws, open, onToggle, page, tab, onTab, onPage, theme, onTheme, onLogout, onAssistant, allTabs, hidden = [], onHidden }: Props) {
  const [q, setQ] = useState("");
  const [edit, setEdit] = useState(false);       // настройка: какие вкладки показывать
  const hide = (keys: string[], on: boolean) => onHidden?.(on ? [...new Set([...hidden, ...keys])] : hidden.filter((k) => !keys.includes(k)));
  const [shut, setShut] = useState<Record<string, boolean>>(() => {
    try { return JSON.parse(localStorage.getItem("side_groups") || "{}"); } catch { return {}; }
  });
  const flip = (g: string) => setShut((s) => {
    const n = { ...s, [g]: !s[g] };
    try { localStorage.setItem("side_groups", JSON.stringify(n)); } catch { /* нет хранилища */ }
    return n;
  });
  const groups = useMemo(() => [...new Set(me.tabs.map((t) => t.group))], [me.tabs]);
  const ql = q.trim().toLowerCase();
  const item = (key: Page, icon: string, title: string) => (
    <button className={"side-item" + (page === key ? " on" : "")} title={title} onClick={() => onPage(key)}>
      <span className="ic">{icon}</span>{open && <span className="tx">{title}</span>}
    </button>
  );
  return (
    <aside className={"side" + (open ? " open" : "")}>
      <div className="side-top">
        <button className="side-burger" title={open ? "Свернуть меню" : "Развернуть меню"} onClick={onToggle}>{open ? "«" : "☰"}</button>
        {open ? <Logo kind="horizontal" theme={theme} height={30} /> : null}
      </div>
      {open ? (
        <div className="side-acc" onClick={() => onPage("account")} title="Настройки аккаунта">
          <div className="side-ws">{ws?.name || "Кабинет"}</div>
          <div className="side-user">{me.user.name || me.user.email}</div>
          <div className="side-role">{ROLE[ws?.role || ""] || ws?.role}{me.user.superadmin ? " · суперадмин" : ""}</div>
        </div>
      ) : (
        <button className="side-avatar" title={`${ws?.name || ""} · ${me.user.email}`} onClick={() => onPage("account")}>
          {(ws?.name || me.user.email).slice(0, 1).toUpperCase()}
        </button>
      )}
      {open && <button className="side-menu-t" onClick={() => flip("__menu")} title={shut.__menu ? "Показать меню аккаунта и кабинета" : "Свернуть — больше места вкладкам"}>
        <span>{shut.__menu ? "▸" : "▾"}</span>Меню{shut.__menu ? " (свернуто)" : ""}</button>}
      {!(open && shut.__menu) && <div className="side-sec">
        {open && <button className="side-h side-h-btn" onClick={() => flip("__acc")}>{shut.__acc ? "▸" : "▾"} Аккаунт</button>}
        {!(open && shut.__acc) && <>
        {item("account", "⚙️", "Настройки аккаунта")}
        {item("calendar", "📅", "Календарь")}
        {item("members", "👥", "Пользователи и права")}
        {item("billing", "💳", "Тариф и оплата")}
        {item("ai", "🔌", "Нейросети (MCP)")}
        {item("referral", "🎁", "Пригласить друга")}
        <a className="side-item" href="/compare" title="Бесплатный инструмент: хранение и наглядный разбор отчётов WB «Сравнение карточек»">
          <span className="ic">⚖️</span>{open && <span className="tx">Сравнение карточек</span>}</a>
        {onAssistant && <button className="side-item" title="Стометрик — умный помощник по магазину" onClick={onAssistant}>
          <span className="ic">🧙</span>{open && <span className="tx">Стометрик</span>}</button>}
        {item("total", "📊", "Сумма магазинов")}
        {ws?.role === "owner" && item("warehouse", "📦", "Общий склад")}
        {item("kb", "📚", "База знаний")}</>}
        {open && <button className="side-h side-h-btn" onClick={() => flip("__work")}>{shut.__work ? "▸" : "▾"} Работа с кабинетом</button>}
        {!(open && shut.__work) && <>
        {item("reviews", "⭐", "Отзывы")}
        {item("questions", "❓", "Вопросы")}
        {item("cards", "🃏", "Карточки")}
        {item("seo", "🔎", "SEO")}
        {item("visual", "🎨", "Визуал")}
        {item("ads", "📢", "Реклама")}
        {item("actions", "🤝", "Взаимодействия")}</>}
        {open && <div className="side-h" />}
        <button className={"side-item" + (page === "service_news" ? " on" : "")} title="Новости сервиса: что нового и что улучшили"
          onClick={() => onPage("service_news")}><span className="ic">📣</span>{open && <span className="tx">Новости сервиса</span>}
          {!!me.news_unread && <span className="side-badge">{me.news_unread}</span>}</button>
        {item("about", "ℹ️", "О сервисе")}
        {me.user.superadmin && item("admin", "🛠", "Админка сервиса")}
      </div>}
      <div className="side-sec side-tabs">
        {open ? (
          <>
            <div className="side-h side-h-row">Вкладки
              {onHidden && <button className={"side-cfg" + (edit ? " on" : "")} title="Какие вкладки показывать в меню"
                onClick={() => setEdit(!edit)}>{edit ? "Готово" : "⚙ Настроить"}</button>}</div>
            {edit && allTabs ? (
              <div className="side-edit">
                <div className="side-edit-h">Снимите галочку — вкладка пропадёт из меню (только у вас, вернуть можно здесь же).
                  {hidden.length > 0 && <button onClick={() => onHidden?.([])}>Показать все ({hidden.length} скрыто)</button>}</div>
                {[...new Set(allTabs.map((t) => t.group))].map((g) => {
                  const list = allTabs.filter((t) => t.group === g);
                  const keys = list.map((t) => t.key).filter((k) => k !== "home");
                  const shown = keys.filter((k) => !hidden.includes(k)).length;
                  return (
                    <div key={g} className="side-grp">
                      <label className="side-gh side-chk"><input type="checkbox" checked={shown > 0} disabled={!keys.length}
                        ref={(el) => { if (el) el.indeterminate = shown > 0 && shown < keys.length; }}
                        onChange={(e) => hide(keys, !e.target.checked)} />{g}</label>
                      {list.map((t) => (
                        <label key={t.key} className="side-tab side-chk" title={t.key === "home" ? "Главную скрыть нельзя" : t.help || t.title}>
                          <input type="checkbox" checked={!hidden.includes(t.key)} disabled={t.key === "home"}
                            onChange={(e) => hide([t.key], !e.target.checked)} />{t.title}</label>
                      ))}
                    </div>
                  );
                })}
              </div>
            ) : <>
            <input className="side-q" placeholder="Найти вкладку…" value={q} onChange={(e) => setQ(e.target.value)} />
            {groups.map((g) => {
              const list = me.tabs.filter((t) => t.group === g && (!ql || t.title.toLowerCase().includes(ql)));
              if (!list.length) return null;
              const closed = !ql && shut[g];
              return (
                <div key={g} className="side-grp">
                  <button className="side-gh" onClick={() => flip(g)}><span>{closed ? "▸" : "▾"}</span>{g}</button>
                  {!closed && list.map((t) => (
                    <button key={t.key} className={"side-tab" + (page === "tab" && t.key === tab ? " on" : "")} title={t.help || t.title}
                      onClick={() => onTab(t.key)}>{t.title}</button>
                  ))}
                </div>
              );
            })}
            {hidden.length > 0 && <button className="side-hidden-n" onClick={() => setEdit(true)}>Скрыто вкладок: {hidden.length} · показать</button>}
            </>}
          </>
        ) : (
          <>
            <button className={"side-item" + (page === "tab" && tab === "home" ? " on" : "")} title="Главная" onClick={() => onTab("home")}>
              <span className="ic">🏠</span>
            </button>
            <button className="side-item" title="Все вкладки — развернуть меню" onClick={onToggle}><span className="ic">📑</span></button>
          </>
        )}
      </div>
      <div className="side-bottom">
        <button className="side-item" title="Светлая / тёмная тема" onClick={onTheme}>
          <span className="ic">{theme === "dark" ? "☀️" : "🌙"}</span>{open && <span className="tx">{theme === "dark" ? "Светлая тема" : "Тёмная тема"}</span>}
        </button>
        <button className="side-item" title="Выйти" onClick={onLogout}><span className="ic">🚪</span>{open && <span className="tx">Выйти</span>}</button>
      </div>
    </aside>
  );
}
