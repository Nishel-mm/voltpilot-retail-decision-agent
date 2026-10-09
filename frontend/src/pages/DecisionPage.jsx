import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, inr, inrExact } from "../api.js";

export default function DecisionPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [rec, setRec] = useState(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState("");
  const [modal, setModal] = useState(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState("");

  async function load() {
    try {
      const data = await api.recommendation(id);
      setRec(data);
      setSelected(data.recommended_option_id);
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => {
    load();
  }, [id]);

  if (error) return <div className="err-banner">{error}</div>;
  if (!rec) return <div className="state">Investigating issue…</div>;

  const chosen = rec.options.find((o) => o.id === selected) || rec.recommended_option;
  const locked = rec.status !== "pending";

  async function confirm() {
    setBusy(true);
    setError("");
    try {
      if (modal === "approve") {
        const result = await api.approve(rec.id, chosen.id, note);
        setFlash(result.message);
      } else {
        const result = await api.reject(rec.id, note);
        setFlash(result.message);
      }
      setModal(null);
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="topbar">
        <div>
          <p className="eyebrow">Investigate → compare → approve</p>
          <h2 className="page-title">{rec.title}</h2>
          <p className="sub">{rec.why_now}</p>
        </div>
        <div className="row">
          <span className={`pill ${rec.severity}`}>{rec.severity}</span>
          <span className={`pill ${rec.status}`}>{rec.status}</span>
        </div>
      </div>

      {flash ? <div className="ok-banner" style={{ marginBottom: 16 }}>{flash}</div> : null}
      {error ? <div className="err-banner" style={{ marginBottom: 16 }}>{error}</div> : null}

      <div className="grid two">
        <section className="card">
          <h3>Evidence</h3>
          <p>{rec.expected_impact}</p>
          <p className="muted">Confidence {Math.round(rec.confidence * 100)}% — {rec.confidence_note}</p>
          <ul>
            {rec.evidence.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          <p className="muted">{rec.score_explainer} Current score {rec.score}.</p>
        </section>
        <section className="card">
          <h3>What-if across stores</h3>
          <table>
            <thead>
              <tr>
                <th>Store</th>
                <th>Qty</th>
                <th>Velocity</th>
                <th>Cover</th>
              </tr>
            </thead>
            <tbody>
              {rec.network.map((row) => (
                <tr key={row.store_id}>
                  <td>{row.store_name}</td>
                  <td>{row.quantity}</td>
                  <td>{row.velocity}</td>
                  <td>{row.cover_label}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>

      <section className="card" style={{ marginTop: 16 }}>
        <h3>Decision comparison</h3>
        <p className="banner">
          Assumptions used: promo uplift, transfer days, transfer cost, and safety cover.
          They are not VoltKart ERP facts.
        </p>
        <div className="grid three" style={{ marginTop: 12 }}>
          {rec.options.map((option) => (
            <button
              key={option.id}
              className={`option ${option.id === rec.recommended_option_id ? "recommended" : ""} ${option.id === selected ? "selected" : ""}`}
              onClick={() => setSelected(option.id)}
              disabled={locked}
              style={{ textAlign: "left", color: "inherit" }}
            >
              <div className="row" style={{ marginBottom: 8 }}>
                {option.id === rec.recommended_option_id ? <span className="pill Low">Recommended</span> : null}
                {!option.feasible ? <span className="pill Critical">Not feasible</span> : null}
                {option.simulated ? <span className="pill pending">Simulated</span> : null}
              </div>
              <strong>{option.title}</strong>
              <p className="muted">{option.risk}</p>
              <p>Cost {inrExact(option.estimated_cost_inr)}</p>
              <p>Benefit {inr(option.expected_benefit_inr)}</p>
              <p>Available in {option.time_until_available_days} day(s)</p>
            </button>
          ))}
        </div>
        <table style={{ marginTop: 16 }}>
          <thead>
            <tr>
              <th>Option</th>
              <th>Cost</th>
              <th>Benefit</th>
              <th>Time</th>
              <th>Limitations</th>
            </tr>
          </thead>
          <tbody>
            {rec.options.map((option) => (
              <tr key={`row-${option.id}`}>
                <td>{option.title}</td>
                <td>{inrExact(option.estimated_cost_inr)}</td>
                <td>{inr(option.expected_benefit_inr)}</td>
                <td>{option.time_until_available_days}d</td>
                <td className="muted">{option.limitations}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {chosen?.what_if ? (
          <div className="ok-banner" style={{ marginTop: 12 }}>
            What-if: source cover {chosen.what_if.source_cover_before} → {chosen.what_if.source_cover_after};
            destination cover {chosen.what_if.dest_cover_before} → {chosen.what_if.dest_cover_after}.
            {chosen.what_if.creates_source_shortage ? " This transfer would create a shortage at the source store." : " Source stays above the safety-cover assumption."}
          </div>
        ) : null}
      </section>

      <section className="card" style={{ marginTop: 16 }}>
        <h3>Selected action</h3>
        <p><strong>{chosen.title}</strong></p>
        <p className="muted">{chosen.limitations}</p>
        <ul>
          {(chosen.assumptions || []).map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
        <div className="row">
          <button className="btn good" disabled={locked || !chosen.feasible} onClick={() => setModal("approve")}>
            Approve action
          </button>
          <button className="btn danger" disabled={locked} onClick={() => setModal("reject")}>
            Reject action
          </button>
          <button className="btn" onClick={() => navigate("/radar")}>Back to radar</button>
        </div>
      </section>

      {modal ? (
        <div className="modal-back" onClick={() => setModal(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{modal === "approve" ? "Confirm simulated action" : "Reject recommendation"}</h3>
            <p>{chosen.title}</p>
            <p className="muted">
              {modal === "approve"
                ? chosen.simulated
                  ? "This will run a SIMULATED operation. No real supplier order is placed."
                  : "This records a no-action decision."
                : "Rejection is logged. Inventory and purchase orders will not change."}
            </p>
            {chosen.type === "transfer" ? (
              <p>Stock will move immediately between stores in the SQLite database.</p>
            ) : null}
            {chosen.type === "purchase" ? (
              <p>A simulated PO will be created. On-hand stock will NOT increase until goods arrive.</p>
            ) : null}
            <textarea placeholder="Optional manager note" value={note} onChange={(e) => setNote(e.target.value)} />
            <div className="row" style={{ marginTop: 12 }}>
              <button className="btn primary" disabled={busy} onClick={confirm}>
                {busy ? "Working…" : "Confirm"}
              </button>
              <button className="btn" onClick={() => setModal(null)}>Cancel</button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
