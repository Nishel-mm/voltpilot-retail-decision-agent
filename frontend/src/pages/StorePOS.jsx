import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  AlertCircle, ArrowLeft, ArrowRight, BadgeCheck, Banknote, Box, CheckCircle2,
  CreditCard, Headphones, Laptop, Minus, Monitor, Package, Plus, Printer,
  Receipt, Search, ShoppingBag, Smartphone, Store, Trash2, UserRound, Wallet, PackagePlus, Warehouse, X,
} from "lucide-react";
import { api, inr } from "../api.js";

const TAX_RATE = 0.18;

function ProductIcon({ category }) {
  const value = (category || "").toLowerCase();
  const Icon = value.includes("laptop") ? Laptop
    : value.includes("headphone") || value.includes("audio") ? Headphones
      : value.includes("monitor") || value.includes("entertainment") ? Monitor
        : value.includes("wearable") || value.includes("phone") ? Smartphone
          : Package;
  return <Icon size={23} strokeWidth={1.7} />;
}

function StageButton({ active, number, title, onClick, disabled }) {
  return (
    <button className={`pos-stage ${active ? "is-active" : ""}`} onClick={onClick} disabled={disabled}>
      <span className="pos-stage-number">{number}</span>
      <span>{title}</span>
    </button>
  );
}

