import { useEffect, useState } from "react";
import { api } from "../api.js";

export default function AuditPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .actions()
      .then(setData)
      .catch((err) => setError(err.message));
  }, []);

  if (error) return <div className="err-banner">{error}</div>;
  if (!data) return <div className="state">Loading ledger…</div>;

  return (
    <div>
      <div className="topbar">
        <div>
          <p className="eyebrow">Human-in-the-loop</p>
          <h2 className="page-title">Action ledger</h2>
          <p className="sub">Every approve and reject is stored. Rejected decisions never change inventory.</p>
        </div>
      </div>
      <section className="card">
        {data.items.length === 0 ? (
          <div className="state">No decisions yet. Approve or reject an item from Attention Radar.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>When</th>
                <th>Decision</th>
                <th>Issue</th>
                <th>Action</th>
                <th>Executed</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((row) => (
                <tr key={row.id}>
                  <td className="mono">{row.timestamp}</td>
                  <td><span className={`pill ${row.decision}`}>{row.decision}</span></td>
                  <td>
                    {row.title}
                    <div className="muted">{row.product_name} · {row.store_name}</div>
                  </td>
                  <td>{row.option_type || "—"}</td>
                  <td>{row.executed ? "Yes" : "No"}</td>
                  <td className="muted">{row.result}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
