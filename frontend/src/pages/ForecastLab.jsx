import { useEffect, useState } from "react";
import {
  Activity, BrainCircuit, CheckCircle2, Clock3, Database, Download,
  FileSpreadsheet, RefreshCw, Upload, AlertTriangle,
} from "lucide-react";
import { api } from "../api.js";

function Metric({ label, value, hint }) {
  return <div className="card forecast-metric"><div className="kpi-label">{label}</div><div className="kpi-value">{value}</div>{hint ? <div className="muted forecast-hint">{hint}</div> : null}</div>;
}

function downloadCsvTemplate() {
  const blob = new Blob(["date,sku,store_code,units\n"], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "voltpilot-observed-sales-template.csv";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export default function ForecastLab() {
  const [status, setStatus] = useState(null);
  const [predictions, setPredictions] = useState(null);
  const [loading, setLoading] = useState(true);
  const [training, setTraining] = useState(false);
  const [importing, setImporting] = useState(false);
  const [selectedFile, setSelectedFile] = useState(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function loadStatus({ keepMessage = true } = {}) {
    setLoading(true);
    setError("");
    if (!keepMessage) setMessage("");
    try {
      const s = await api.forecastStatus();
      setStatus(s);
      if (s.ready_for_forecast || s.trained) {
        try { setPredictions(await api.forecastPredictions(7)); }
        catch { setPredictions(null); }
      } else {
        setPredictions(null);
      }
    } catch (e) {
      setError(e.message || "Could not load forecast status.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadStatus(); }, []);

  async function trainModel() {
    setTraining(true); setError(""); setMessage("");
    try {
      const result = await api.trainForecast();
      setStatus(result);
      try { setPredictions(await api.forecastPredictions(7)); }
      catch { setPredictions(null); }
      setMessage(`Training and hold-out evaluation finished using observed sales data. ${result.agent_recommendations_refreshed ?? 0} pending agent recommendations refreshed.`);
    } catch (e) {
      setError(e.message || "Training failed.");
    } finally {
      setTraining(false);
    }
  }

  async function importHistory() {
    if (!selectedFile) return;
    setImporting(true); setError(""); setMessage("");
    try {
      const csvText = await selectedFile.text();
      const result = await api.importForecastHistory(csvText);
      setMessage(`${result.message} ${result.imported_rows} daily observation(s) processed.`);
      setSelectedFile(null);
      const input = document.getElementById("forecast-history-file");
      if (input) input.value = "";
      await loadStatus();
    } catch (e) {
      setError(e.message || "Could not import sales history.");
    } finally {
      setImporting(false);
    }
  }

  const stale = Boolean(status?.stale);
  const useMl = status?.selected_forecaster === "ridge_regression" && !stale;
  const canTrain = Boolean(status?.ready_to_train) && !training && !loading;
  const readiness = status?.readiness_reason || "Record actual sales or import historical daily sales to prepare an evaluation set.";

  return (
    <div>
      <div className="topbar">
        <div>
          <p className="eyebrow">Demand intelligence</p>
          <h2 className="page-title">Forecast Lab</h2>
          <p className="sub">Train and evaluate demand forecasts from the retailer's own recorded sales. Seeded demo velocities and generated history are not used for model training.</p>
        </div>
        <button className="btn primary" onClick={trainModel} disabled={!canTrain} title={!status?.ready_to_train ? readiness : "Train on current observed sales history"}>
          <BrainCircuit size={16} /> {training ? "Training model…" : status?.trained ? "Retrain on current data" : "Train & evaluate model"}
        </button>
      </div>

      {error ? <div className="err-banner forecast-banner">{error}</div> : null}
      {message ? <div className="ok-banner forecast-banner"><CheckCircle2 size={16} /> {message}</div> : null}

      <div className="banner forecast-banner">
        <strong>Training data policy:</strong> Forecast Lab only trains on completed Store &amp; POS transaction line-items and historical daily sales that you explicitly import. It never generates a pretend 210-day sales history. A few sales on one date are not enough for reliable time-series training, so the app will say when it needs more history.
      </div>

      {loading ? <div className="card state">Checking observed sales data…</div> : null}

      {!loading && status ? <>
        <div className="grid forecast-metrics">
          <Metric label="Model status" value={status.trained ? (stale ? "Retrain needed" : "Trained") : (status.ready_to_train ? "Ready to train" : "Collecting data")} hint={status.model_name || "Ridge Regression (pure Python)"} />
          <Metric label="POS transactions" value={Number(status.pos_transactions || 0).toLocaleString("en-IN")} hint="Completed Store & POS checkouts" />
          <Metric label="Imported daily rows" value={Number(status.imported_daily_rows || 0).toLocaleString("en-IN")} hint="Retailer-provided historical sales" />
          <Metric label="Observed date span" value={`${Number(status.history_span_days || 0)} days`} hint={`${Number(status.product_store_series || 0)} product/store series`} />
        </div>

        <div className="card forecast-table-card" style={{ marginBottom: 18 }}>
          <div className="section-heading">
            <div><h3><FileSpreadsheet size={17} style={{ verticalAlign: "-3px", marginRight: 8 }} />Import your historical sales</h3><p className="muted">Use your own actual history if you have it. Imported rows are saved to SQLite and become part of future training and sales-velocity analysis.</p></div>
            <button className="btn" onClick={downloadCsvTemplate}><Download size={15} /> CSV template</button>
          </div>
          <div className="banner forecast-banner">
            <strong>CSV columns:</strong> <code>date,sku,store_code,units</code><br />
            Dates must be <code>YYYY-MM-DD</code>. Use an SKU and store code already registered in VoltPilot. Zero units are valid for dates when the product was available but did not sell. Import historical dates that do not overlap with POS sales already recorded for the same product, store, and date.
          </div>
          <div className="row" style={{ gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <input id="forecast-history-file" type="file" accept=".csv,text/csv" className="input" onChange={(event) => setSelectedFile(event.target.files?.[0] || null)} />
            <button className="btn primary" onClick={importHistory} disabled={!selectedFile || importing}>
              <Upload size={15} /> {importing ? "Importing…" : "Import sales CSV"}
            </button>
          </div>
        </div>

        <div className="card forecast-table-card" style={{ marginBottom: 18 }}>
          <div className="section-heading"><div><h3><Database size={17} style={{ verticalAlign: "-3px", marginRight: 8 }} />Data readiness</h3><p className="muted">The model uses a chronological hold-out evaluation after creating the 14-day lag features.</p></div><span className={`pill ${status.ready_to_train ? "success" : "pending"}`}>{status.ready_to_train ? "Ready" : "More data needed"}</span></div>
          <div className="grid forecast-metrics">
            <Metric label="Training examples" value={Number(status.training_examples_available || 0).toLocaleString("en-IN")} hint={`Minimum ${status.minimum_training_examples || 20}`} />
            <Metric label="Held-out examples" value={Number(status.test_examples_available || 0).toLocaleString("en-IN")} hint={`Minimum ${status.minimum_test_examples || 7}`} />
            <Metric label="Observed units" value={Number(status.total_observed_units || 0).toLocaleString("en-IN")} hint="POS + imported sales only" />
            <Metric label="Observed date range" value={status.first_observed_date && status.last_observed_date ? `${status.first_observed_date} → ${status.last_observed_date}` : "No sales data"} hint="Actual/imported observations" />
          </div>
          {!status.ready_to_train ? <div className="banner forecast-banner"><AlertTriangle size={16} style={{ verticalAlign: "-3px", marginRight: 6 }} /><strong>Not training yet:</strong> {readiness} Make additional real sales over time or import actual sales history. Do not make up rows to pass the minimum.</div> : <div className="ok-banner forecast-banner"><CheckCircle2 size={16} /> Enough observed data is available for a train/test evaluation. Training will be based on the currently stored observations.</div>}
          {status.legacy_synthetic_model_ignored ? <p className="muted">The previously saved model trained from synthetic history has been ignored. It cannot be used for retailer-data forecasts.</p> : null}
          {stale ? <div className="banner forecast-banner"><strong>New sales since training:</strong> The saved model is stale. Forecasts fall back to the moving average of current observed sales until you retrain.</div> : null}
        </div>

        {status.trained ? <div className={useMl ? "ok-banner forecast-banner" : "banner forecast-banner"}>
          <div className="row"><Activity size={17} /><strong>Selected forecast for decisions: {useMl ? status.model_name : "Observed-data moving-average baseline"}</strong></div>
          <p>{status.selection_reason}</p>
          {!stale ? <p className="forecast-hint">Ridge MAE: {Number(status.model_mae).toFixed(3)} · Baseline MAE: {Number(status.baseline_mae).toFixed(3)} · Ridge RMSE: {Number(status.model_rmse).toFixed(3)} · Baseline RMSE: {Number(status.baseline_rmse).toFixed(3)}</p> : <p className="forecast-hint">Metrics below describe the previous training run only; retrain to evaluate the newer dataset.</p>}
          <p className="forecast-hint">Last trained: {status.trained_at || "—"} · Training examples: {Number(status.training_samples || 0).toLocaleString("en-IN")} · Test examples: {Number(status.test_samples || 0).toLocaleString("en-IN")}</p>
        </div> : null}
      </> : null}

      {predictions ? <div className="card forecast-table-card">
        <div className="section-heading"><div><h3>Next 7-day store demand outlook</h3><p className="muted">Only product/store pairs with observed POS/imported history are forecast. Rows without enough history are labelled rather than filled with dummy demand.</p></div><span className="pill pending"><Clock3 size={12} /> 7-day horizon</span></div>
        <div className="table-wrap"><table>
          <thead><tr><th>Product / SKU</th><th>Store</th><th>Stock</th><th>ML avg/day</th><th>Baseline avg/day</th><th>Selected demand/day</th><th>Forecast cover</th><th>Source</th></tr></thead>
          <tbody>{predictions.items.map((item) => <tr key={`${item.product_id}-${item.store_id}`}>
            <td><strong>{item.product_name}</strong><div className="muted mono">{item.sku}</div></td>
            <td>{item.store_name}</td><td>{item.current_stock}</td>
            <td>{item.ml_daily_average == null ? "—" : Number(item.ml_daily_average).toFixed(2)}</td>
            <td>{item.baseline_daily_average == null ? "—" : Number(item.baseline_daily_average).toFixed(2)}</td>
            <td><strong>{item.forecast_daily_average == null ? "—" : Number(item.forecast_daily_average).toFixed(2)}</strong></td>
            <td>{item.forecast_stock_cover_days == null ? "—" : `${item.forecast_stock_cover_days} d`}</td>
            <td>{item.forecast_available ? item.forecast_source : <span className="muted">{item.forecast_reason}</span>}</td>
          </tr>)}</tbody>
        </table></div>
        <p className="muted forecast-footnote">Forecast inputs are the retailer's observed transaction history and imported daily sales. The app does not invent older sales to make its ML metrics look better.</p>
      </div> : null}
      <div className="row forecast-actions"><button className="btn" onClick={() => loadStatus({ keepMessage: true })} disabled={loading || training || importing}><RefreshCw size={15} /> Refresh status</button></div>
    </div>
  );
}