export default function StorePOS() {
  const navigate = useNavigate();
  const { saleId } = useParams();
  const [storeId, setStoreId] = useState(null);
  const [storeData, setStoreData] = useState({ stores: [], items: [], categories: [] });
  const [recentSales, setRecentSales] = useState([]);
  const [receiptData, setReceiptData] = useState(null);
  const [cart, setCart] = useState([]);
  const [step, setStep] = useState("vault");
  const [category, setCategory] = useState("All products");
  const [search, setSearch] = useState("");
  const [customerName, setCustomerName] = useState("");
  const [paymentMethod, setPaymentMethod] = useState("upi");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [showNewProduct, setShowNewProduct] = useState(false);
  const [restockProduct, setRestockProduct] = useState(null);
  const [savingProduct, setSavingProduct] = useState(false);
  const [savingReceipt, setSavingReceipt] = useState(false);
  const [newProduct, setNewProduct] = useState({ sku: "", name: "", category: "Laptops", unit_cost: "", selling_price: "", initial_stock: "0", note: "New stock added through Store & Product Vault" });
  const [receiptForm, setReceiptForm] = useState({ quantity: "1", note: "Stock received at store" });
  const [newStore, setNewStore] = useState({ code: "", name: "", city: "", region: "" });
  const [savingStore, setSavingStore] = useState(false);

  async function reloadStore() {
    setLoading(true);
    setError("");
    try {
      const availableStores = await api.stores();
      if (!availableStores.length) {
        setStoreData({ store: null, stores: [], items: [], categories: [], data_origin: "No retailer data has been entered yet." });
        setRecentSales([]);
        return;
      }
      const selectedExists = availableStores.some((store) => Number(store.id) === Number(storeId));
      if (!selectedExists) {
        setStoreData((previous) => ({ ...previous, stores: availableStores }));
        setStoreId(Number(availableStores[0].id));
        return;
      }
      const [catalog, sales] = await Promise.all([api.storeCatalog(Number(storeId)), api.storeSales(Number(storeId))]);
      setStoreData(catalog);
      setRecentSales(sales.items || []);
    } catch (err) {
      setError(err.message || "Could not load store catalog.");
    } finally {
      setLoading(false);
    }
  }

  async function reloadReceipt() {
    setLoading(true);
    setError("");
    try {
      const result = await api.storeSale(saleId);
      setReceiptData(result);
    } catch (err) {
      setError(err.message || "Could not load receipt.");
      setReceiptData(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (saleId) reloadReceipt();
    else reloadStore();
    // Only reload when the store or receipt route changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storeId, saleId]);

  const items = storeData.items || [];
  const stores = storeData.stores || [];
  const categories = ["All products", ...(storeData.categories || [])];
  const filteredItems = useMemo(() => items.filter((item) => {
    const categoryMatch = category === "All products" || item.category === category;
    const needle = search.trim().toLowerCase();
    const searchMatch = !needle || `${item.name} ${item.sku} ${item.category}`.toLowerCase().includes(needle);
    return categoryMatch && searchMatch;
  }), [items, category, search]);

  const cartCount = cart.reduce((sum, item) => sum + item.quantity, 0);
  const subtotal = round2(cart.reduce((sum, item) => sum + item.quantity * Number(item.selling_price), 0));
  const tax = round2(subtotal * TAX_RATE);
  const total = round2(subtotal + tax);

  function round2(value) { return Math.round((Number(value) + Number.EPSILON) * 100) / 100; }

  function addToCart(product) {
    setError("");
    setNotice("");
    const current = cart.find((line) => line.product_id === product.product_id);
    if (current && current.quantity >= product.available_qty) {
      setError(`Only ${product.available_qty} units of ${product.name} are available at this store.`);
      return;
    }
    if (!current && product.available_qty < 1) {
      setError(`${product.name} is currently out of stock at this store.`);
      return;
    }
    setCart((prev) => {
      const found = prev.find((line) => line.product_id === product.product_id);
      if (found) return prev.map((line) => line.product_id === product.product_id ? { ...line, quantity: line.quantity + 1 } : line);
      return [...prev, { ...product, quantity: 1 }];
    });
    setNotice(`${product.name} added to the bill.`);
  }

  function setLineQuantity(productId, quantity) {
    if (quantity < 1) {
      setCart((prev) => prev.filter((line) => line.product_id !== productId));
      return;
    }
    const product = items.find((item) => item.product_id === productId);
    if (product && quantity > product.available_qty) {
      setError(`Only ${product.available_qty} units are available at this store.`);
      return;
    }
    setCart((prev) => prev.map((line) => line.product_id === productId ? { ...line, quantity } : line));
    setError("");
  }

  function changeStore(nextValue) {
    const nextId = Number(nextValue);
    if (nextId === Number(storeId)) return;
    if (cart.length && !window.confirm("Changing stores will clear the current bill. Continue?")) return;
    setCart([]);
    setStoreId(nextId);
    setCategory("All products");
    setNotice("");
    setError("");
  }

  async function submitNewStore(event) {
    event.preventDefault();
    setSavingStore(true); setError(""); setNotice("");
    try {
      const result = await api.createStore({
        code: newStore.code.trim().toUpperCase(),
        name: newStore.name.trim(),
        city: newStore.city.trim(),
        region: newStore.region.trim(),
      });
      setStoreData({ store: result.store, stores: [result.store], items: [], categories: [], business_date: new Date().toISOString().slice(0, 10) });
      setStoreId(Number(result.store.id));
      setNewStore({ code: "", name: "", city: "", region: "" });
      setNotice(result.message || "Store created. Add products and opening stock next.");
    } catch (err) {
      setError(err.message || "Could not create store.");
    } finally {
      setSavingStore(false);
    }
  }

  async function submitNewProduct(event) {
    event.preventDefault();
    setSavingProduct(true); setError(""); setNotice("");
    try {
      const result = await api.createStoreProduct({
        store_id: Number(storeId), sku: newProduct.sku.trim(), name: newProduct.name.trim(),
        category: newProduct.category.trim(), unit_cost: Number(newProduct.unit_cost),
        selling_price: Number(newProduct.selling_price), initial_stock: Number(newProduct.initial_stock),
        note: newProduct.note.trim(),
      });
      setShowNewProduct(false);
      setNewProduct({ sku: "", name: "", category: "Laptops", unit_cost: "", selling_price: "", initial_stock: "0", note: "New stock added through Store & Product Vault" });
      await reloadStore();
      setNotice(result.message || "Product saved to SQLite.");
      setCategory("All products"); setSearch("");
    } catch (err) { setError(err.message || "Could not add product."); }
    finally { setSavingProduct(false); }
  }

  async function submitStockReceipt(event) {
    event.preventDefault();
    if (!restockProduct) return;
    setSavingReceipt(true); setError(""); setNotice("");
    try {
      const result = await api.receiveStoreStock({
        store_id: Number(storeId), product_id: Number(restockProduct.product_id),
        quantity: Number(receiptForm.quantity), note: receiptForm.note.trim(),
      });
      setRestockProduct(null); setReceiptForm({ quantity: "1", note: "Stock received at store" });
      await reloadStore();
      setNotice(result.message || "Stock receipt saved to SQLite.");
    } catch (err) { setError(err.message || "Could not record stock receipt."); }
    finally { setSavingReceipt(false); }
  }

  async function checkout() {
    if (!cart.length) {
      setError("Add at least one product before checkout.");
      return;
    }
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const result = await api.storeCheckout({
        store_id: Number(storeId),
        customer_name: customerName.trim(),
        payment_method: paymentMethod,
        items: cart.map((line) => ({ product_id: line.product_id, quantity: line.quantity })),
      });
      setCart([]);
      setCustomerName("");
      navigate(`/store/receipt/${result.id}`);
    } catch (err) {
      setError(err.message || "Checkout failed. Refresh the product vault and try again.");
    } finally {
      setSaving(false);
    }
  }

  if (saleId) {
    if (loading) return <div className="page"><div className="card">Loading receipt…</div></div>;
    if (error) return <div className="page"><div className="topbar"><div><p className="eyebrow">Store operations</p><h2 className="page-title">Sales receipt</h2></div><button className="btn" onClick={() => navigate("/store")}><ArrowLeft size={16} /> Back to Store</button></div><div className="err-banner pos-message"><AlertCircle size={17} />{error}</div></div>;
    const sale = receiptData?.sale;
    if (!sale) return null;
    return (
      <div className="page pos-page">
        <div className="topbar"><div><p className="eyebrow">Store operations / completed sale</p><h2 className="page-title">Sales receipt</h2><p className="sub">A recorded prototype transaction. No real payment was processed.</p></div><div className="row"><button className="btn" onClick={() => window.print()}><Printer size={16} /> Print receipt</button><button className="btn primary" onClick={() => navigate("/store")}><ArrowLeft size={16} /> Back to Store</button></div></div>
        <section className="pos-receipt card">
          <div className="pos-receipt-brand"><div className="pos-receipt-mark"><Store size={20} /></div><div><h3>VoltKart Electronics</h3><p>{sale.store_name}</p></div><span className="pos-sold-label"><CheckCircle2 size={15} /> SOLD</span></div>
          <div className="pos-receipt-meta"><div><span>Invoice</span><strong>{sale.invoice_number}</strong></div><div><span>Date recorded</span><strong>{new Date(sale.created_at).toLocaleString()}</strong></div><div><span>Customer</span><strong>{sale.customer_name || "Walk-in customer"}</strong></div><div><span>Payment</span><strong>{String(sale.payment_method).toUpperCase()} · simulated</strong></div></div>
          <div className="table-wrap"><table className="pos-table"><thead><tr><th>Item</th><th>Qty</th><th>Unit price</th><th className="align-right">Line total</th></tr></thead><tbody>{receiptData.items.map((line) => <tr key={line.id}><td><strong>{line.product_name}</strong><small>{line.sku}</small></td><td>{line.quantity}</td><td>{inr(line.unit_price)}</td><td className="align-right">{inr(line.line_total)}</td></tr>)}</tbody></table></div>
          <div className="pos-receipt-totals"><div><span>Subtotal</span><strong>{inr(sale.subtotal)}</strong></div><div><span>Demo tax estimate ({Math.round(Number(sale.tax_rate) * 100)}%)</span><strong>{inr(sale.tax_amount)}</strong></div><div className="pos-total-line"><span>Total</span><strong>{inr(sale.total_amount)}</strong></div></div>
          <p className="pos-footnote">Demo only: the tax figure is illustrative, not a statutory tax invoice. Inventory and daily sales history were updated in the connected database for the prototype.</p>
          <div className="ok-banner pos-message"><BadgeCheck size={17} /> Sale is saved. On-hand stock, daily sales history and pending recommendations were refreshed.</div>
        </section>
        {receiptData.agent_analysis ? <section className="card pos-agent-reaction">
          <div className="pos-section-head"><div><p className="eyebrow">After-sale system check</p><h3>VoltPilot re-analysed the seven risk areas</h3><p className="muted">Calculated from current inventory, sales, supplier, promotion and purchase-order records at {receiptData.agent_analysis.last_analyzed_at ? new Date(receiptData.agent_analysis.last_analyzed_at).toLocaleTimeString() : "checkout"}.</p></div><button className="btn primary" onClick={() => navigate("/")}>View Command Center <ArrowRight size={14}/></button></div>
          <div className="pos-agent-risk-grid">{(receiptData.agent_analysis.items || []).map((area) => <button type="button" className="pos-agent-risk" key={area.id} onClick={() => navigate(`/risk-areas/${area.id}`)}>
            <span className="pos-agent-risk-number">{area.number}</span><strong>{area.title}</strong><span className={`risk-area-state ${area.status === "needs_data" ? "needs-data" : area.status === "active" ? "active" : "clear"}`}>{area.status === "needs_data" ? "Needs data" : area.status === "active" ? `${area.issue_count} finding${area.issue_count === 1 ? "" : "s"}` : "No current findings"}</span><small>Open analysis <ArrowRight size={12}/></small>
          </button>)}</div>
          <p className="muted pos-agent-note">A sale should update the objectives its data affects (especially stockout exposure and store imbalance). Supplier trade-offs or the new-launch objective may correctly remain unchanged if the relevant data did not change or is not available.</p>
        </section> : null}
      </div>
    );
  }

  if (!saleId && !loading && stores.length === 0) {
    return (
      <div className="page pos-page">
        <div className="topbar"><div><p className="eyebrow">Retail setup</p><h2 className="page-title">Create your first store</h2><p className="sub">VoltPilot starts with an empty business database. Enter your real store details, then add products and opening stock.</p></div></div>
        {error ? <div className="err-banner pos-message"><AlertCircle size={17} />{error}</div> : null}
        {notice ? <div className="ok-banner pos-message"><CheckCircle2 size={17} />{notice}</div> : null}
        <section className="card pos-inline-panel">
          <div className="pos-inline-panel-head"><div><h3>Store details</h3><p className="muted">A store is a location, not product or stock data. No sample records will be created.</p></div><Store size={22} /></div>
          <form onSubmit={submitNewStore}>
            <div className="pos-admin-form-grid">
              <label className="pos-admin-field"><span>Store code <b>*</b></span><input required minLength={2} maxLength={12} pattern="[A-Za-z0-9_-]+" value={newStore.code} onChange={(e) => setNewStore({ ...newStore, code: e.target.value.toUpperCase() })} placeholder="e.g. BLR01" /><small>Short unique code used in reports/imports.</small></label>
              <label className="pos-admin-field"><span>Store name <b>*</b></span><input required minLength={2} maxLength={140} value={newStore.name} onChange={(e) => setNewStore({ ...newStore, name: e.target.value })} placeholder="e.g. VoltKart Bengaluru Central" /></label>
              <label className="pos-admin-field"><span>City <b>*</b></span><input required minLength={2} maxLength={80} value={newStore.city} onChange={(e) => setNewStore({ ...newStore, city: e.target.value })} placeholder="Bengaluru" /></label>
              <label className="pos-admin-field"><span>Region <b>*</b></span><input required minLength={2} maxLength={80} value={newStore.region} onChange={(e) => setNewStore({ ...newStore, region: e.target.value })} placeholder="South" /></label>
            </div>
            <div className="pos-inline-panel-footer"><p>This saves only the store record. Products and stock are added separately so the database reflects what the retailer actually enters.</p><button className="btn primary" type="submit" disabled={savingStore}>{savingStore ? "Creating store…" : "Create store & continue"}</button></div>
          </form>
        </section>
      </div>
    );
  }

  return (
    <div className="page pos-page">
      <div className="topbar"><div><p className="eyebrow">Retail operations / point of sale</p><h2 className="page-title">Store &amp; Product Vault</h2><p className="sub">Browse stock, prepare a bill, record a simulated sale and feed the operational data back into VoltPilot.</p></div>{stores.length ? <div className="pos-store-select"><label htmlFor="pos-store">Selling from</label><select id="pos-store" value={storeId ?? ""} onChange={(event) => changeStore(event.target.value)}>{stores.map((store) => <option key={store.id} value={store.id}>{store.name}</option>)}</select></div> : null}</div>

      <div className="pos-demo-note"><Store size={16} /><span><strong>Retail operations</strong> — the catalog and quantities come from records entered by your team. Checkout records a simulated sale; no real payment is processed.</span></div>

      <div className="pos-stagebar">
        <StageButton number="01" title="Product vault" active={step === "vault"} onClick={() => setStep("vault")} />
        <div className="pos-stage-connector"><ArrowRight size={15} /></div>
        <StageButton number="02" title={`Billing${cartCount ? ` (${cartCount})` : ""}`} active={step === "billing"} onClick={() => setStep("billing")} />
        <div className="pos-stage-connector"><ArrowRight size={15} /></div>
        <StageButton number="03" title="Sold records" active={step === "sold"} onClick={() => { setStep("sold"); reloadStore(); }} />
      </div>

      {error ? <div className="err-banner pos-message"><AlertCircle size={17} />{error}</div> : null}
      {notice ? <div className="ok-banner pos-message"><CheckCircle2 size={17} />{notice}</div> : null}

      {step === "vault" ? (
        <>
          <div className="pos-workspace">
            <section className="pos-catalog">
              <div className="pos-section-head"><div><h3>Product vault</h3><p className="muted">Browse by department or search the store's catalog.</p></div><div className="pos-vault-actions"><span className="pos-count">{items.length} SKUs in this store</span><button className="btn primary" onClick={() => { setShowNewProduct((value) => !value); setRestockProduct(null); }}><PackagePlus size={15} /> {showNewProduct ? "Close form" : "Add new product"}</button></div></div>
              {showNewProduct ? (
                <form className="card pos-inline-panel" onSubmit={submitNewProduct}>
                  <div className="pos-inline-panel-head"><div><h4>Add a product to the catalog</h4><p>Creates a unique SKU for {storeData.store?.name || "the selected store"}. Other stores will list it only when stock is received there.</p></div><button type="button" className="btn" aria-label="Close add product form" onClick={() => setShowNewProduct(false)}><X size={15} /></button></div>
                  <div className="pos-admin-form-grid">
                    <label className="pos-admin-field"><span>SKU <b>*</b></span><input required minLength={2} maxLength={50} value={newProduct.sku} onChange={(e) => setNewProduct({ ...newProduct, sku: e.target.value.toUpperCase() })} placeholder="e.g. VK-LT-18" /></label>
                    <label className="pos-admin-field"><span>Product name <b>*</b></span><input required minLength={2} maxLength={140} value={newProduct.name} onChange={(e) => setNewProduct({ ...newProduct, name: e.target.value })} placeholder="e.g. OrbitBook 18-inch Laptop" /></label>
                    <label className="pos-admin-field"><span>Category <b>*</b></span><select required value={newProduct.category} onChange={(e) => setNewProduct({ ...newProduct, category: e.target.value })}>{["Laptops", "Headphones", "Monitors", "Accessories", "Smartphones", "Tablets", "Gaming", "Home Audio", "Networking", "Other"].map((value) => <option key={value}>{value}</option>)}</select></label>
                    <label className="pos-admin-field"><span>Unit cost (₹) <b>*</b></span><input required type="number" min="0" step="0.01" value={newProduct.unit_cost} onChange={(e) => setNewProduct({ ...newProduct, unit_cost: e.target.value })} placeholder="Supplier cost" /></label>
                    <label className="pos-admin-field"><span>Selling price (₹) <b>*</b></span><input required type="number" min="0.01" step="0.01" value={newProduct.selling_price} onChange={(e) => setNewProduct({ ...newProduct, selling_price: e.target.value })} placeholder="Retail price" /></label>
                    <label className="pos-admin-field"><span>Opening stock at selected store</span><input required type="number" min="0" max="100000" step="1" value={newProduct.initial_stock} onChange={(e) => setNewProduct({ ...newProduct, initial_stock: e.target.value })} /><small>Enter 0 if the SKU is listed but stock has not arrived yet.</small></label>
                    <label className="pos-admin-field pos-admin-field-wide"><span>Stock note</span><input maxLength={400} value={newProduct.note} onChange={(e) => setNewProduct({ ...newProduct, note: e.target.value })} placeholder="Opening stock source / note" /></label>
                  </div>
                  <div className="pos-inline-panel-footer"><p>Data is saved to the connected database and pending VoltPilot recommendations are refreshed. Product creation does not invent sales history.</p><button className="btn primary" type="submit" disabled={savingProduct}>{savingProduct ? "Saving product…" : "Save product & stock"}</button></div>
                </form>
              ) : null}
              {restockProduct ? (
                <form className="card pos-inline-panel" onSubmit={submitStockReceipt}>
                  <div className="pos-inline-panel-head"><div><h4>Receive stock · {restockProduct.name}</h4><p>SKU {restockProduct.sku} · Current on-hand at {storeData.store?.name}: {restockProduct.available_qty}</p></div><button type="button" className="btn" aria-label="Close receive stock form" onClick={() => setRestockProduct(null)}><X size={15} /></button></div>
                  <div className="pos-admin-form-grid pos-admin-form-grid-compact">
                    <label className="pos-admin-field"><span>Quantity received <b>*</b></span><input required type="number" min="1" max="100000" step="1" value={receiptForm.quantity} onChange={(e) => setReceiptForm({ ...receiptForm, quantity: e.target.value })} /></label>
                    <label className="pos-admin-field"><span>Receipt note</span><input maxLength={400} value={receiptForm.note} onChange={(e) => setReceiptForm({ ...receiptForm, note: e.target.value })} placeholder="Delivery / stocktake reference" /></label>
                  </div>
                  <div className="pos-inline-panel-footer"><p>Records a positive stock movement and refreshes the agent. It does not change sales history.</p><button className="btn primary" type="submit" disabled={savingReceipt}>{savingReceipt ? "Recording receipt…" : "Record received stock"}</button></div>
                </form>
              ) : null}
              <div className="pos-catalog-tools"><div className="pos-search"><Search size={16} /><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search name, SKU or category" aria-label="Search products" /></div><div className="pos-category-tabs">{categories.map((name) => <button key={name} className={category === name ? "selected" : ""} onClick={() => setCategory(name)}>{name}</button>)}</div></div>
              {loading ? <div className="card">Loading products…</div> : (
                <div className="pos-product-grid">
                  {filteredItems.map((product) => (
                    <article className="pos-product-card" key={product.product_id}>
                      <div className="pos-product-art"><ProductIcon category={product.category} /><span>{product.category}</span></div>
                      <p className="pos-sku">{product.sku}</p><h4>{product.name}</h4>
                      <div className="pos-price">{inr(product.selling_price)}</div>
                      <div className="pos-product-flags"><span className={`pos-stock-badge ${product.stock_status || (product.available_qty <= 0 ? "out_of_stock" : product.available_qty <= 3 ? "low_stock" : "in_stock")}`}>{product.stock_status_label || (product.available_qty <= 0 ? "Out of stock" : product.available_qty <= 3 ? "Low stock" : "In stock")}</span></div>
                      <div className="pos-stock-row"><span className={product.available_qty <= 3 ? "pos-stock-low" : ""}>{product.available_qty} units on hand</span><span>{Number(product.stock_cover_days ?? 0) > 0 ? `${Number(product.stock_cover_days).toFixed(1)}d cover` : "Cover n/a"}</span></div>
                      <button className="btn primary pos-add-button" disabled={product.available_qty <= 0} onClick={() => addToCart(product)}><Plus size={15} /> {product.available_qty <= 0 ? "Sold out" : "Add to bill"}</button>
                      <button className="btn pos-restock-button" onClick={() => { setRestockProduct(product); setShowNewProduct(false); setReceiptForm({ quantity: "1", note: "Stock received at store" }); }}><Warehouse size={14} /> Receive stock</button>
                    </article>
                  ))}
                  {!filteredItems.length ? <div className="pos-empty">No products match this search.</div> : null}
                </div>
              )}
            </section>
            <aside className="pos-cart-summary card">
              <div className="pos-section-head"><div><h3>Current bill</h3><p className="muted">{cartCount} unit{cartCount === 1 ? "" : "s"} selected</p></div><ShoppingBag size={19} /></div>
              {cart.length ? <div className="pos-cart-lines">{cart.map((line) => <div className="pos-cart-line" key={line.product_id}><div className="pos-cart-line-main"><strong>{line.name}</strong><small>{inr(line.selling_price)} each</small></div><div className="pos-qty-control"><button aria-label={`Remove one ${line.name}`} onClick={() => setLineQuantity(line.product_id, line.quantity - 1)}><Minus size={13} /></button><span>{line.quantity}</span><button aria-label={`Add one ${line.name}`} onClick={() => setLineQuantity(line.product_id, line.quantity + 1)}><Plus size={13} /></button><button className="pos-remove" aria-label={`Remove ${line.name}`} onClick={() => setLineQuantity(line.product_id, 0)}><Trash2 size={14} /></button></div><div className="pos-cart-line-total">{inr(line.quantity * line.selling_price)}</div></div>)}</div> : <div className="pos-empty-cart"><ShoppingBag size={26} /><strong>No items yet</strong><span>Add products from the vault to prepare a bill.</span></div>}
              <div className="pos-summary-line"><span>Subtotal</span><strong>{inr(subtotal)}</strong></div><div className="pos-summary-line"><span>Demo tax estimate (18%)</span><strong>{inr(tax)}</strong></div><div className="pos-summary-line pos-grand-total"><span>Estimated total</span><strong>{inr(total)}</strong></div>
              <button className="btn primary pos-full-button" disabled={!cart.length} onClick={() => setStep("billing")}>Continue to billing <ArrowRight size={16} /></button>
              <p className="pos-footnote">Tax is an illustrative demo assumption, not a tax-compliant invoice.</p>
            </aside>
          </div>
        </>
      ) : step === "billing" ? (
        <div className="pos-billing-grid">
          <section className="card pos-billing-card"><div className="pos-section-head"><div><h3>Billing details</h3><p className="muted">Review the items before recording the sale.</p></div><Receipt size={20} /></div>
            {!cart.length ? <div className="pos-empty"><ShoppingBag size={22} /><p>Your bill is empty. Return to the product vault to add items.</p><button className="btn" onClick={() => setStep("vault")}>Back to product vault</button></div> : <>
              <label className="pos-field"><span>Customer name <small>optional</small></span><div className="pos-field-input"><UserRound size={15} /><input value={customerName} onChange={(e) => setCustomerName(e.target.value)} maxLength={100} placeholder="Walk-in customer" /></div></label>
              <div className="pos-payment-heading">Payment method <span>simulated</span></div>
              <div className="pos-payment-options">{[{ id: "upi", title: "UPI", Icon: Wallet }, { id: "card", title: "Card", Icon: CreditCard }, { id: "cash", title: "Cash", Icon: Banknote }].map(({ id, title, Icon }) => <button key={id} className={`pos-payment-option ${paymentMethod === id ? "selected" : ""}`} onClick={() => setPaymentMethod(id)}><Icon size={18} /><span>{title}</span>{paymentMethod === id ? <CheckCircle2 size={15} /> : null}</button>)}</div>
              <div className="pos-process-note"><AlertCircle size={16} /><span>No external payment provider is connected. Confirming this screen records a simulated payment and marks the products sold in the local database.</span></div>
              <div className="table-wrap"><table className="pos-table"><thead><tr><th>Item</th><th>Qty</th><th className="align-right">Amount</th></tr></thead><tbody>{cart.map((line) => <tr key={line.product_id}><td><strong>{line.name}</strong><small>{line.sku}</small></td><td>{line.quantity}</td><td className="align-right">{inr(line.quantity * line.selling_price)}</td></tr>)}</tbody></table></div>
              <div className="row pos-billing-actions"><button className="btn" onClick={() => setStep("vault")}><ArrowLeft size={15} /> Back to vault</button><button className="btn primary" onClick={checkout} disabled={saving}>{saving ? "Recording sale…" : "Confirm simulated payment & mark sold"}<ArrowRight size={15} /></button></div>
            </>}
          </section>
          <aside className="card pos-totals-card"><h3>Bill summary</h3><p className="muted">{cartCount} item units · {storeData.store?.name || "Selected store"}</p><div className="pos-summary-line"><span>Subtotal</span><strong>{inr(subtotal)}</strong></div><div className="pos-summary-line"><span>Demo tax (18%)</span><strong>{inr(tax)}</strong></div><div className="pos-summary-line pos-grand-total"><span>Total due</span><strong>{inr(total)}</strong></div><div className="pos-process-note"><AlertCircle size={16} /><span>The transaction is not committed until you confirm. Stock is checked again by the backend at checkout.</span></div></aside>
        </div>
      ) : (
        <section className="card pos-sold-panel"><div className="pos-section-head"><div><h3>Completed sales</h3><p className="muted">Saved bills for the selected store. Open any receipt to review the recorded sale.</p></div><button className="btn" onClick={reloadStore}><Receipt size={15} /> Refresh list</button></div>
          {loading ? <p className="muted">Loading sales…</p> : recentSales.length ? <div className="table-wrap"><table className="pos-table"><thead><tr><th>Invoice</th><th>Recorded at</th><th>Units</th><th>Payment</th><th>Total</th><th>Status</th><th></th></tr></thead><tbody>{recentSales.map((sale) => <tr key={sale.id}><td><strong>{sale.invoice_number}</strong></td><td>{new Date(sale.created_at).toLocaleString()}</td><td>{sale.units_sold}</td><td>{String(sale.payment_method).toUpperCase()} · demo</td><td><strong>{inr(sale.total_amount)}</strong></td><td><span className="pos-sold-label"><CheckCircle2 size={13} /> {sale.status}</span></td><td><button className="btn" onClick={() => navigate(`/store/receipt/${sale.id}`)}>View receipt</button></td></tr>)}</tbody></table></div> : <div className="pos-empty"><Receipt size={24} /><h4>No completed sales yet</h4><p>Record a sale from the Product Vault; it will appear here after checkout.</p><button className="btn primary" onClick={() => setStep("vault")}>Open product vault</button></div>}
        </section>
      )}
      <p className="pos-page-footnote">Business date: {storeData.demo_date || "—"}. Product catalog, checkout, on-hand stock, daily sales history and sale records are served by the FastAPI backend and stored in the connected database.</p>
    </div>
  );
}
