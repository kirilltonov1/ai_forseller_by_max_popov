import { useEffect, useMemo, useRef, useState } from "react";
import { AgGridReact } from "ag-grid-react";
import { AllCommunityModule, ModuleRegistry, themeQuartz, colorSchemeDark, colorSchemeLight, type CellStyle, type ColDef, type ColGroupDef } from "ag-grid-community";
import { api, http, type Col, type Me, type ShopStaff, type Tab, type TabData, type TabQ } from "./api";
import { copyCell } from "./copy";
import { ChartPanel } from "./Chart";
import { LayoutEditor } from "./LayoutEditor";
import { TaxForm } from "./TaxForm";
import { Home } from "./Home";
import { Sidebar, type Page } from "./Sidebar";
import { AiLinks, OAuthConsent } from "./AiLinks";
import { Kb } from "./Kb";
import { AboutPage, LegalNote, LegalPage, TermsGate } from "./Legal";
import { Assistant, Gnome, GNOME_ACTS } from "./Assistant";
import { Account } from "./Account";
import { ArtPicker } from "./ArtPicker";
import { InvitePage } from "./Members";
import { MagicPage } from "./Notify";
import { ActionsBoard } from "./ActionsBoard";
import { PriceLab } from "./PriceLab";
import { Competitors } from "./Competitors";
import { Insights } from "./Insights";
import { Billing, Referral } from "./Billing";
import { Admin } from "./Admin";
import { HomeAI } from "./HomeAI";
import { HomeTasks } from "./HomeTasks";
import { Calendar, HomeCalendar } from "./Calendar";
import { useTabData } from "./useTabData";
import { Actions } from "./Actions";
import { Reviews } from "./Reviews";
import { Questions } from "./Questions";
import { Cards } from "./Cards";
import { Ads } from "./Ads";
import { Total } from "./Total";
import { Warehouse } from "./Warehouse";
import { Rnp } from "./Rnp";
import { News } from "./News";
import { EntryPoints } from "./EntryPoints";
import { ExtCosts } from "./ExtCosts";
import { Mrc } from "./Mrc";
import { Shelves } from "./Shelves";
import { CostBar } from "./CostBar";
import { ServiceNews } from "./ServiceNews";
import { Promo } from "./Promo";
import { Hypotheses } from "./Hypotheses";
import { Seo } from "./Seo";
import { SeoBlock } from "./SeoBlock";
import { VisualBlock } from "./VisualBlock";
import { ChecklistTop } from "./ChecklistTop";
import { Planning } from "./Planning";
import { ComparePage } from "./Compare";
import { Exclusions } from "./Exclusions";
import { Staff } from "./Staff";
import { TabBarEdit } from "./TabBarEdit";
import { Logo } from "./Logo";
import { PhotoFunnel } from "./PhotoFunnel";
import { COL_TREND_TABS, KEY_COL, PNL_TABS, KEY_ROW, SKIP_COL, colPairs, rowDir, trendPairs, type TrendMode } from "./trend";
import "./App.css";

ModuleRegistry.registerModules([AllCommunityModule]);

const iso = (d: Date) => d.toISOString().slice(0, 10);
const nf = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
const nf2 = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });

const fmtNum = (type: string, v: unknown) => {
  if (v == null || v === "") return "";
  const n = Number(v);
  return type === "share" ? nf2.format(n * 100) + " %" : type === "pct" ? nf2.format(n) + " %" : type === "num" ? nf2.format(n) : nf.format(n);
};

/** Подряд идущие столбцы одной метрики за разные периоды (+ «разница» за ними) → один столбец, периоды друг под другом. */
function stackCols(list: Col[]): Col[] {
  const out: Col[] = [];
  for (let i = 0; i < list.length; i++) {
    const c = list[i];
    if (!c.metric || c.metric === "разница") { out.push(c); continue; }
    const parts = [c];
    while (i + 1 < list.length && list[i + 1].metric === c.metric && !list[i + 1].group) parts.push(list[++i]);
    let diff: Col | undefined;
    if (i + 1 < list.length && list[i + 1].metric === "разница" && !list[i + 1].group) diff = list[++i];
    if (parts.length === 1 && !diff) { out.push(c); continue; }
    const short = (p: Col) => (p.title.split(" · ")[1] || p.period || "").replace(/\s*\(.*\)$/, "");
    out.push({ field: c.field, title: c.metric, type: "stack", group: c.group, metric: c.metric,
      stack: [...parts.map((p) => ({ label: short(p), field: p.field, type: p.type })),
        ...(diff ? [{ label: "разница", field: diff.field, type: diff.type, diff: true }] : [])] });
  }
  return out;
}

const GROUP_TABS = new Set(["dash_group", "v2_day", "v2_week", "v2_month", "v2_unit", "v2_turnover", "v2_stocks", "v2_phrases", "v2_queries", "v2_check"]);   // вкладки с выбором группы/склейки

// столбцы артикулов и SKU: клик по ячейке — скопировать значение 
const COPY_FIELDS = new Set(["nm_id", "sku", "vendor_code", "offer_id", "vc", "supplier_article", "nm", "imt_id"]);
const isCopyCol = (c: Col) => COPY_FIELDS.has(c.field) || (/^(артикул|sku)/i.test(c.title || "") && !/артикулы/i.test(c.title || ""));

function colDef(c: Col): ColDef {
  const base: ColDef = { field: c.field, headerName: c.title, headerTooltip: c.title, sortable: true, resizable: true, filter: true,
    ...(isCopyCol(c) ? { cellClass: "copy-cell", tooltipValueGetter: () => "Нажмите, чтобы скопировать",
      onCellClicked: (p) => { if (!p.node.rowPinned) copyCell(p.value, p.event); } } : {}) };
  switch (c.type) {
    case "int":
    case "money":
      return { ...base, filter: "agNumberColumnFilter", type: "rightAligned",
        valueFormatter: (p) => (p.value == null ? "" : c.field.endsWith("_id") || c.field === "nm_id" ? String(p.value) : nf.format(Number(p.value))) };
    case "num":
    case "pct":
      return { ...base, filter: "agNumberColumnFilter", type: "rightAligned",
        valueFormatter: (p) => (p.value == null ? "" : nf2.format(Number(p.value)) + (c.type === "pct" ? " %" : "")) };
    case "edit_money":
      return { ...base, editable: true, filter: "agNumberColumnFilter", type: "rightAligned", cellClass: "editable",
        valueParser: (p) => { const v = Number(String(p.newValue).replace(",", ".").replace(/\s/g, "")); return isNaN(v) ? p.oldValue : v; },
        valueFormatter: (p) => (p.value == null ? "— не задана —" : nf2.format(Number(p.value))) };
    case "edit_text":
      return { ...base, editable: true, cellClass: "editable" };
    case "label":
      return { ...base, pinned: "left", width: 430, suppressAutoSize: true, filter: false, sortable: false,
        cellClass: (p) => (p.data?.fmt === "h" ? "row-h" : "") };
    case "rowfmt":
      return { ...base, filter: false, sortable: false, type: "rightAligned", width: 130,
        valueFormatter: (p) => {
          if (p.value == null || p.data?.fmt === "h") return "";
          const v = Number(p.value);
          return p.data?.fmt === "pct" ? nf2.format(v * 100) + " %" : p.data?.fmt === "num" ? nf2.format(v) : nf.format(v);
        } };
    case "change":
      return { ...base, filter: false, sortable: false, type: "rightAligned", width: 90,
        cellClass: (p) => (p.value > 0 ? "up" : p.value < 0 ? "down" : ""),
        valueFormatter: (p) => (p.value == null || p.data?.fmt === "h" ? "" :
          (p.data?.fmt === "pct" ? (p.value > 0 ? "+" : "") + nf2.format(Number(p.value) * 100) + " п.п."
            : (p.value > 0 ? "+" : "") + nf.format(Number(p.value) * 100) + " %")) };
    case "share":
      return { ...base, filter: "agNumberColumnFilter", type: "rightAligned",
        valueFormatter: (p) => (p.value == null ? "" : nf2.format(Number(p.value) * 100) + " %") };
    case "date":
      return { ...base, filter: "agDateColumnFilter", valueFormatter: (p) => (p.value ? String(p.value).slice(0, 10).split("-").reverse().join(".") : "") };
    case "datetime":
      return { ...base, valueFormatter: (p) => (p.value ? new Date(String(p.value)).toLocaleString("ru-RU") : "") };
    case "stack":
      return { ...base, filter: "agNumberColumnFilter", type: "rightAligned", minWidth: 150, autoHeight: false, cellClass: "stack-cell",
        cellRenderer: (p: { data?: Record<string, unknown> }) => (
          <div className="stack">{c.stack!.map((s) => {
            const v = p.data?.[s.field];
            const n = Number(v);
            return (
              <div key={s.field} className={s.diff ? (n > 0 ? "up" : n < 0 ? "down" : "") : ""}>
                <span className="st-l">{s.label}</span>{s.diff && n > 0 ? "+" : ""}{fmtNum(s.type, v)}
              </div>
            );
          })}</div>
        ) };
    case "image":
      return { ...base, width: 70, filter: false, sortable: false,
        cellRenderer: (p: { value?: string }) => (p.value ? <img src={p.value} className="thumb" alt="" /> : null) };
    default:
      return base;
  }
}

