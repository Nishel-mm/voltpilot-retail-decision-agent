const API = "/api";

async function request(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    // Inventory, sales and risk-area GETs must always reflect the latest SQLite state.
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { detail: text };
  }
  if (!response.ok) {
    const detail = data?.detail || data?.error || response.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

export const api = {
  health: () => request("/health"),
  dashboard: () => request("/dashboard"),
  recommendations: (refresh = false) => request(`/recommendations${refresh ? "?refresh=true" : ""}`),
  recommendation: (id) => request(`/recommendations/${id}`),
  inventory: () => request("/inventory"),
  orders: () => request("/orders"),
  submitSupplierUpdate: (orderId, payload) => request(`/orders/${orderId}/supplier-update`, {
    method: "POST", body: JSON.stringify(payload),
  }),
  supplierUpdateHistory: (orderId) => request(`/orders/${orderId}/supplier-updates`),
  actions: () => request("/actions"),
  approve: (id, optionId, note) =>
    request(`/actions/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ option_id: optionId || null, note: note || "" }),
    }),
  reject: (id, note) =>
    request(`/actions/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ note: note || "" }),
    }),
  reset: () => request("/reset", { method: "POST" }),
  riskAreas: () => request("/risk-areas"),
  riskArea: (id) => request(`/risk-areas/${id}`),
  forecastStatus: () => request("/forecast/status"),
  trainForecast: () => request("/forecast/train", { method: "POST" }),
  importForecastHistory: (csvText) => request("/forecast/import-history", { method: "POST", body: JSON.stringify({ csv_text: csvText }) }),
  forecastPredictions: (days = 7) => request(`/forecast/predictions?days_ahead=${days}`),
  storeCatalog: (storeId = 1) => request(`/store/catalog?store_id=${storeId}`),
  createStoreProduct: (payload) => request("/store/products", { method: "POST", body: JSON.stringify(payload) }),
  receiveStoreStock: (payload) => request("/store/stock-receipts", { method: "POST", body: JSON.stringify(payload) }),
  storeInventoryMovements: (storeId = null, productId = null, limit = 100) => {
    const params = new URLSearchParams();
    if (storeId) params.set("store_id", String(storeId));
    if (productId) params.set("product_id", String(productId));
    params.set("limit", String(limit));
    return request(`/store/inventory-movements?${params.toString()}`);
  },
  storeCheckout: (payload) => request("/store/checkout", { method: "POST", body: JSON.stringify(payload) }),
  storeSales: (storeId = null) => request(`/store/sales${storeId ? `?store_id=${storeId}` : ""}`),
  storeSale: (saleId) => request(`/store/sales/${saleId}`),
};

export function inr(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(value);
}

export function inrExact(value) {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format(value);
}
