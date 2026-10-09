import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, ArrowRight, CheckCircle2, Database, RefreshCw, LoaderCircle } from "lucide-react";
import { api } from "../api.js";
import { findMatchingDecision } from "../utils/recommendationRouting.js";

export default function RiskAreasPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [area, setArea] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [openingKey, setOpeningKey] = useState("");

  async function load(quiet = false) {
    if (!quiet) setLoading(true);
    setError("");
    try { setArea(await api.riskArea(id)); }
    catch (e) { setError(e.message || "Could not load this risk area."); }
    finally { if (!quiet) setLoading(false); }
  }

  useEffect(() => {
    load();
    const timer = window.setInterval(() => load(true), 10000);
    return () => window.clearInterval(timer);
    // load reads only the route id and is intentionally local to this page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function openSolution(finding, index) {
    const key = `${id}-${index}`;
    setOpeningKey(key);
    try {
      if (id === "launches" || area?.status === "needs_data") {
        navigate(`/risk-areas/${id}/solution/${index}`);
        return;
      }
      // Ask the backend to recalculate current decisions, then open the relevant
      // decision page directly. Never route this button to the generic Radar.
      const response = await api.recommendations(true);
      const decision = findMatchingDecision(id, finding, response?.items || []);
      if (decision?.id != null) {
        navigate(`/decision/${decision.id}`);
      } else {
        // Some risk findings (e.g. a promo signal with no stockout yet) won't
        // have an executable decision. Still open an issue-specific solution view.
        navigate(`/risk-areas/${id}/solution/${index}`);
      }
    } catch {
      // The specific evidence/solution workspace remains available even if the
      // recommendation API is temporarily unavailable.
      navigate(`/risk-areas/${id}/solution/${index}`);
    } finally {
      setOpeningKey("");
    }
  }

  if (loading) return <div className="state">Investigating risk area…</div>;
  if (error) return <div className="err-banner">{error}<div className="row" style={{ marginTop: 12 }}><button className="btn" onClick={() => load()}><RefreshCw size={14}/> Retry</button><Link className="btn" to="/">Command Center</Link></div></div>;
  if (!area) return null;

  const needsData = area.status === "needs_data";
  return <div>
    <div className="topbar">
      <div>
        <Link className="muted risk-back" to="/"><ArrowLeft size={14}/> Back to Command Center</Link>
        <p className="eyebrow">Seven Retail Risk Areas · Investigation {area.number}</p>
        <h2 className="page-title">{area.title}</h2>
        <p className="sub">{area.description}</p>
      </div>
      <div><button className="btn" onClick={() => load()} disabled={loading}><RefreshCw size={14}/> Refresh analysis</button>{area.last_analyzed_at ? <p className="muted" style={{fontSize: 11, marginTop: 6}}>Recalculated {new Date(area.last_analyzed_at).toLocaleTimeString()}</p> : null}</div>
    </div>

    <div className="risk-detail-summary card">
      <div><div className="kpi-label">Detection status</div><div className="risk-detail-value">{needsData ? "Needs data" : area.status === "active" ? "Issues detected" : "No current issues detected"}</div></div>
      <div><div className="kpi-label">Findings</div><div className="risk-detail-value">{area.issue_count}</div></div>
      <div><div className="kpi-label">Highest severity</div><div className="risk-detail-value">{area.severity}</div></div>
    </div>

    {needsData ? <section className="banner risk-data-banner"><Database size={17}/><div><strong>Required data is missing</strong><p>{area.data_note || "This detector needs additional product or event data."}</p></div></section> : null}
    {!needsData && area.findings.length === 0 ? <section className="card risk-empty"><CheckCircle2 size={24}/><h3>No matching issues in the current data</h3><p className="muted">This detector did not find a finding under its configured rules. It does not prove the business can never have this risk.</p></section> : null}

    <div className="risk-findings">
      {area.findings.map((finding, index) => {
        const isLatePurchaseOrder = area.id === "purchase-orders";
        const isMissingLaunchData = area.id === "launches" || needsData;
        const poNumber = finding.metrics?.po_number;
        const key = `${id}-${index}`;
        const opening = openingKey === key;
        return <section className="card risk-finding" key={`${finding.title}-${index}`}>
          <div className="risk-finding-head">
            <div><span className={`pill ${finding.severity}`}>{finding.severity}</span><h3>{finding.title}</h3><p className="muted">{finding.product}{finding.store && finding.store !== "—" ? ` · ${finding.store}` : ""}</p></div>
            <span className="risk-finding-number">#{String(index + 1).padStart(2, "0")}</span>
          </div>
          <div className="risk-evidence-grid">
            <div><h4>Evidence</h4><ul>{(finding.evidence || []).map((item, i) => <li key={i}>{item}</li>)}</ul></div>
            <div className="risk-recommendation">
              <h4>{isMissingLaunchData ? "Data needed" : "Recommended next step"}</h4>
              <p>{finding.recommendation}</p>
              <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
                {isLatePurchaseOrder ? <Link className="btn" to={`/suppliers${poNumber ? `?poNumber=${encodeURIComponent(poNumber)}` : ""}`}>Update supplier delivery <ArrowRight size={14}/></Link> : null}
                <button type="button" className="btn primary" onClick={() => openSolution(finding, index)} disabled={opening}>
                  {opening ? <><LoaderCircle size={14}/> Opening solution…</> : <>{isMissingLaunchData ? "View data requirements" : "Review agent recommendations"} <ArrowRight size={14}/></>}
                </button>
              </div>
            </div>
          </div>
        </section>;
      })}
    </div>

    <p className="muted risk-data-footnote"><Database size={13}/> {area.data_origin} · Findings recalculate from the current database. Only objectives affected by changed evidence should change after a sale.</p>
  </div>;
}
