import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, inr } from "../api.js";

export default function RadarPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    api
      .recommendations()
      .then(setData)
      .catch((err) => setError(err.message));
  }, []);

  if (error) return <div className="err-banner">{error}</div>;
  if (!data) return <div className="state">Ranking issues…</div>;

  const pending = data.items.filter((i) => i.status === "pending");

  return (
    <div>
      <div className="topbar">
        <div>
          <p className="eyebrow">Prioritized worklist</p>
          <h2 className="page-title">Attention Radar</h2>
          <p className="sub">{data.score_explainer}</p>
        </div>
      </div>
      <section className="card">
        {pending.length === 0 ? (
          <div className="state">No pending recommendations. Open Action Ledger or reset the demo.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Score</th>
                <th>Issue</th>
                <th>Severity</th>
                <th>Why now</th>
                <th>Impact</th>
                <th>Confidence</th>
                <th>Next step</th>
              </tr>
            </thead>
            <tbody>
              {pending.map((item) => (
                <tr className="clickable" key={item.id} onClick={() => navigate(`/decision/${item.id}`)}>
                  <td className="mono">{item.score}</td>
                  <td>
                    <strong>{item.title}</strong>
                    <div className="muted">{item.product_name} · {item.store_name}</div>
                  </td>
                  <td><span className={`pill ${item.severity}`}>{item.severity}</span></td>
                  <td className="muted">{item.why_now}</td>
                  <td>{inr(item.impact_inr)}</td>
                  <td>{Math.round(item.confidence * 100)}%</td>
                  <td>{item.recommended_next_step}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
