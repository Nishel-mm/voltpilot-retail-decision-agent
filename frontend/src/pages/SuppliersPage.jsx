import { useEffect, useMemo, useState } from "react";
import { AlertCircle, CheckCircle2, Clock3, FileText, RefreshCw, Send, Truck } from "lucide-react";
import { api, inrExact } from "../api.js";

const STATUS_LABELS = {
  confirmed: "Confirmed",
  delayed: "Delayed",
  in_transit: "In transit",
};

export default function SuppliersPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [selectedId, setSelectedId] = useState("");
  const [contact, setContact] = useState("Supplier operations");
  const [status, setStatus] = useState("delayed");
  const [eta, setEta] = useState("");
  const [note, setNote] = useState("");

  async function loadData({ keepSelection = true } = {}) {
    setLoading(true);
    setError("");
    try {
      const result = await api.orders();
      setData(result);
      const chosen = keepSelection
        ? result.orders.find((po) => String(po.id) === String(selectedId))
        : null;
      const defaultPo = chosen || result.orders.find((po) => !["received", "cancelled", "rejected"].includes(String(po.status).toLowerCase())) || result.orders[0];
      if (defaultPo) {
        setSelectedId(String(defaultPo.id));
        if (!chosen) setEta(defaultPo.expected_at || "");
      }
    } catch (err) {
      setError(err.message || "Could not load suppliers and purchase orders.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadData({ keepSelection: false }); }, []);

  const openOrders = useMemo(() => (data?.orders || []).filter((po) => !["received", "cancelled", "rejected"].includes(String(po.status).toLowerCase())), [data]);
  const selectedOrder = (data?.orders || []).find((po) => String(po.id) === String(selectedId));
  const updates = data?.delivery_updates || [];

  function selectOrder(value) {
    setSelectedId(value);
    const po = (data?.orders || []).find((item) => String(item.id) === String(value));
    setEta(po?.expected_at || "");
    setStatus(String(po?.status).toLowerCase() === "delayed" ? "delayed" : String(po?.status).toLowerCase() === "in_transit" ? "in_transit" : "confirmed");
    setSuccess("");
  }

  async function submitUpdate(event) {
    event.preventDefault();
    if (!selectedOrder) return;
    setSending(true); setError(""); setSuccess("");
    try {
      const result = await api.submitSupplierUpdate(selectedOrder.id, {
        supplier_contact: contact.trim(),
        status,
        revised_expected_at: eta,
        note: note.trim(),
      });
      setSuccess(result.message);
      setNote("");
      await loadData();
    } catch (err) {
      setError(err.message || "Could not save the supplier update.");
    } finally {
      setSending(false);
    }
  }

  if (loading && !data) return <div className="state">Loading supplier operations…</div>;
  if (error && !data) return <div className="err-banner">{error}</div>;

  return (
    <div className="supplier-page">
      <div className="topbar supplier-page-heading">
        <div>
          <p className="eyebrow">Procurement operations</p>
          <h2 className="page-title">Suppliers & purchase orders</h2>
          <p className="sub">Track inbound stock, compare suppliers and record delivery updates against existing purchase orders.</p>
        </div>
        <button className="btn" onClick={() => loadData()} disabled={loading}><RefreshCw size={15} /> Refresh data</button>
      </div>

      {error ? <div className="err-banner supplier-message"><AlertCircle size={16} />{error}</div> : null}
      {success ? <div className="ok-banner supplier-message"><CheckCircle2 size={16} />{success}</div> : null}

      <section className="card supplier-update-panel">
        <div className="supplier-panel-head">
          <div className="supplier-panel-icon"><Truck size={19} /></div>
          <div>
            <p className="eyebrow">Inbound delivery</p>
            <h3>Record a supplier update</h3>
            <p className="muted">A supplier representative can report a status change or revised arrival date for a specific PO.</p>
          </div>
          <span className="supplier-demo-tag">Demo portal</span>
        </div>
        <div className="supplier-process-note"><AlertCircle size={16} /><span>This is a simulated supplier entry form for the hackathon. It saves to the local SQLite database, keeps an update history and refreshes pending recommendations. It does not contact a real supplier or increase on-hand inventory.</span></div>
        <form onSubmit={submitUpdate} className="supplier-update-form">
          <div className="supplier-form-grid">
            <label>Purchase order
              <select value={selectedId} onChange={(event) => selectOrder(event.target.value)} required>
                {openOrders.map((po) => <option key={po.id} value={String(po.id)}>{po.po_number} · {po.product_name} · {po.supplier_name}</option>)}
              </select>
            </label>
            <label>Supplier contact name / team
              <input value={contact} onChange={(event) => setContact(event.target.value)} placeholder="e.g. Priya, dispatch desk" minLength={2} maxLength={100} required />
            </label>
            <label>Reported status
              <select value={status} onChange={(event) => setStatus(event.target.value)} required>
                <option value="confirmed">Confirmed — ETA is still valid</option>
                <option value="delayed">Delayed — ETA has changed</option>
                <option value="in_transit">In transit — shipment dispatched</option>
              </select>
            </label>
            <label>Revised expected arrival
              <input type="date" value={eta} onChange={(event) => setEta(event.target.value)} required />
            </label>
          </div>
          <label className="supplier-note-field">Update note
            <textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="Explain what changed, e.g. dispatch held at carrier hub; revised ETA 12 Oct." minLength={5} maxLength={600} required rows={3} />
          </label>
          <div className="supplier-form-footer">
            <p className="muted"><FileText size={14} /> Selected PO: <strong>{selectedOrder?.po_number || "—"}</strong> · Current ETA: <strong>{selectedOrder?.expected_at || "—"}</strong></p>
            <button className="btn primary" type="submit" disabled={sending || !selectedOrder || openOrders.length === 0}><Send size={15} /> {sending ? "Saving update…" : "Save delivery update"}</button>
          </div>
        </form>
      </section>

      <section className="card supplier-history-panel">
        <div className="section-heading">
          <div><h3>Recent supplier updates</h3><p className="muted">A timestamped record of submitted ETA and status changes.</p></div>
          <span className="supplier-count">{updates.length} updates</span>
        </div>
        {updates.length === 0 ? <div className="supplier-empty"><Clock3 size={19} /><span>No delivery updates submitted yet. Use the form above to create the first record.</span></div> : (
          <div className="table-wrap"><table className="supplier-updates-table">
            <thead><tr><th>Reported</th><th>PO / supplier</th><th>Status</th><th>ETA change</th><th>Contact / note</th></tr></thead>
            <tbody>{updates.map((update) => <tr key={update.id}>
              <td className="mono supplier-time">{String(update.reported_at).replace("T", " ")}</td>
              <td><strong>{update.po_number}</strong><div className="muted">{update.supplier_name} · {update.product_name}</div></td>
              <td><span className={`pill ${update.status_reported}`}>{STATUS_LABELS[update.status_reported] || update.status_reported}</span></td>
              <td><span className="muted">{update.previous_expected_at}</span><div className="supplier-new-eta">→ {update.revised_expected_at}</div></td>
              <td>{update.supplier_contact}<div className="muted supplier-note-preview">{update.note}</div></td>
            </tr>)}</tbody>
          </table></div>
        )}
      </section>

      <section className="card supplier-pos-panel">
        <div className="section-heading"><div><h3>Open purchase orders</h3><p className="muted">Supplier-reported ETAs are shown here after an update is saved.</p></div></div>
        <div className="table-wrap"><table>
          <thead><tr><th>PO</th><th>Supplier</th><th>Product</th><th>Store</th><th>Qty</th><th>Status</th><th>Expected arrival</th></tr></thead>
          <tbody>{data.orders.map((po) => <tr key={po.id}>
            <td className="mono">{po.po_number}</td><td>{po.supplier_name}</td><td>{po.product_name}</td><td>{po.store_name}</td><td>{po.quantity}</td>
            <td><span className={`pill ${String(po.status).toLowerCase()}`}>{String(po.status).replaceAll("_", " ")}</span></td><td>{po.expected_at}</td>
          </tr>)}</tbody>
        </table></div>
      </section>

      <section className="card supplier-catalog-panel">
        <div className="section-heading"><div><h3>Supplier catalog</h3><p className="muted">Listed costs, lead times, available quantities and supplier reliability.</p></div></div>
        <div className="table-wrap"><table>
          <thead><tr><th>Supplier</th><th>Product</th><th>Unit price</th><th>Lead time</th><th>Available</th><th>Reliability</th></tr></thead>
          <tbody>{data.catalog.map((row) => <tr key={row.id}>
            <td>{row.supplier_name}</td><td>{row.product_name}</td><td>{inrExact(row.unit_price)}</td><td>{row.lead_time_days} days</td><td>{row.available_qty}</td><td>{row.reliability}</td>
          </tr>)}</tbody>
        </table></div>
      </section>
      <p className="muted supplier-footnote">Prototype limitation: this form is locally accessible and has no supplier authentication. In a real deployment, suppliers would need verified accounts or a secured partner API, access restricted to their own POs, and an authenticated integration.</p>
    </div>
  );
}
