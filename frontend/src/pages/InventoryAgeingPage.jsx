import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";

const inr = (value) => new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(Number(value || 0));

export default function InventoryAgeingPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("All");

  useEffect(() => { api.inventoryAgeing().then(setData).catch((e) => setError(e.message)); }, []);
  const rows = useMemo(() => (data?.items || []).filter((x) => filter === "All" || x.age_status === filter), [data, filter]);

  if (error) return <div className="err-banner">{error}</div>;
  if (!data) return <div className="state">Loading inventory ageing…</div>;
  const money = (v) => inr(v);
  return <div>
    <div className="topbar"><div><p className="eyebrow">Slow-moving stock monitor</p><h2 className="page-title">Inventory Ageing</h2><p className="sub">Track stock age using recorded stock receipts or the optional age entered when adding opening stock. Unknown dates remain Needs data.</p></div>
      <select className="btn" value={filter} onChange={(e) => setFilter(e.target.value)}><option>All</option><option>Fresh</option><option>Ageing</option><option>Old</option><option>Needs data</option></select>
    </div>
    <section className="grid" style={{gridTemplateColumns:"repeat(auto-fit,minmax(160px,1fr))",gap:12,marginBottom:16}}>
      <div className="card"><p className="eyebrow">Tracked rows</p><h2>{data.summary.tracked}</h2></div>
      <div className="card"><p className="eyebrow">Ageing / old rows</p><h2>{data.summary.ageing_or_old}</h2></div>
      <div className="card"><p className="eyebrow">Inventory value at risk</p><h2>{money(data.summary.value_at_risk)}</h2></div>
      <div className="card"><p className="eyebrow">Needs date data</p><h2>{data.summary.needs_data}</h2></div>
    </section>
    <p className="muted" style={{marginBottom:12}}>{data.ageing_policy} As of {data.as_of}.</p>
    <section className="card"><div style={{overflowX:"auto"}}><table><thead><tr><th>Product</th><th>Store</th><th>On hand</th><th>Age</th><th>Status</th><th>Stock value</th><th>Value at risk</th><th>Evidence</th></tr></thead><tbody>
      {rows.map((x) => <tr key={`${x.product_id}-${x.store_id}`}><td><strong>{x.product_name}</strong><div className="muted">{x.sku}</div></td><td>{x.store_name}<div className="muted">{x.city}</div></td><td className="mono">{x.quantity}</td><td>{x.stock_age_days == null ? "—" : `${x.stock_age_days} days`}</td><td><span className={`pos-stock-badge ${x.age_status === "Old" ? "out_of_stock" : x.age_status === "Ageing" ? "low_stock" : "in_stock"}`}>{x.age_status}</span></td><td>{money(x.inventory_value)}</td><td>{x.value_at_risk ? money(x.value_at_risk) : "—"}</td><td className="muted">{x.age_source}</td></tr>)}
      {!rows.length && <tr><td colSpan="8">No inventory rows match this filter.</td></tr>}
    </tbody></table></div></section>
    <p className="muted" style={{marginTop:12}}>Age uses a manually entered opening-stock age when supplied; otherwise it uses the earliest recorded stock-in movement per product/store. It is not batch-level FIFO. Value at risk is a screening estimate using on-hand quantity × unit cost for stock aged 30+ days; review before taking action.</p>
  </div>;
}