/** Реклама WB: ключи (поисковые кластеры) выбранной кампании — под таблицей кампаний. */
const AD_TABS: Record<string, [string, string][]> = {   // вкладка кампаний → что открывается по клику на кампанию
  ads_kw: [["ads_keys", "🔑 Ключи"], ["ads_assoc", "🔗 Ассоциированные конверсии"]],
  oz_ads_kw: [["oz_ad_items", "📦 Товары"], ["oz_ad_phrases", "🔎 Фразы"]],
};

function AdKeys({ shop, from, to, nm, camp, theme, onClose, parent }: { shop: number; from: string; to: string; nm: string; camp: { id: string; name: string };
  theme: typeof themeQuartz; onClose: () => void; parent: string }) {
  const subs = AD_TABS[parent] || [];
  const [sub, setSub] = useState(subs[0]?.[0] || "");
  const [d, setD] = useState<TabData | null>(null);
  const [err, setErr] = useState("");
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    setD(null); setErr("");
    api.tab(shop, sub, { from, to, nm, campaign: camp.id }).then(setD).catch((e) => setErr(e.message));
    setTimeout(() => box.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
  }, [shop, from, to, nm, camp.id, sub]);
  const cols = useMemo(() => (d?.columns || []).filter((c) => c.field !== "campaign" && c.field !== "advert_id")
    .map((c) => (c.field === "query" || c.field === "phrase" ? { ...colDef(c), width: 300, pinned: "left" as const } : colDef(c))), [d]);
  const n = d?.rows.length ?? 0;
  const spendOf = (r: Record<string, unknown>) => Number(r.spend ?? r.spend_est ?? 0);
  const noOrders = (d?.rows || []).filter((r) => ("q_orders" in r ? r.q_orders === 0 : !Number(r.orders) && !Number(r.models)) && spendOf(r) > 0);
  const waste = noOrders.reduce((s, r) => s + spendOf(r), 0);
  return (
    <div ref={box} className="adkeys">
      <div className="adkeys-h"><b>Кампания «{camp.name}»</b> <span className="hint">ID {camp.id}</span>
        {subs.length > 1 && subs.map(([k, t]) => <button key={k} className={"chip" + (k === sub ? " on" : "")} onClick={() => setSub(k)}>{t}</button>)}
        <button className="link" onClick={onClose}>✕ закрыть</button></div>
      {err && <div className="err">{err}</div>}
      {d?.note && <div className="hint">ℹ️ {d.note}</div>}
      {d && <div className="hint">Строк: {nf.format(n)}{noOrders.length ? ` · без заказов при расходе: ${nf.format(noOrders.length)} на ${nf.format(waste)} ₽` : ""}
        {" "}· сортировка — клик по заголовку, фильтр — ☰ в заголовке.</div>}
      {d && !n && d.empty && <div className="hint">{d.empty}</div>}
      <div className="grid" style={{ height: "60vh", minHeight: 320 }}>
        <AgGridReact theme={theme} rowData={d?.rows || []} columnDefs={cols} loading={!d && !err} enableCellTextSelection
          defaultColDef={{ minWidth: 90, wrapHeaderText: true, autoHeaderHeight: true }} pagination paginationPageSize={100} />
      </div>
    </div>
  );
}

