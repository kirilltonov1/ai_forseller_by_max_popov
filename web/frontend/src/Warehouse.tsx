import { useEffect, useState } from "react";
import { http } from "./api";
import "./Warehouse.css";

type Channel = { source_shop_id:number; shop_id:number; shop:string; skus:string[]; stock:number|null; daily:number|null; in_transit:number; days_left:number|null; need:number|null; allocated:number; stale:boolean };
type Product = { id:number; sku:string; title:string; own:number; fulfillment:number; incoming:number; reserved:number; sent:number; to_ship:number; shortage:number; channels:Channel[] };
type Data = { generated_at:string; source_url:string; products:Product[]; links:Record<string,number>; source_shops:{id:number;name:string;marketplace:string}[]; shops:{id:number;title:string;marketplace:string}[]; errors:{shop:string;message:string}[]; unmatched:{shop:string;sku:string;reason:string}[] };
const fmt=(n:number|null)=>n==null?"—":new Intl.NumberFormat("ru-RU",{maximumFractionDigits:1}).format(n);
export function Warehouse(){
 const [data,setData]=useState<Data|null>(null),[error,setError]=useState(""),[busy,setBusy]=useState(false);
 const [days,setDays]=useState(28),[lead,setLead]=useState(7),[q,setQ]=useState(""),[onlyNeed,setOnlyNeed]=useState(false);
 const [revision,setRevision]=useState(0);
 useEffect(()=>{
   let alive=true,loading=false;
   const load=async()=>{if(loading)return;loading=true;setBusy(true);try{const d=await http.get<Data>(`/api/warehouse?target_days=${days}&lead_days=${lead}`);if(alive){setData(d);setError("");}}catch(e){if(alive){setError(String(e));setData(null);}}finally{loading=false;if(alive)setBusy(false);}};
   void load();const id=setInterval(()=>void load(),60000);return()=>{alive=false;clearInterval(id);};
 },[days,lead,revision]);
 const link=async(source:number,dest:number)=>{try{await http.put("/api/warehouse/link",{source_shop_id:source,shop_id:dest});setRevision(x=>x+1);}catch(e){setError(String(e));}};
 const products=(data?.products||[]).filter(p=>(!q||`${p.sku} ${p.title}`.toLowerCase().includes(q.toLowerCase()))&&(!onlyNeed||p.channels.some(c=>(c.need||0)>0)));
 const exportPlan=()=>{
   if(!data)return;
   const safe=(s:unknown)=>'"'+String(s??'').replace(/^[=+@-]/,"'$&").replace(/"/g,'""')+'"';
   const rows=[["Артикул склада","Товар","Магазин","Артикулы магазина","Рекомендовано отправить, шт","Потребность, шт","Снимок склада"]];
   products.forEach(p=>p.channels.filter(c=>c.allocated>0&&!c.stale).forEach(c=>rows.push([p.sku,p.title,c.shop,c.skus.join(", "),String(c.allocated),String(c.need),data.generated_at])));
   const url=URL.createObjectURL(new Blob(['\uFEFF'+rows.map(r=>r.map(safe).join(';')).join('\r\n')],{type:'text/csv;charset=utf-8'}));
   const a=document.createElement('a');a.href=url;a.download='plan-postavok.csv';a.click();URL.revokeObjectURL(url);
 };
 return <section className="warehouse-page">
   <div className="warehouse-heading"><div><h1>Общий склад и поставки</h1><p>Остатки из Viper Склад · спрос и остатки магазинов из ai-for-seller</p></div><button onClick={()=>setRevision(x=>x+1)} disabled={busy}>{busy?"Обновляем…":"Обновить"}</button></div>
   {error&&<div role="alert" className="warehouse-alert">{error.replace(/^Error: /,"")}</div>}
   {data&&<>
    <div className="warehouse-cards">
     {[["Свободно на нашем складе",data.products.reduce((s,p)=>s+p.own,0)],["На фулфилменте",data.products.reduce((s,p)=>s+p.fulfillment,0)],["Зарезервировано / отправлено",data.products.reduce((s,p)=>s+p.reserved+p.sent,0)],["Ожидаем от поставщиков",data.products.reduce((s,p)=>s+p.incoming,0)]].map(([name,value])=><div key={String(name)}><small>{name}</small><strong>{fmt(Number(value))} <span>шт.</span></strong></div>)}
    </div>
    <div className="warehouse-meta">Снимок склада: {new Date(data.generated_at).toLocaleString("ru-RU")} · обновление каждую минуту при открытом разделе. <a href={data.source_url} target="_blank" rel="noreferrer">Открыть склад →</a></div>
    <details className="warehouse-settings" open={data.source_shops.some(s=>!data.links[s.id])}><summary>Связи магазинов · {Object.keys(data.links).length} из {data.source_shops.length}</summary>
     <p>Совпадающие кабинеты связываются по идентификатору продавца. Для остальных выберите соответствие. Товары сопоставляются по точному артикулу магазина из CRM.</p>
     {data.source_shops.map(s=><label key={s.id}>{s.marketplace} · {s.name}<select value={data.links[s.id]||""} onChange={e=>e.target.value&&void link(s.id,Number(e.target.value))}><option value="" disabled>Выбрать магазин аналитики</option>{data.shops.filter(d=>d.marketplace===s.marketplace.toLowerCase()).map(d=><option key={d.id} value={d.id}>{d.title}</option>)}</select></label>)}
    </details>
    {data.errors.map(e=><div key={e.shop} className="warehouse-alert">{e.shop}: {e.message}</div>)}
    <div className="warehouse-toolbar"><input placeholder="Найти товар или артикул" value={q} onChange={e=>setQ(e.target.value)}/><label>Запас на <input type="number" min={1} max={180} value={days} onChange={e=>{const n=Number(e.target.value);if(n>=1&&n<=180)setDays(n);}}/> дней</label><label>Доставка <input type="number" min={0} max={90} value={lead} onChange={e=>{const n=Number(e.target.value);if(n>=0&&n<=90)setLead(n);}}/> дней</label><label><input type="checkbox" checked={onlyNeed} onChange={e=>setOnlyNeed(e.target.checked)}/>Только к пополнению</label><button onClick={exportPlan}>Скачать план CSV</button></div>
    <p className="warehouse-note">Потребность = спрос в день × (запас + доставка) − доступный остаток магазина − уже запланированные FBO-поставки. Свободный склад распределяется один раз, в первую очередь магазинам с меньшим запасом в днях. Резерв в CRM уже вычтен. Будущие закупки и фулфилмент не входят в свободный запас для отправки.</p>
    <div className="warehouse-table"><table><thead><tr><th>Товар / магазин</th><th>Свободно у нас</th><th>Остаток магазина</th><th>Спрос / день</th><th>Хватит дней</th><th>Уже в поставках</th><th>Нужно</th><th>Отправить</th></tr></thead><tbody>
      {products.map(p=><ProductRows key={p.id} product={p}/>)}
    </tbody></table>{!products.length&&<p>Нет товаров по выбранному фильтру.</p>}</div>
    <p className="warehouse-note">WB: заказы в день при наличии из текущего отчёта аналитики; Ozon: заказы минус отмены за последние 28 полных дней / 28. Это прогноз, а не гарантированный срок. «—» означает отсутствие расчёта. Устаревшие отчёты не создают рекомендации к отправке. План CSV не резервирует товар: отправки оформляются в CRM.</p>
    {data.unmatched.length>0&&<details className="warehouse-settings"><summary>Не связаны с товаром склада: {data.unmatched.length}</summary><p>Исправьте связь артикулов в CRM. Эти позиции не включены в план.</p>{data.unmatched.map((r,i)=><div key={i}>{r.shop} · {r.sku} — {r.reason}</div>)}</details>}
   </>}
 </section>;
}
function ProductRows({product:p}:{product:Product}){return <>
 <tr className="warehouse-product"><td><b>{p.sku}</b><small>{p.title}</small></td><td>{fmt(p.own)}</td><td colSpan={4}><small>Ожидаем закупок: {fmt(p.incoming)} · фулфилмент: {fmt(p.fulfillment)} · резерв: {fmt(p.reserved)} · отправлено: {fmt(p.sent)}</small></td><td>{p.shortage>0?<small>Не хватает {fmt(p.shortage)}</small>:""}</td><td><b>{fmt(p.to_ship)}</b></td></tr>
 {p.channels.map(c=><tr key={c.shop_id} className={c.days_left!=null&&c.days_left<7?"warehouse-urgent":""}><td>↳ {c.shop}<small>{c.skus.join(", ")}{c.stale?" · отчёт обновляется":""}</small></td><td>—</td><td>{fmt(c.stock)}</td><td>{fmt(c.daily)}</td><td>{fmt(c.days_left)}</td><td>{fmt(c.in_transit)}</td><td>{fmt(c.need)}</td><td><b>{c.stale?"—":fmt(c.allocated)}</b></td></tr>)}
 {!p.channels.length&&<tr><td colSpan={8}><small>Нет связанных данных спроса. Проверьте соответствие магазинов и артикулов.</small></td></tr>}
 </>;}
