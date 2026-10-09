import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";

export default function InventoryPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [productId, setProductId] = useState("");

  useEffect(() => {
    api
      .inventory()
      .then((payload) => {
        setData(payload);
        const tv = payload.products.find((p) => p.sku === "VK-TV-55");
        setProductId(String(tv ? tv.id : payload.products[0]?.id || ""));
      })
      .catch((err) => setError(err.message));
  }, []);

  const rows = useMemo(() => {
    if (!data) return [];
    return data.items.filter((i) => !productId || String(i.product_id) === productId);
  }, [data, productId]);

  if (error) return <div className="err-banner">{error}</div>;
  if (!data) return <div className="state">Loading network inventory…</div>;

  return (
    <div>
      <div className="topbar">
        <div>
          <p className="eyebrow">Multi-store view</p>
          <h2 className="page-title">Inventory network</h2>
          <p className="sub">
            Compare stock cover across stores before buying. Transfer-before-purchase starts here:
            surplus in one city can cover a festival stockout in another.
          </p>
        </div>
        <select className="btn" value={productId} onChange={(e) => setProductId(e.target.value)}>
          {data.products.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
      </div>
      <section className="card">
        <table>
          <thead>
            <tr>
              <th>Store</th>
              <th>On hand</th>
              <th>Stock status</th>
              <th>Velocity / day</th>
              <th>Cover</th>
              <th>Days on hand</th>
              <th>Markdown review</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>
                  <strong>{row.store_name}</strong>
                  <div className="muted">{row.city} · {row.region}</div>
                </td>
                <td className="mono">{row.quantity}</td>
                <td><span className={`pos-stock-badge ${row.stock_status || (row.quantity <= 0 ? "out_of_stock" : row.quantity <= 3 ? "low_stock" : "in_stock")}`}>{row.stock_status_label || (row.quantity <= 0 ? "Out of stock" : row.quantity <= 3 ? "Low stock" : "In stock")}</span></td>
                <td className="mono">{Number(row.velocity).toFixed(2)}</td>
                <td>{row.cover_days === null ? "n/a (no sales)" : `${row.cover_days} days`}</td>
                <td>{row.days_on_hand}</td>
                <td>{row.markdown_review ? "Yes" : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