function Login({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");
  const [reg, setReg] = useState<string | null>(null);
  useEffect(() => {
    let ref = new URLSearchParams(window.location.search).get("ref") || "";
    try { if (ref) localStorage.setItem("ref", ref); else ref = localStorage.getItem("ref") || ""; } catch { /* нет хранилища */ }
    http.get<{ bot_link: string | null }>(`/api/ref/${encodeURIComponent(ref || "-")}`).then((r) => setReg(r.bot_link)).catch(() => undefined);
  }, []);
  return (
    <div className="login">
      <form onSubmit={async (e) => { e.preventDefault(); setErr("");
        try { await api.login(email, pw); onDone(); } catch (x) { setErr((x as Error).message === "401" ? "Неверный логин или пароль" : (x as Error).message); } }}>
        <Logo kind="vertical" height={96} />
        <input placeholder="E-mail" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
        <input placeholder="Пароль" type="password" value={pw} onChange={(e) => setPw(e.target.value)} />
        <button>Войти</button>
        {err && <div className="err">{err}</div>}
        {reg && <a className="reg-link" href={reg} target="_blank" rel="noreferrer">Нет аккаунта? Регистрация через Telegram →</a>}
        <LegalNote />
      </form>
    </div>
  );
}

export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [need, setNeed] = useState(false);
  const [shop, setShop] = useState<number | null>(null);
  const [tab, setTab] = useState("home");
  // «Визуал» → «Открыть в Карточках»: переход с артикулом (событие ais:cards)
  const [cardsNm, setCardsNm] = useState<number | null>(null);
  useEffect(() => {
    const go = (e: Event) => { setCardsNm((e as CustomEvent<number>).detail); setPage("cards"); };
    window.addEventListener("ais:cards", go); return () => window.removeEventListener("ais:cards", go);
  }, []);
  const [page, setPage] = useState<Page>(() => (new URLSearchParams(window.location.search).get("page") === "warehouse" ? "warehouse" : new URLSearchParams(window.location.search).get("hf") ? "account" : "tab"));   // возврат со входа в Higgsfield — в настройки
  const [calendarDay, setCalendarDay] = useState<string | undefined>();
  useEffect(() => { if (page !== "cards") setCardsNm(null); }, [page]);
  useEffect(() => {
    const go = (e: Event) => setPage((e as CustomEvent<Page>).detail);
    window.addEventListener("ais:page", go);
    return () => window.removeEventListener("ais:page", go);
  }, []);
  const narrow = () => window.matchMedia?.("(max-width: 800px)").matches;
  const [sideOpen, setSideOpen] = useState<boolean>(() => {
    if (narrow()) return false;
    try { return localStorage.getItem("side_open") !== "0"; } catch { return true; }
  });
  useEffect(() => { try { if (!narrow()) localStorage.setItem("side_open", sideOpen ? "1" : "0"); } catch { /* нет хранилища */ } }, [sideOpen]);
  const navRef = useRef<HTMLElement>(null);
  const [tbEdit, setTbEdit] = useState(false);       // настройка панели вкладок
  const [more, setMore] = useState(false);           // «Ещё ▾» — вкладки не на панели
  // ширина столбцов: узкие (заголовок до 3 строк) / по содержимому / широкие (заголовок в 1 строку)
  type ColMode = "narrow" | "auto" | "wide";
  const [colMode, setColModeRaw] = useState<ColMode>(() => {
    try { const v = localStorage.getItem("col_mode"); if (v === "narrow" || v === "auto" || v === "wide") return v; } catch { /* нет хранилища */ }
    return "auto";
  });
  const setColMode = (v: ColMode) => { setColModeRaw(v); try { localStorage.setItem("col_mode", v); } catch { /* нет хранилища */ } };
  const gridRef = useRef<AgGridReact>(null);
  const [trend, setTrendRaw] = useState<TrendMode>(() => {
    try { const v = localStorage.getItem("trend_mode"); if (v === "fill" || v === "text" || v === "none") return v; } catch { /* нет хранилища */ }
    return "none";
  });
  const setTrend = (v: TrendMode) => { setTrendRaw(v); try { localStorage.setItem("trend_mode", v); } catch { /* нет хранилища */ } };
  const [stacked, setStackedRaw] = useState<boolean>(() => { try { return localStorage.getItem("stack_periods") === "1"; } catch { return false; } });
  const setStacked = (v: boolean) => { setStackedRaw(v); try { localStorage.setItem("stack_periods", v ? "1" : "0"); } catch { /* нет хранилища */ } };
  const defCol = useMemo<ColDef>(() => colMode === "wide" ? { minWidth: 90 }
    : { width: 112, minWidth: colMode === "auto" ? 64 : 80, maxWidth: 420, wrapHeaderText: true, autoHeaderHeight: true }, [colMode]);
  const gridBox = useRef<HTMLDivElement>(null);
  const fitNow = () => {
    const g = gridRef.current?.api;
    if (colMode !== "auto" || !g || g.isDestroyed()) return;
    if (!gridBox.current || gridBox.current.offsetParent === null) return;   // сетка скрыта (главная, свои страницы) — мерить нечего
    const auto = (g.getColumns() || []).filter((col) => !col.getColDef().suppressAutoSize);
    if (!auto.length) return;
    g.autoSizeColumns(auto, true); // по содержимому ячеек, без заголовка
    // …но не уже, чем нужно, чтобы заголовок уместился в 3 строки (≈7 px на букву)
    const fix = auto.map((col) => {
      const title = col.getColDef().headerName || "";
      const need = Math.min(Math.ceil(title.length / 3) * 7 + 22, 200);
      return { key: col.getColId(), newWidth: Math.max(col.getActualWidth(), need) };
    }).filter((x, i) => x.newWidth !== auto[i].getActualWidth());
    if (fix.length) g.setColumnWidths(fix);
  };
  // мерить только после того, как новые строки и столбцы отрисованы: сразу после смены данных ячеек ещё нет,
  // и ширина «по содержимому» получалась минимальной . Два кадра + повтор через 300 мс.
  const fit = () => {
    requestAnimationFrame(() => requestAnimationFrame(fitNow));
    setTimeout(fitNow, 300);
  };
  useEffect(() => { navRef.current?.querySelector("button.on")?.scrollIntoView({ block: "nearest", inline: "center", behavior: "smooth" }); }, [tab, page]);
  useEffect(() => {   // сменили магазин WB ↔ Ozon — открыть первую вкладку его набора, если текущей там нет
    if (!me || !shop) return;
    const m = me.shops.find((s) => s.id === shop)?.marketplace;
    const list = m === "ozon" ? me.oz_tabs : m === "ym" ? me.ym_tabs : me.tabs;
    if (list.length && !list.some((t) => t.key === tab)) setTab(list[0].key);
  }, [me, shop]);   // eslint-disable-line react-hooks/exhaustive-deps
  const openTab = (k: string) => { setTab(k); setPage("tab"); if (narrow()) setSideOpen(false); };
  const today = new Date();
  const [from, setFrom] = useState(iso(new Date(today.getTime() - 29 * 864e5)));
  const [to, setTo] = useState(iso(today));
  const autoDay = useRef(iso(today));      // день, на который сайт сам поставил «по» (период по умолчанию)
  const toRef = useRef(to);
  toRef.current = to;
  useEffect(() => {   // вкладка открыта через полночь: период «по сегодня» сам переходит на новый день ; свой период не трогаем
    const roll = () => {
      const now = iso(new Date()), was = autoDay.current;
      if (now === was || toRef.current !== was) return;
      autoDay.current = now;
      const shift = new Date(now).getTime() - new Date(was).getTime();
      setFrom((f) => iso(new Date(new Date(f).getTime() + shift)));
      setTo(now);
    };
    const id = setInterval(roll, 60_000);
    document.addEventListener("visibilitychange", roll);
    return () => { clearInterval(id); document.removeEventListener("visibilitychange", roll); };
  }, []);
  const [nm, setNm] = useState("");
  const [err, setErr] = useState("");
  const [reload, setReload] = useState(0);
  const [staffSel, setStaffSel] = useState<number | null>(null);    // фильтр «Менеджер» (по умолчанию — все; Example, 22.10)
  const [shopStaff, setShopStaff] = useState<ShopStaff | null>(null);
  useEffect(() => {
    if (!shop) return;
    let live = true;
    api.shopStaff(shop).then((s) => { if (!live) return; setShopStaff(s);
      setStaffSel((cur) => (cur && s.staff.some((x) => x.id === cur && x.n > 0) ? cur : null)); }).catch(() => { if (live) setShopStaff(null); });
    return () => { live = false; };
  }, [shop, reload]);
  const staffOnly = useMemo(() => (staffSel && shopStaff
    ? new Set(Object.entries(shopStaff.assign).filter(([, v]) => v === staffSel).map(([k]) => Number(k))) : null), [staffSel, shopStaff]);
  const [group, setGroup] = useState("");
  const [p1, setP1] = useState({ from: "", to: "" });     // Юнитка: первый период (пусто — столько же дней перед вторым)
  const [perUnit, setPerUnit] = useState(false);          // Юнитка: на 1 проданную штуку
  const [adCamp, setAdCamp] = useState<{ id: string; name: string } | null>(null);   // Реклама WB: кампания, ключи которой открыты
  useEffect(() => setAdCamp(null), [shop, tab]);
  const [artGroups, setArtGroups] = useState<{ key: string; title: string; kind: string }[]>([]);
  useEffect(() => {
    if (shop && GROUP_TABS.has(tab)) api.groups(shop).then((g) => {
      setArtGroups(g);
      setGroup((cur) => (cur && g.some((x) => x.key === cur) ? cur : tab !== "dash_group" ? "" : g.find((x) => x.kind === "card")?.key ?? g[0]?.key ?? ""));
    }).catch(() => setArtGroups([]));
  }, [shop, tab, reload]);
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    try { const t = localStorage.getItem("theme"); if (t === "light" || t === "dark") return t; } catch { /* нет хранилища */ }
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("theme", theme); } catch { /* нет хранилища */ }
  }, [theme]);
  const gridTheme = useMemo(() => themeQuartz.withPart(theme === "dark" ? colorSchemeDark : colorSchemeLight), [theme]);

  const loadMe = () => api.me().then((m) => { setMe(m); setNeed(false); setShop((s) => m.shops.some(x => x.id === s) ? s : m.default_shop ?? m.shops[0]?.id ?? null); })
    .catch((e) => (e.message === "401" ? setNeed(true) : setErr(e.message)));
  useEffect(() => { loadMe(); }, []);

  const [helpOff, setHelpOffState] = useState(() => { try { return localStorage.getItem("help_off") === "1"; } catch { return false; } });
  const setHelpOff = (v: boolean) => { setHelpOffState(v); try { localStorage.setItem("help_off", v ? "1" : "0"); } catch { /* приватный режим */ } };
  const [pageLimit, setPageLimit] = useState(0);                 // 0 — по умолчанию (сервер отдаёт 100 строк большой таблицы), -1 — все
  const [srvSort, setSrvSort] = useState<{ field: string; desc: boolean } | null>(null);
  useEffect(() => { setPageLimit(0); setSrvSort(null); }, [shop, tab, from, to, nm, group, staffSel]);
  const tabQ: TabQ = { from, to, nm, group: GROUP_TABS.has(tab) ? group : "", ...(tab === "v2_unit" ? { p1from: p1.from, p1to: p1.to, perUnit } : {}),
    limit: pageLimit || undefined, sort: srvSort?.field, desc: srvSort?.desc, staff: staffSel };
  const { data, loading, error: tabError } = useTabData(shop, tab, tabQ, page === "tab", reload);
  useEffect(() => setErr(""), [shop, tab, page]);
  const partial = !!data?.rows_total && data.rows_total > data.rows.length;
  const [costMissing, setCostMissing] = useState(false);       // лист «Себестоимость»: только товары без себестоимости
  const isCost = data?.editable === "cost";
  const gridRows = isCost && costMissing ? (data?.rows || []).filter((r) => r.cost == null) : data?.rows || [];
  useEffect(() => { if (!loading) fit(); }, [loading, data]);
  useEffect(() => {      // вкладка ещё грузит данные (Джем) — перезапросить сама
    if (!data?.retry) return;
    const t = setTimeout(() => setReload((x) => x + 1), data.retry * 1000);
    return () => clearTimeout(t);
  }, [data]);

  const hasPeriods = !!data?.columns.some((c) => c.metric && c.metric !== "разница");
  // закреплённые столбцы: по вкладке, в браузере пользователя; true — закреплён слева, false — откреплён (в т.ч. закреплённый по умолчанию)
  const [pins, setPins] = useState<Record<string, Record<string, boolean>>>(() => {
    try { return JSON.parse(localStorage.getItem("col_pins") || "{}"); } catch { return {}; }
  });
  const setPin = (field: string, on: boolean) => setPins((cur) => {
    const k = data?.key || tab;
    const n = { ...cur, [k]: { ...(cur[k] || {}), [field]: on } };
    try { localStorage.setItem("col_pins", JSON.stringify(n)); } catch { /* нет хранилища */ }
    return n;
  });
  const [full, setFull] = useState<{ title: string; text: string } | null>(null);   // полный текст ячейки
  const [asOpen, setAsOpen] = useState(false);      // «Стометрик» — чат помощника
  const [gnome, setGnomeRaw] = useState(() => { try { return localStorage.getItem("gnome") !== "0"; } catch { return true; } });
  const [gAct, setGAct] = useState<{ act: string; say: string } | null>(null);   // гномик иногда чем-то занят (первый раз через 5–10 с, дальше раз в 20–40 с, на ~9 с)
  useEffect(() => {
    const fixed = new URLSearchParams(location.search).get("gnome_act");     // проверка: ?gnome_act=laptop — одно занятие без смены
    if (fixed) { setGAct(GNOME_ACTS.find((x) => x.act === fixed) || null); return; }
    let t = 0, first = true;
    const next = () => {
      const wait = first ? 5000 + Math.random() * 5000 : 20000 + Math.random() * 20000;
      first = false;
      t = window.setTimeout(() => {
        if (document.visibilityState === "visible") setGAct(GNOME_ACTS[Math.floor(Math.random() * GNOME_ACTS.length)]);
        t = window.setTimeout(() => { setGAct(null); next(); }, 9000);
      }, wait);
    };
    next();
    return () => window.clearTimeout(t);
  }, []);
  const setGnome = (v: boolean) => { setGnomeRaw(v); try { localStorage.setItem("gnome", v ? "1" : "0"); } catch { /* нет хранилища */ } };
  const [hideChg, setHideChgState] = useState(() => { try { return localStorage.getItem("hide_changes") === "1"; } catch { return false; } });
  const setHideChg = (v: boolean) => { setHideChgState(v); try { localStorage.setItem("hide_changes", v ? "1" : "0"); } catch { /* нет хранилища */ } };
  const isChg = (c: Col) => c.type === "change" || c.metric === "разница";      // столбцы «изм.» / «разница» 
  const hasChg = !!data && (!!data.home || ["rnp", "entry"].includes(String(data.custom)) || (data.columns || []).some(isChg));
  const viewCols = useMemo(() => {
    const base = data?.columns || [];
    const v = stacked && hasPeriods ? stackCols(base) : base;       // «разница» склеивается в ячейку периода — убираем после склейки
    return hideChg ? v.filter((c) => !isChg(c)).map((c) => (c.stack ? { ...c, stack: c.stack.filter((s) => !s.diff) } : c)) : v;
  }, [data, stacked, hasPeriods, hideChg]);   // eslint-disable-line react-hooks/exhaustive-deps
  const expCols = viewCols.flatMap((c) => (c.stack ? c.stack.map((s) => s.field) : [c.field]));    // выгрузка: видимые столбцы по порядку
  const [gBusy, setGBusy] = useState(false);
  const stackLines = Math.max(1, ...viewCols.map((c) => c.stack?.length || 1));
  const cols = useMemo(() => {
    const list = viewCols;
    const out: (ColDef | ColGroupDef)[] = [];
    if (!list.some((c) => c.group !== undefined)) out.push(...list.map(colDef));
    else {
      // группы колонок как в таблице: подпись группы действует до следующей подписи
      let cur: ColGroupDef | null = null;
      for (const c of list) {
        if (c.group) { cur = { headerName: c.group, children: [] }; out.push(cur); }
        if (cur && c.group !== undefined && (c.group || cur)) cur.children.push(colDef(c)); else out.push(colDef(c));
      }
    }
    // сортировка по умолчанию от сервера (2#Сводная — по сумме заказов за 4 недели): строки уже по порядку, показываем стрелку
    const ds = data?.sort;
    if (ds && !srvSort) {
      const mark = (d: ColDef) => { if (d.field === ds.field) d.initialSort = ds.desc ? "desc" : "asc"; };
      for (const d of out) ("children" in d ? (d.children as ColDef[]).forEach(mark) : mark(d as ColDef));
    }
    // заливка «чем больше — тем зеленее»: шкала от min до max внутри группы столбцов (data.heat)
    for (const grp of data?.heat || []) {
      const vals = (data?.rows || []).flatMap((r) => grp.map((f) => Number(r[f]))).filter((x) => Number.isFinite(x));
      if (!vals.length) continue;
      const lo = Math.min(...vals), hi = Math.max(...vals);
      const paint = (d: ColDef) => {
        if (!d.field || !grp.includes(d.field)) return;
        d.cellStyle = (p) => {
          const v = Number(p.value);
          if (p.node.rowPinned || !Number.isFinite(v) || hi <= lo) return null;
          return { backgroundColor: `rgba(22, 163, 74, ${(0.08 + 0.62 * (v - lo) / (hi - lo)).toFixed(3)})` };
        };
      };
      for (const d of out) ("children" in d ? (d.children as ColDef[]).forEach(paint) : paint(d as ColDef));
    }
    // заливка по порогам и градиентом (Джем — правила листа «усл форматирование»)
    const rules = data?.rules || {}, grad = data?.grad || [];
    if (Object.keys(rules).length || grad.length) {
      const top: Record<string, number> = {};
      for (const f of grad) top[f] = Math.max(0, ...(data?.rows || []).map((r) => Number(r[f])).filter((x) => Number.isFinite(x)));
      const paintR = (d: ColDef) => {
        const f = d.field;
        if (!f || (!rules[f] && !grad.includes(f))) return;
        d.cellStyle = (p): CellStyle | undefined => {
          const v = Number(p.value);
          if (p.node.rowPinned || p.value == null || p.value === "" || !Number.isFinite(v) || v === 0) return undefined;
          if (rules[f]) {
            const r = rules[f].find((x) => (x.gt == null || v > x.gt) && (x.le == null || v <= x.le));
            return r ? { backgroundColor: r.color, color: "#1f2937" } : undefined;
          }
          if (!top[f] || v < 0) return undefined;
          const k = v / top[f];      // максимум — зелёный, к минимуму — светлее (#57bb8a → #ffffff)
          const mix = (a: number) => Math.round(255 - (255 - a) * (0.15 + 0.85 * k));
          return { backgroundColor: `rgb(${mix(0x57)}, ${mix(0xbb)}, ${mix(0x8a)})`, color: "#1f2937" };
        };
      };
      for (const d of out) ("children" in d ? (d.children as ColDef[]).forEach(paintR) : paintR(d as ColDef));
    }
    if (data?.cell_colors) {
      const cc = data.cell_colors;
      const paintT = (d: ColDef) => {
        const m = d.field ? cc[d.field] : undefined;
        if (!m) return;
        d.cellStyle = (p): CellStyle | undefined => (p.value != null && m[String(p.value)] ? { backgroundColor: m[String(p.value)], color: "#1f2937", textAlign: "center" } : undefined);
      };
      for (const d of out) ("children" in d ? (d.children as ColDef[]).forEach(paintT) : paintT(d as ColDef));
    }
    if (data && data.layout !== "sheet" && trend !== "none" && COL_TREND_TABS.includes(data.key)) {
      const pairs = colPairs(data.columns);
      const idx = Object.fromEntries(data.columns.map((c, i) => [c.field, i]));
      const rows = data.rows;
      const color = (good: boolean, mag: number): CellStyle =>
        trend === "text" ? { color: good ? "#16a34a" : "#dc2626", fontWeight: "600" }
          : { backgroundColor: `rgba(${good ? "22, 163, 74" : "220, 38, 38"}, ${(0.1 + 0.55 * Math.min(mag, 1)).toFixed(3)})` };
      const paintCol = (d: ColDef) => {
        if (!d.field || idx[d.field] === undefined) return;
        const c = data.columns[idx[d.field]];
        if (!["int", "money", "num", "pct", "share"].includes(c.type)) return;
        const isDiff = c.metric === "разница" || /^разница/i.test(c.title);
        const base = isDiff ? data.columns[idx[d.field] - 1] : c;          // «разница» относится к столбцу слева
        const name = (base?.metric || base?.title || "").split(" · ")[0];
        if (!base || SKIP_COL.test(name)) return;
        const dir = rowDir(name);
        if (!dir) return;
        const key = KEY_COL.test(name);
        if (trend === "fill" && !key) return;
        const prev = pairs[c.field];
        // без пары: шкала от минимума до максимума по артикулам, нули (почти не продавались) не учитываем 
        const nz = !prev && !isDiff ? rows.map((r) => Number(r[c.field])).filter((x) => Number.isFinite(x) && x !== 0) : [];
        const pos = nz.filter((x) => x > 0), neg = nz.filter((x) => x < 0);
        const lo = pos.length ? Math.min(...pos) : 0, hi = pos.length ? Math.max(...pos) : 0;
        const negMax = neg.length ? Math.max(...neg.map(Math.abs)) : 0;
        d.cellStyle = (p): CellStyle | undefined => {
          const r = p.data as Record<string, unknown> | undefined;
          if (!r || p.node.rowPinned) return undefined;
          let v = Number(p.value);
          if (!Number.isFinite(v) || p.value == null) return undefined;
          if (isDiff) {                                                    // знак разницы × смысл показателя
            if (!v) return undefined;
            const older = Number(r[base.field]);   // слева от «разницы» — значение за предыдущий период
            return color(Math.sign(v) * dir > 0, older ? Math.abs(v / older) / 0.5 : 1);
          }
          if (prev) {
            let w = Number(r[prev]);
            if (!Number.isFinite(w) || r[prev] == null || v === w) return undefined;
            if (dir < 0 && v <= 0 && w <= 0) { v = -v; w = -w; }
            const ch = c.type === "pct" || c.type === "share" ? (v - w) * (c.type === "pct" ? 0.1 : 10) : w ? (v - w) / Math.abs(w) : Math.sign(v - w);
            return color(Math.sign(ch) * dir > 0, Math.abs(ch) / 0.5);
          }
          // без пары: заливка — чем больше по модулю, тем ярче (хорошее — зелёным, расход — красным); цифры — красим только минус
          if (trend === "text") return dir > 0 && v < 0 ? { color: "#dc2626", fontWeight: "600" } : undefined;
          if (!v) return undefined;
          if (v < 0) return negMax ? color(dir < 0, Math.abs(v) / negMax) : undefined;   // минус: убыток — красный
          if (hi <= lo) return undefined;
          return color(dir > 0, (v - lo) / (hi - lo));    // хорошее — зеленее к максимуму, расход — краснее к максимуму
        };
      };
      for (const d of out) ("children" in d ? (d.children as ColDef[]).forEach(paintCol) : paintCol(d as ColDef));
    }
    if (data?.layout === "sheet" && trend !== "none") {
      const pairs = trendPairs(data.columns);
      const tint = (d: ColDef) => {
        const prev = d.field && pairs[d.field];
        if (!prev) return;
        d.cellStyle = (p): CellStyle | undefined => {
          const r = p.data as Record<string, unknown> | undefined;
          if (!r || r.fmt === "h") return undefined;
          const dir = rowDir(String(r.label || ""));
          let v = Number(p.value), w = Number(r[prev]);
          if (dir < 0 && v <= 0 && w <= 0) { v = -v; w = -w; }   // расходы в листах со знаком «−»: больше расход = больше по модулю
          if (!dir || !Number.isFinite(v) || !Number.isFinite(w) || v === w || (r[prev] == null)) return undefined;
          const ch = r.fmt === "pct" ? (v - w) * 10 : w ? (v - w) / Math.abs(w) : Math.sign(v - w);   // п.п. ×10 ≈ доля
          const good = Math.sign(ch) * dir > 0;
          if (trend === "text") return { color: good ? "#16a34a" : "#dc2626", fontWeight: "600" };
          if (!KEY_ROW.test(String(r.label || ""))) return undefined;
          const a = (0.1 + 0.55 * Math.min(Math.abs(ch) / 0.5, 1)).toFixed(3);    // ±50 % и больше — самый тёмный
          return { backgroundColor: good ? `rgba(22, 163, 74, ${a})` : `rgba(220, 38, 38, ${a})` };
        };
      };
      for (const d of out) ("children" in d ? (d.children as ColDef[]).forEach(tint) : tint(d as ColDef));
    }
    // PnL: строки/столбцы прибыли — по знаку: плюс зелёный (больше — зеленее), минус красный (больше убыток — темнее) 
    if (data && PNL_TABS.test(data.key)) {
      const isTot = (f: string, t: string) => f === "total" || /^Y\d{4}$/.test(f) || /итого/i.test(t);
      const tot = new Set(data.columns.filter((c) => isTot(c.field, c.title || "")).map((c) => c.field));
      const shade = (v: number, top: number): CellStyle | undefined => {
        if (!v || !top) return undefined;
        const k = Math.min(Math.abs(v) / top, 1);
        const [a, b] = v > 0 ? [[220, 252, 231], [21, 128, 61]] : [[254, 202, 202], [127, 29, 29]];
        const c = a.map((x, i) => Math.round(x + (b[i] - x) * k));
        return { backgroundColor: `rgb(${c.join(", ")})`, color: k > 0.55 ? "#fff" : "#1f2937", fontWeight: "600" };
      };
      if (data.layout === "sheet") {
        const num = data.columns.filter((c) => c.type !== "label" && c.field !== "label").map((c) => c.field);
        const prof = (r: Record<string, unknown>) => /прибыл/i.test(String(r.label || "")) && !/%/.test(String(r.label || "")) && !["pct", "share", "h"].includes(String(r.fmt));
        const tops = new Map<unknown, [number, number]>();
        for (const r of data.rows) if (prof(r)) {
          const vs = num.filter((f) => !tot.has(f)).map((f) => Number(r[f])).filter((x) => Number.isFinite(x));
          tops.set(r, [Math.max(0, ...vs.filter((x) => x > 0)), Math.max(0, ...vs.filter((x) => x < 0).map(Math.abs))]);
        }
        const paintP = (d: ColDef) => {
          if (!d.field || !num.includes(d.field)) return;
          const prev = d.cellStyle;
          d.cellStyle = (p) => {
            const t = tops.get(p.data);
            if (!t) return typeof prev === "function" ? prev(p) : prev;
            const v = Number(p.value);
            return Number.isFinite(v) ? shade(v, v > 0 ? t[0] || v : t[1] || -v) : undefined;
          };
        };
        for (const d of out) ("children" in d ? (d.children as ColDef[]).forEach(paintP) : paintP(d as ColDef));
      } else {
        const pc = data.columns.filter((c) => /прибыл/i.test(c.title || "") && ["money", "num", "int"].includes(c.type)).map((c) => c.field);
        const paintC = (d: ColDef) => {
          if (!d.field || !pc.includes(d.field)) return;
          const vs = data.rows.map((r) => Number(r[d.field!])).filter((x) => Number.isFinite(x));
          const pos = Math.max(0, ...vs.filter((x) => x > 0)), neg = Math.max(0, ...vs.filter((x) => x < 0).map(Math.abs));
          d.cellStyle = (p) => {
            const v = Number(p.value);
            if (p.node.rowPinned || p.value == null || !Number.isFinite(v)) return undefined;
            return shade(v, v > 0 ? pos : neg);
          };
        };
        for (const d of out) ("children" in d ? (d.children as ColDef[]).forEach(paintC) : paintC(d as ColDef));
      }
    }
    // длинный текст (журналы, комментарии): в две строки, ширину можно тянуть, клик по ячейке — весь текст
    const rowsAll = data?.rows || [];
    const long = new Set(viewCols.filter((c) => (!c.type || c.type === "text") &&
      rowsAll.slice(0, 300).some((r) => typeof r[c.field] === "string" && (r[c.field] as string).length > 45)).map((c) => c.field));
    const wrap = (d: ColDef) => {
      if (!d.field || !long.has(d.field)) return;
      Object.assign(d, { wrapText: true, autoHeight: true, cellClass: "clamp2", width: 380, minWidth: 220, maxWidth: 1400, suppressAutoSize: true,
        onCellClicked: (p: { value: unknown }) => p.value != null && String(p.value).length > 45 && setFull({ title: String(d.headerName || ""), text: String(p.value) }) });
    };
    for (const d of out) ("children" in d ? (d.children as ColDef[]).forEach(wrap) : wrap(d as ColDef));
    const my = pins[data?.key || tab] || {};
    const pin = (d: ColDef) => { if (d.field && d.field in my) d.pinned = my[d.field] ? "left" : null; };
    for (const d of out) ("children" in d ? (d.children as ColDef[]).forEach(pin) : pin(d as ColDef));
    return out;
  }, [viewCols, data, trend, pins, tab, srvSort]);
  const pinnedNow = (field: string, type: string) => { const m = pins[data?.key || tab] || {}; return field in m ? m[field] : type === "label"; };
  const totals = useMemo(() => {
    if (data?.total_row && data.rows.length) return [data.total_row];
    if (!data || data.layout === "sheet" || data.plain || !data.rows.length) return undefined;
    const t: Record<string, unknown> = {};
    const first = data.columns.find((c) => c.type === "text" || c.type === "label");
    for (const c of data.columns) {
      if ((c.type === "int" || c.type === "money") && !c.field.endsWith("_id") && c.field !== "nm_id")
        t[c.field] = data.rows.reduce((a, r) => a + (r[c.field] == null ? 0 : Number(r[c.field])), 0);
    }
    if (first) t[first.field] = "ИТОГО";
    return [t];
  }, [data]);
  const inviteTok = window.location.pathname.match(/^\/invite\/([\w-]+)$/)?.[1];
  const magicTok = window.location.pathname.match(/^\/login\/([\w-]+)$/)?.[1];
  if (window.location.pathname.startsWith("/compare")) return <ComparePage />;
  if (window.location.pathname.startsWith("/legal/")) return <LegalPage />;
  if (magicTok) return <MagicPage tok={magicTok} onDone={() => { setNeed(false); loadMe(); }} />;
  if (inviteTok) return <InvitePage tok={inviteTok} onDone={() => { setNeed(false); loadMe(); }} />;
  if (need) return <Login onDone={loadMe} />;
  if (!me) return <div className="center">{err || "Загрузка…"}</div>;
  if (window.location.pathname === "/oauth/authorize") return <OAuthConsent wsId={me.shops.find((s) => s.id === shop)?.workspace_id ?? me.workspaces[0]?.id ?? null} />;

  const shopMp = me.shops.find((s) => s.id === shop)?.marketplace || "wb";
  const isOz = shopMp === "ozon";
  const isYm = shopMp === "ym";
  const allTabs = isOz ? me.oz_tabs : isYm ? me.ym_tabs : me.tabs;     // магазин Ozon / Маркета — свои листы
  const hiddenKeys = me.hidden_tabs?.[shopMp] || [];
  const tabsList = allTabs.filter((t) => !hiddenKeys.includes(t.key) || t.key === tab);   // скрытые — только в меню настройки
  const saveHidden = (keys: string[]) => {
    const mp = shopMp;
    setMe({ ...me, hidden_tabs: { ...(me.hidden_tabs || {}), [mp]: keys } });
    api.setHiddenTabs(mp, keys).catch((e) => setErr(e.message));
  };
  const groups = [...new Set(tabsList.map((t) => t.group))];
  // своя панель вкладок : только выбранные и в своём порядке; остальные — в «Ещё ▾»
  const mpKey = shopMp;
  const barKeys = me.tabbar?.[mpKey] || [];
  const bar = barKeys.map((k) => allTabs.find((t) => t.key === k)).filter((t): t is Tab => !!t);
  const rest = tabsList.filter((t) => !barKeys.includes(t.key));
  const saveBar = (keys: string[]) => {
    setMe({ ...me, tabbar: { ...(me.tabbar || {}), [mpKey]: keys } }); setTbEdit(false);
    api.setTabbar(mpKey, keys).catch((e) => setErr(e.message));
  };
  const wsId = me.shops.find((s) => s.id === shop)?.workspace_id ?? me.workspaces[0]?.id;
  const ws = me.workspaces.find((w) => w.id === wsId);
  const scrollNav = (dx: number) => navRef.current?.scrollBy({ left: dx, behavior: "smooth" });
  return (
    <div className="app">
      {full && <div className="modal-back" onClick={() => setFull(null)}>
        <div className="modal full" onClick={(e) => e.stopPropagation()}>
          <h3>{full.title}</h3>
          <div className="full-text">{full.text}</div>
          <div className="full-btns">
            <button onClick={() => { navigator.clipboard?.writeText(full.text).catch(() => undefined); }}>Копировать</button>
            <button onClick={() => setFull(null)}>Закрыть</button>
          </div>
        </div>
      </div>}
      {me.terms_need && <TermsGate onDone={loadMe} />}
      <Sidebar me={{ ...me, tabs: tabsList }} allTabs={allTabs} hidden={hiddenKeys} onHidden={saveHidden} ws={ws} open={sideOpen} onToggle={() => setSideOpen((x) => !x)} page={page} tab={tab} onTab={openTab}
        onPage={(p) => { setPage(p); if (narrow()) setSideOpen(false); }} theme={theme}
        onTheme={() => setTheme(theme === "dark" ? "light" : "dark")} onLogout={() => api.logout().then(() => setNeed(true))}
        onAssistant={() => { setAsOpen((x) => !x); if (narrow()) setSideOpen(false); }} />
      {gnome && !asOpen && shop && <button className={"gnome-fab" + (gAct ? " busy" : "")} title="Стометрик — спроси про свой магазин" onClick={() => setAsOpen(true)}>
        <Gnome size={64} act={gAct?.act} /><span className="gnome-hi">{gAct?.say || "Спроси меня!"}</span>
        <span className="gnome-x" title="Скрыть гномика (вернуть — в чате Стометрика или пункт меню)" onClick={(e) => { e.stopPropagation(); setGnome(false); }}>×</span>
      </button>}
      <Assistant shop={shop} open={asOpen} onClose={() => setAsOpen(false)} gnome={gnome} onGnome={setGnome} />
      {sideOpen && <div className="side-shade" onClick={() => setSideOpen(false)} />}
      <div className="body">
      <header>
        <button className="burger-m" title="Меню" onClick={() => setSideOpen(true)}>☰</button>
        <select value={shop ?? ""} onChange={(e) => { setShop(Number(e.target.value)); setNm(""); }}>   {/* артикулы другого магазина не переносим */}
          {me.shops.map((s) => <option key={s.id} value={s.id}>{s.marketplace === "ozon" ? "🔵 Ozon" : s.marketplace === "ym" ? "🟡 Маркет" : "🟣 WB"} · {s.title || s.name}</option>)}
        </select>
        <label>с <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
        <label>по <input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
        {shopStaff && shopStaff.staff.some((s) => s.n > 0) && (
          <select title="Менеджер: все вкладки — по его артикулам этого магазина" value={staffSel ?? ""}
            onChange={(e) => { setStaffSel(e.target.value ? Number(e.target.value) : null); setNm(""); }}>
            <option value="">👤 Все менеджеры</option>
            {shopStaff.staff.filter((s) => s.n > 0).map((s) => <option key={s.id} value={s.id}>👤 {s.name}{s.id === shopStaff.me ? " (я)" : ""} · {s.n}</option>)}
          </select>)}
        {shop && <ArtPicker shop={shop} value={nm} onChange={setNm} only={staffOnly} />}
        {hasPeriods && (
          <select title="Как показывать вчера / позавчера / разницу" value={stacked ? "1" : "0"} onChange={(e) => setStacked(e.target.value === "1")}>
            <option value="0">Периоды: столбцами</option>
            <option value="1">Периоды: в одной ячейке</option>
          </select>
        )}
        {(data?.layout === "sheet" || (data && COL_TREND_TABS.includes(data.key))) && (
          <select title="Раскраска к предыдущему периоду (день к дню, неделя к неделе…)" value={trend} onChange={(e) => setTrend(e.target.value as TrendMode)}>
            <option value="none">Цвета: как есть</option>
            <option value="fill">{data?.layout === "sheet" ? "Цвета: заливка ключевых строк" : "Цвета: заливка ключевых столбцов"}</option>
            <option value="text">Цвета: рост/падение цветом цифр</option>
          </select>
        )}
        {hasChg && <label className="chk top-chk" title="Показывать столбцы изменений: «изм.», «разница», динамику и % к прошлому периоду">
          <input type="checkbox" checked={!hideChg} onChange={(e) => setHideChg(!e.target.checked)} /> % изменения</label>}
        {data && !data.home && !data.custom && !data.form && viewCols.length > 1 && (
          <details className="pin-pick">
            <summary title="Закрепить столбцы слева: они не уезжают при прокрутке вправо">📌 Закрепить ({viewCols.filter((c) => pinnedNow(c.field, c.type)).length})</summary>
            <div className="pin-list">
              {viewCols.map((c, i) => (
                <label key={c.field}><input type="checkbox" checked={pinnedNow(c.field, c.type)} onChange={(e) => setPin(c.field, e.target.checked)} />
                  {" "}{c.group ? `${c.group} · ` : ""}{c.title === "%" && i ? `${viewCols[i - 1].title}, %` : c.title || c.field}</label>))}
              <button onClick={() => setPins((cur) => { const n = { ...cur }; delete n[data.key]; try { localStorage.setItem("col_pins", JSON.stringify(n)); } catch { /* */ } return n; })}>Сбросить</button>
            </div>
          </details>
        )}
        {shop && data && !data.custom && !data.form && data.columns.length > 0 && data.key === tab && <>
          <a className="btn" title="Скачать эту таблицу в Excel (.xlsx): те же фильтры и столбцы, все строки"
            href={api.tabXlsx(shop, tab, tabQ, expCols)}>⬇ Excel</a>
          {me?.gsheet && <button disabled={gBusy} title="Создать Google Таблицу с этой вкладкой (те же фильтры и столбцы, все строки); доступ — на вашу почту"
            onClick={() => {
              const w = window.open("", "_blank");        // окно — сразу по нажатию (иначе Safari блокирует)
              setGBusy(true);
              api.tabGsheet(shop, tab, tabQ, expCols).then((r) => {
                if (w) w.location.href = r.url; else window.open(r.url, "_blank");
                if (r.note) alert(r.note);
              }).catch((e) => { w?.close(); alert(e.message); }).finally(() => setGBusy(false));
            }}>{gBusy ? "Создаю таблицу…" : "📗 Google Таблица"}</button>}
        </>}
        <select title="Ширина столбцов таблицы" value={colMode} onChange={(e) => setColMode(e.target.value as ColMode)}>
          <option value="auto">Столбцы: по содержимому</option>
          <option value="narrow">Столбцы: узкие</option>
          <option value="wide">Столбцы: широкие</option>
        </select>
        {GROUP_TABS.has(tab) && (
          <select value={group} onChange={(e) => setGroup(e.target.value)}>
            <option value="">{tab === "dash_group" ? "— группа —" : "— все товары (склейка не выбрана) —"}</option>
            {artGroups.some((g) => g.kind === "own") && <optgroup label="Мои группы">
              {artGroups.filter((g) => g.kind === "own").map((g) => <option key={g.key} value={g.key}>{g.title}</option>)}</optgroup>}
            <optgroup label={tab === "dash_group" ? "Карточки WB (артикулы одной карточки)" : "Модели Ozon (SKU одной модели)"}>
              {artGroups.filter((g) => g.kind === "card").map((g) => <option key={g.key} value={g.key}>{g.title}</option>)}</optgroup>
          </select>
        )}
      </header>
      <div className="tabbar">
        <button className="tb-arrow" title="Назад" onClick={() => scrollNav(-400)}>‹</button>
        <nav ref={navRef} onWheel={(e) => { if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) e.currentTarget.scrollLeft += e.deltaY; }}>
          {bar.length ? <div className="grp">
            {bar.map((t) => (
              <button key={t.key} className={page === "tab" && t.key === tab ? "on" : ""} title={t.help || t.title} onClick={() => openTab(t.key)}>{t.title}</button>))}
            {page === "tab" && !barKeys.includes(tab) && allTabs.some((t) => t.key === tab) &&
              <button className="on" title="Открыта из «Ещё» — на панели её нет">{allTabs.find((t) => t.key === tab)!.title}</button>}
          </div> : groups.map((g) => (
            <div key={g} className="grp"><span>{g}</span>
              {tabsList.filter((t) => t.group === g).map((t) => (
                <button key={t.key} className={page === "tab" && t.key === tab ? "on" : ""} title={t.help || t.title} onClick={() => openTab(t.key)}>{t.title}</button>
              ))}
            </div>
          ))}
        </nav>
        <button className="tb-arrow" title="Вперёд" onClick={() => scrollNav(400)}>›</button>
        {bar.length > 0 && rest.length > 0 && <div className="tb-more">
          <button className="tb-btn" onClick={() => setMore(!more)} title="Вкладки, которых нет на панели">Ещё ▾</button>
          {more && <><div className="tb-more-shade" onClick={() => setMore(false)} />
            <div className="tb-more-pop">{[...new Set(rest.map((t) => t.group))].map((g) => <div key={g}>
              <div className="tbe-g">{g}</div>
              {rest.filter((t) => t.group === g).map((t) => <button key={t.key} className={t.key === tab ? "on" : ""}
                onClick={() => { openTab(t.key); setMore(false); }}>{t.title}</button>)}</div>)}</div></>}
        </div>}
        <button className="tb-btn" title="Настроить панель: какие вкладки показывать и в каком порядке" onClick={() => setTbEdit(true)}>⚙</button>
        {tbEdit && <TabBarEdit all={tabsList} keys={barKeys} onSave={saveBar} onClose={() => setTbEdit(false)} />}
      </div>
      <main>
        {(page === "account" || page === "members") && wsId && <Account key={`account:${wsId}`} me={me} wsId={wsId} page={page} onChanged={loadMe} />}
        {page === "calendar" && wsId && <Calendar key={`calendar:${wsId}:${calendarDay || ''}`} wsId={wsId} workspaces={me.workspaces} initialDay={calendarDay} />}
        {page === "billing" && wsId && <Billing wsId={wsId} />}
        {page === "ai" && wsId && <AiLinks wsId={wsId} />}
        {page === "referral" && <Referral />}
        {page === "admin" && me.user.superadmin && <Admin onShopsChanged={loadMe} />}
        {page === "about" && <AboutPage />}
        {page === "service_news" && <ServiceNews tabTitle={(k) => allTabs.find((t) => t.key === k)?.title || null} onTab={openTab}
          onSeen={() => setMe((m) => m && { ...m, news_unread: 0 })} />}
        {page === "reviews" && shop && (isYm ? <div className="hint">Отзывы Яндекс Маркета — позже. Выберите магазин WB или Ozon.</div>
          : <Reviews shop={shop} onSettings={() => setPage("actions")} />)}
        {page === "questions" && shop && (isOz || isYm ? <div className="hint">Вопросы пока только для WB. Выберите магазин WB.</div>
          : <Questions shop={shop} onSettings={() => setPage("actions")} />)}
        {page === "actions" && shop && (isYm ? <div className="hint">Взаимодействия с кабинетом Яндекс Маркета — позже. Магазин Маркета пока только для аналитики.</div>
          : <Actions shop={shop} />)}
        {page === "total" && <Total dark={theme === "dark"} />}
        {page === "warehouse" && <Warehouse />}
        {page === "kb" && wsId && <Kb wsId={wsId} />}
        {page === "ads" && shop && (isOz || isYm ? <div className="hint">Управление рекламой Ozon — следующим шагом. Выберите магазин WB.</div>
          : <Ads shop={shop} onSettings={() => setPage("actions")} />)}
        {page === "seo" && shop && (isOz || isYm ? <div className="hint">SEO пока только для магазинов WB. Выберите магазин WB.</div> : <SeoBlock shop={shop} />)}
        {page === "visual" && shop && (isOz || isYm ? <div className="hint">Визуал пока только для магазинов WB. Выберите магазин WB.</div> : <VisualBlock shop={shop} />)}
        {page === "cards" && shop && (isOz || isYm ? <div className="hint">Редактирование карточек Ozon — позже. Выберите магазин WB.</div>
          : <Cards shop={shop} initNm={cardsNm} onSettings={() => setPage("actions")} />)}
        {page === "tab" && <>
        {tabsList.find((t) => t.key === tab)?.help && (helpOff
          ? <button className="link help-toggle" onClick={() => setHelpOff(false)} title="Показать описание вкладки">ℹ️ описание</button>
          : <div className="tab-help">ℹ️ {tabsList.find((t) => t.key === tab)?.help}
            <button className="link help-toggle" onClick={() => setHelpOff(true)} title="Скрыть описания вкладок (вернуть — «ℹ️ описание»)">скрыть</button></div>)}
        {err && <div className="err">{err}</div>}
        {tabError && <div className="err" role="alert">{tabError} <button onClick={() => setReload((x) => x + 1)}>Повторить загрузку</button></div>}
        {loading && <div className="hint" role="status">Загружаю «{tabsList.find((t) => t.key === tab)?.title || tab}»…</div>}
        {data?.note && data.key === tab && <div className="hint">ℹ️ {data.note}</div>}
        {data?.unit && data.key === tab && <div className="unit-per">
          <div><b>Первый период</b>
            <input type="date" value={p1.from || data.unit.p1_from} onChange={(e) => setP1({ from: e.target.value, to: p1.to || data.unit!.p1_to })} />
            <input type="date" value={p1.to || data.unit.p1_to} onChange={(e) => setP1({ from: p1.from || data.unit!.p1_from, to: e.target.value })} /></div>
          <div><b>Второй период</b>
            <input type="date" value={data.unit.p2_from} onChange={(e) => setFrom(e.target.value)} />
            <input type="date" value={data.unit.p2_to} onChange={(e) => setTo(e.target.value)} /></div>
          <label><input type="checkbox" checked={perUnit} onChange={(e) => setPerUnit(e.target.checked)} /> На 1 шт</label>
          {p1.from && <button className="link" onClick={() => setP1({ from: "", to: "" })}>Период 1 — авто</button>}
        </div>}
        {data?.stale && <div className="hint">Пришли новые данные — показан расчёт на {new Date(data.cached_at!).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}, свежий считается (обновите страницу через минуту).</div>}
        {data?.dangers && shop && <ChecklistTop shop={shop} dangers={data.dangers} editor={data.max_editor} onSaved={() => setReload((x) => x + 1)} />}
        {data && data.form === "tax" && shop && <TaxForm shop={shop} data={data} onSaved={() => setReload((x) => x + 1)} />}
        {data?.switch && data.key === tab && shop && <div className="row tab-switch"><b>{data.switch.title}:</b>
          {data.switch.options.map(([v, t]) => <label key={v}><input type="radio" name={data.switch!.key} checked={data.switch!.value === v}
            onChange={() => api.setPref(shop, data.switch!.key, { mode: v }).then(() => setReload((x) => x + 1))} /> {t}</label>)}</div>}
        {data && data.layout_editor && shop && (
          <LayoutEditor data={data} onSave={(v) => api.setPref(shop, data.layout_editor!, v).then(() => setReload((x) => x + 1))} />
        )}
        {data && data.layout !== "sheet" && !data.form && !data.custom && !data.plain && <ChartPanel data={data} dark={theme === "dark"} />}
        {tab === "home" && data?.home && shop && <HomeTasks key={`tasks:${shop}`} shop={shop} />}
        {tab === "home" && wsId && <HomeCalendar key={`calendar-due:${wsId}:${me.user.id}`} wsId={wsId} onOpen={day => { setCalendarDay(day); setPage("calendar"); }} />}
        {tab === "home" && data?.home && shop && <HomeAI key={`reports:${shop}`} shop={shop} />}
        {tab === "home" && data?.home && <Home data={data} hideChg={hideChg} />}
        {shop && data?.custom === "actions" && data.key === tab && <ActionsBoard shop={shop}
          shops={me.shops.filter((x) => x.workspace_id === wsId).map((x) => ({ id: x.id, title: x.title || x.name }))} />}
        {shop && data?.custom === "prices" && data.key === tab && <PriceLab shop={shop} />}
        {shop && data?.custom === "competitors" && data.key === tab && <Competitors shop={shop} />}
        {shop && data?.custom === "insights" && data.key === tab && <Insights shop={shop} staff={staffSel} />}
        {shop && data?.custom === "planning" && data.key === tab && <Planning shop={shop} />}
        {shop && data?.custom === "exclusions" && data.key === tab && <Exclusions shop={shop} />}
        {shop && data?.custom === "staff" && data.key === tab && <Staff shop={shop} onChange={() => api.shopStaff(shop).then(setShopStaff).catch(() => {})} />}
        {shop && data?.custom === "photos" && data.key === tab && <PhotoFunnel shop={shop} />}
        {shop && data?.custom === "rnp" && data.key === tab && <Rnp shop={shop} hideChg={hideChg} nm={nm} staff={staffSel} />}
        {shop && data?.custom === "news" && data.key === tab && <News shop={shop} />}
        {shop && data?.custom === "entry" && data.key === tab && <EntryPoints shop={shop} nm={nm} hideChg={hideChg} />}
        {shop && data?.custom === "ext_costs" && data.key === tab && <ExtCosts shop={shop} />}
        {shop && data?.custom === "mrc" && data.key === tab && <Mrc shop={shop} />}
        {shop && data?.custom === "shelves" && data.key === tab && <Shelves shop={shop} />}
        {shop && data?.custom === "promo" && data.key === tab && <Promo shop={shop} />}
        {shop && data?.custom === "hypotheses" && data.key === tab && <Hypotheses shop={shop} />}
        {shop && data?.custom === "seo" && data.key === tab && <Seo shop={shop} nm={nm} />}
        {data && !data.custom && !data.home && !loading && !data.rows.length && data.empty && <div className="hint">{data.empty}</div>}
        {data && AD_TABS[data.key] && tab === data.key && <div className="hint">👇 Нажмите на кампанию — ниже откроется подробно: {AD_TABS[data.key].map((x) => x[1].slice(3).toLowerCase()).join(" и ")} со статистикой за период.</div>}
        {shop && data && isCost && tab === data.key && <CostBar shop={shop} total={data.rows.length} missing={data.rows.filter((r) => r.cost == null).length}
          onlyMissing={costMissing} setOnlyMissing={setCostMissing} onDone={() => setReload((x) => x + 1)} />}
        {data && partial && !data.custom && <div className="page-bar hint">Показаны {data.rows.length} из {data.rows_total} строк (ИТОГО — по всем; сортировка по столбцу — по всем строкам).
          <button disabled={loading} onClick={() => setPageLimit(data.rows.length + 100)}>Показать ещё 100</button>
          <button disabled={loading} onClick={() => setPageLimit(-1)}>Показать все</button></div>}
        <div ref={gridBox} className={"grid cols-" + colMode} style={data?.home || data?.custom ? { display: "none" } : data && AD_TABS[data.key] ? { height: "45vh", minHeight: 300 } : undefined}>
          <AgGridReact ref={gridRef} key={colMode + (stacked ? "s" : "") + trend} theme={gridTheme}
            onSortChanged={(e) => {   // часть строк: сортирует сервер по всем строкам
              if (!partial && !srvSort) return;
              const s = e.api.getColumnState().find((x) => x.sort);
              const next = s?.colId ? { field: s.colId, desc: s.sort === "desc" } : null;
              if (JSON.stringify(next) !== JSON.stringify(srvSort)) setSrvSort(next);
            }} rowHeight={stackLines > 1 ? 10 + 18 * stackLines : undefined} onFirstDataRendered={fit} onRowDataUpdated={fit} onGridColumnsChanged={fit} rowData={gridRows} columnDefs={cols} loading={loading} pinnedTopRowData={totals}
            defaultColDef={defCol} enableCellTextSelection
            suppressColumnVirtualisation={colMode === "auto"} /* «по содержимому»: мерить и столбцы за краем экрана (телефон, Example 20.10) */
            onCellValueChanged={(e) => {
              if ((data?.key === "cost" || data?.key === "oz_cost") && shop && e.colDef.field === "group_name")
                api.setGroup(shop, Number(e.data.nm_id), String(e.newValue ?? "")).then(() => setErr("")).catch((x) => setErr("Не сохранилось: " + x.message));
              if (data?.key === "unit_wb" && shop && (e.colDef.field === "marking" || e.colDef.field === "extra")) {
                const v = String(e.newValue ?? "").replace(",", ".").trim();
                http.put(`/api/shops/${shop}/unit_extra`, { nm_id: Number(e.data.nm_id), field: e.colDef.field, value: v ? Number(v) : null })
                  .then(() => { setErr(""); setReload((x) => x + 1); }).catch((x) => setErr("Не сохранилось: " + x.message));
              }
              if (data?.key === "v2_check" && shop && e.colDef.field)
                http.put(`/api/shops/${shop}/checklist`, { day: e.data.day, sku: Number(e.data.nm_id), field: e.colDef.field, value: String(e.newValue ?? "") })
                  .then(() => setErr("")).catch((x) => setErr("Не сохранилось: " + x.message));
              if ((data?.key === "cost" || data?.key === "oz_cost") && shop && e.colDef.field === "cost")
                api.setCost(shop, Number(e.data.nm_id), Number(e.newValue)).then(() => setErr("")).catch((x) => setErr("Не сохранилось: " + x.message));
            }} pagination={data?.layout !== "sheet" && !data?.rows_total} paginationPageSize={100}
            onRowClicked={(e) => { if (data && AD_TABS[data.key] && e.data?.advert_id) setAdCamp({ id: String(e.data.advert_id), name: String(e.data.name || "") }); }} />
        </div>
        {data && partial && !data.custom && <div className="page-bar hint">Показаны {data.rows.length} из {data.rows_total}.
          <button disabled={loading} onClick={() => setPageLimit(data.rows.length + 100)}>Показать ещё 100</button>
          <button disabled={loading} onClick={() => setPageLimit(-1)}>Показать все</button></div>}
        {shop && data && AD_TABS[data.key] && tab === data.key && adCamp && <AdKeys key={data.key} parent={data.key} shop={shop} from={from} to={to} nm={nm} camp={adCamp} theme={gridTheme} onClose={() => setAdCamp(null)} />}
        </>}
      </main>
      </div>
    </div>
  );
}
