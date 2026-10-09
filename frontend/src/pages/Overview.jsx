import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, inr } from "../api.js";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Activity, Archive, CalendarDays, ChevronRight, Clock3, Database, Network, RefreshCw, Target, TrendingUp, Truck } from "lucide-react";

export default function Overview() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [riskData, setRiskData] = useState(null);
  const [riskError, setRiskError] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    let alive = true;
    const loadDashboard = async () => {
      try {
        const result = await api.dashboard();
        if (alive) { setData(result); setError(""); }
      } catch (err) {
        if (alive) setError(err.message);
      }
    };
    loadDashboard();
    // Reflect store/POS changes even if this Command Center tab remains open.
    const timer = window.setInterval(loadDashboard, 10000);
    return () => { alive = false; window.clearInterval(timer); };
  }, []);

  useEffect(() => {
    let alive = true;
    const loadRiskAreas = async () => {
      try {
        const result = await api.riskAreas();
        if (alive) { setRiskData(result); setRiskError(""); }
      } catch (err) {
        if (alive) setRiskError(err.message);
      }
    };
    loadRiskAreas();
    const timer = window.setInterval(loadRiskAreas, 10000);
    return () => { alive = false; window.clearInterval(timer); };
  }, []);

  if (error) return <div className="err-banner">{error} — start the FastAPI backend on port 8000.</div>;
  if (!data) return <div className="state">Loading command center…</div>;

  const chart = data.radar.map((item) => ({
    name: item.store_name.replace("VoltKart ", "").split(" ")[0],
    score: item.score,
  }));

  return (
    <div>
      <div className="topbar">
        <div>
          <p className="eyebrow">VoltKart Electronics · Festival Rush</p>
          <h2 className="page-title">What needs your attention today</h2>
          <p className="sub">
            Demo clock {data.today}. VoltPilot ranked live inventory risks, compared feasible actions,
            and is waiting for a human decision. It is a rule-based agent, not a language model.
          </p>
        </div>
      </div>

      <div className="grid kpis">
        <Kpi label="Open issues" value={data.kpis.attention_items} />
        <Kpi label="Critical / high" value={data.kpis.critical_or_high} />
        <Kpi label="Units on hand" value={data.kpis.units_on_hand} />
        <Kpi label="Delayed POs" value={data.kpis.delayed_pos} />
        <Kpi label="Actions logged" value={data.kpis.actions_logged} />
      </div>

      <section className="risk-areas-section">
        <div className="risk-section-heading">
          <div>
            <p className="eyebrow">Challenge coverage</p>
            <h3>Seven Retail Risk Areas</h3>
            <p className="muted">Every core challenge goal is visible here. Counts are calculated from the current SQLite demo data; missing data is labelled honestly.</p>
          </div>
          <button className="btn" onClick={() => { setRiskError(""); api.riskAreas().then(setRiskData).catch((err) => setRiskError(err.message)); }}><RefreshCw size={14}/> Refresh risks</button>
        </div>
        {riskError ? <div className="err-banner">Risk areas could not be loaded: {riskError}</div> : null}
        {!riskData && !riskError ? <div className="card state">Loading the seven risk detectors…</div> : null}
        {riskData ? <div className="risk-areas-grid">{riskData.items.map((item) => <RiskAreaCard key={item.id} item={item} onClick={() => navigate(`/risk-areas/${item.id}`)} />)}</div> : null}
        {riskData ? <p className="muted risk-origin"><Database size={13}/> {riskData.data_origin} · Last recalculated {riskData.last_analyzed_at ? new Date(riskData.last_analyzed_at).toLocaleTimeString() : "just now"} · refreshes every 10 seconds</p> : null}
      </section>

      <div className="grid two" style={{ marginTop: 16 }}>
        <section className="card">
          <h3>Attention Radar</h3>
          <p className="muted">{data.score_explainer}</p>
          {data.radar.length === 0 ? (
            <div className="state">No pending issues. Reset the demo or approve fewer items.</div>
          ) : (
            data.radar.map((item) => (
              <div className="issue" key={item.id} onClick={() => navigate(`/decision/${item.id}`)}>
                <div>
                  <div className="score">{Math.round(item.score)}</div>
                  <div className="muted">score</div>
                </div>
                <div>
                  <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
                    <span className={`pill ${item.severity}`}>{item.severity}</span>
                    <span className="muted">{item.product_name}</span>
                  </div>
                  <strong>{item.title}</strong>
                  <p className="muted" style={{ margin: "6px 0 0" }}>{item.why_now}</p>
                </div>
                <div className="muted" style={{ textAlign: "right" }}>
                  {inr(item.impact_inr)}
                  <div>impact</div>
                </div>
              </div>
            ))
          )}
        </section>
        <div className="grid" style={{ alignContent: "start" }}>
          <section className="card">
            <h3>Issue pressure by store</h3>
            <div style={{ height: 220 }}>
              <ResponsiveContainer>
                <BarChart data={chart}>
                  <XAxis dataKey="name" stroke="#93a0c2" fontSize={12} />
                  <YAxis stroke="#93a0c2" fontSize={12} />
                  <Tooltip contentStyle={{ background: "#121a2e", border: "1px solid #334" }} />
                  <Bar dataKey="score" fill="#6ea8ff" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>
          <section className="card">
            <h3>Delayed inbound (simulated)</h3>
            {data.delayed_orders.length === 0 ? (
              <p className="muted">No delayed purchase orders.</p>
            ) : (
              data.delayed_orders.map((po) => (
                <p key={po.id}>
                  <span className="pill delayed">delayed</span> {po.po_number} · {po.product_name} → {po.store_name}
                </p>
              ))
            )}
          </section>
          <section className="card">
            <h3>Assumptions in force</h3>
            <p className="banner">
              Transfer time, transfer cost, and promo demand uplift were not specified by the challenge.
              VoltPilot treats them as configurable assumptions and shows them on every recommendation.
            </p>
            <table>
              <tbody>
                {data.assumptions.slice(0, 6).map((a) => (
                  <tr key={a.key}>
                    <td className="mono">{a.key}</td>
                    <td>{a.value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </div>
      </div>
    </div>
  );
}

function Kpi({ label, value }) {
  return (
    <div className="card">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
    </div>
  );
}


const riskIconMap = {
  stockout: TrendingUp,
  ageing: Archive,
  promotions: CalendarDays,
  launches: RefreshCw,
  suppliers: Truck,
  imbalance: Network,
  "purchase-orders": Clock3,
};

function RiskAreaCard({ item, onClick }) {
  const Icon = riskIconMap[item.id] || Activity;
  const stateLabel = item.status === "needs_data" ? "Needs data" : item.status === "active" ? "Issues detected" : "No current issues";
  const stateClass = item.status === "needs_data" ? "needs-data" : item.status === "active" ? "active" : "clear";
  return (
    <button className="risk-area-card" onClick={onClick} type="button">
      <div className="risk-area-card-top"><span className="risk-area-number">{item.number}</span><span className={`risk-area-state ${stateClass}`}>{stateLabel}</span></div>
      <div className="risk-area-icon"><Icon size={19}/></div>
      <h4>{item.title}</h4>
      <p>{item.short}</p>
      <div className="risk-area-card-bottom"><strong>{item.status === "needs_data" ? "Data required" : `${item.issue_count} finding${item.issue_count === 1 ? "" : "s"}`}</strong><span>Investigate <ChevronRight size={14}/></span></div>
    </button>
  );
}
