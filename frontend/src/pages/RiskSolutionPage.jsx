import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, ArrowRight, RefreshCw, Database, ShieldCheck, AlertTriangle } from "lucide-react";
import { api } from "../api.js";
import { findMatchingDecision } from "../utils/recommendationRouting.js";

export default function RiskSolutionPage() {
  const { id, findingIndex } = useParams();
  const navigate = useNavigate();
  const [area, setArea] = useState(null);
  const [finding, setFinding] = useState(null);
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const result = await api.riskArea(id);
      const index = Number.parseInt(findingIndex, 10);
      const selected = Number.isInteger(index) ? result.findings?.[index] : null;
      if (!selected) throw new Error("This finding no longer exists in the latest analysis. Return to the objective and refresh its findings.");
      setArea(result);
      setFinding(selected);
    } catch (err) {
      setError(err.message || "Could not load the issue-specific solution workspace.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); /* route params define the specific finding */ }, [id, findingIndex]);

  async function recheckDecision() {
    setChecking(true);
    setNotice("");
    try {
      const data = await api.recommendations(true);
      const match = findMatchingDecision(id, finding, data?.items || []);
      if (match?.id != null) {
        navigate(`/decision/${match.id}`);
      } else {
        setNotice("The decision engine did not produce a matching pending decision for this exact finding. No action was executed. The evidence and recommended next step below remain available.");
      }
    } catch (err) {
      setNotice(`Could not refresh decisions: ${err.message || "API error"}. No action was executed.`);
    } finally {
      setChecking(false);
    }
  }

  if (loading) return <div className="state">Opening issue-specific solution…</div>;
  if (error) return <div className="err-banner">{error}<div className="row" style={{ marginTop: 12 }}><Link className="btn" to={`/risk-areas/${id}`}>Back to finding</Link></div></div>;
  if (!area || !finding) return null;

  const poNumber = finding.metrics?.po_number;
  const isLaunch = id === "launches" || area.status === "needs_data";
  return <div>
    <div className="topbar">
      <div>
        <Link className="muted risk-back" to={`/risk-areas/${id}`}><ArrowLeft size={14}/> Back to {area.title}</Link>
        <p className="eyebrow">VoltPilot · Issue-specific solution workspace</p>
        <h2 className="page-title">{finding.title}</h2>
        <p className="sub">This page is scoped to the selected finding; it does not send you to the generic Attention Radar.</p>
      </div>
      <span className={`pill ${finding.severity}`}>{finding.severity}</span>
    </div>

    {notice ? <div className="banner" role="status" style={{ marginBottom: 16 }}>{notice}</div> : null}

    <div className="grid two">
      <section className="card">
        <h3><AlertTriangle size={17} style={{ verticalAlign: "text-bottom", marginRight: 7 }}/>Why this needs attention</h3>
        <p>{finding.recommendation}</p>
        <ul>{(finding.evidence || []).map((item, index) => <li key={index}>{item}</li>)}</ul>
      </section>
      <section className="card">
        <h3><ShieldCheck size={17} style={{ verticalAlign: "text-bottom", marginRight: 7 }}/>Proposed response</h3>
        {isLaunch ? <>
          <p>The detector cannot make an evidence-backed launch-impact recommendation until the missing product relationships and dates are recorded.</p>
          <div className="banner"><Database size={16}/> {area.data_note || "Add model family, predecessor/successor SKU, launch date and pre/post-launch sales history."}</div>
        </> : <>
          <p>{finding.recommendation}</p>
          <p className="muted">The existing finding provides an evidence-based next step. An executable decision record is only available when the decision engine has generated a matching pending recommendation for this product and store.</p>
        </>}
        <div className="row" style={{ marginTop: 14, flexWrap: "wrap" }}>
          {!isLaunch ? <button className="btn primary" onClick={recheckDecision} disabled={checking}>{checking ? <><RefreshCw size={14} className="spin"/> Checking decisions…</> : <>Find matching agent decision <ArrowRight size={14}/></>}</button> : null}
          {id === "purchase-orders" ? <Link className="btn" to={`/suppliers${poNumber ? `?poNumber=${encodeURIComponent(poNumber)}` : ""}`}>Update supplier delivery <ArrowRight size={14}/></Link> : null}
          <Link className="btn" to={`/risk-areas/${id}`}>Return to findings</Link>
        </div>
      </section>
    </div>

    <section className="card" style={{ marginTop: 16 }}>
      <h3>Execution status</h3>
      <p className="muted">No inventory, purchase order, supplier record or payment has been changed from this solution workspace. Any consequential operation must be opened as a matching agent decision and explicitly approved by a manager.</p>
    </section>
  </div>;
}
