import { NavLink, Route, Routes, useNavigate } from "react-router-dom";
import {
  Activity,
  BrainCircuit,
  Boxes,
  ClipboardList,
  Radar,
  ShieldCheck,
  Truck,
  Zap,
  Store,
} from "lucide-react";
import Overview from "./pages/Overview.jsx";
import RadarPage from "./pages/RadarPage.jsx";
import InventoryPage from "./pages/InventoryPage.jsx";
import SuppliersPage from "./pages/SuppliersPage.jsx";
import DecisionPage from "./pages/DecisionPage.jsx";
import AuditPage from "./pages/AuditPage.jsx";
import ForecastLab from "./pages/ForecastLab.jsx";
import RiskAreasPage from "./pages/RiskAreasPage.jsx";
import RiskSolutionPage from "./pages/RiskSolutionPage.jsx";
import StorePOS from "./pages/StorePOS.jsx";
import { api } from "./api.js";
import { useState } from "react";

const links = [
  { to: "/", label: "Command Center", icon: Activity },
  { to: "/radar", label: "Attention Radar", icon: Radar },
  { to: "/inventory", label: "Inventory Network", icon: Boxes },
  { to: "/store", label: "Store & POS", icon: Store },
  { to: "/forecast", label: "Forecast Lab", icon: BrainCircuit },
  { to: "/suppliers", label: "Suppliers & POs", icon: Truck },
  { to: "/audit", label: "Action Ledger", icon: ClipboardList },
];

export default function App() {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState("");

  async function resetDemo() {
    if (!window.confirm("Reset the demo to the 9 Oct 2026 festival snapshot?")) return;
    setBusy(true);
    try {
      const result = await api.reset();
      setToast(result.message);
      navigate("/");
      window.location.reload();
    } catch (err) {
      setToast(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <Zap size={18} />
          </div>
          <div>
            <h1>VoltPilot</h1>
            <p>VoltKart decision agent</p>
          </div>
        </div>
        <nav className="nav">
          {links.map((link) => (
            <NavLink key={link.to} to={link.to} end={link.to === "/"} className={({ isActive }) => (isActive ? "active" : "")}>
              <link.icon size={18} />
              {link.label}
            </NavLink>
          ))}
        </nav>
        <button className="btn" onClick={resetDemo} disabled={busy}>
          Reset demo
        </button>
        <div className="sidebar-foot">
          <ShieldCheck size={14} /> Human approval required. All supplier actions are simulated.
          {toast ? <div style={{ marginTop: 8 }}>{toast}</div> : null}
        </div>
      </aside>
      <main className="main">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/radar" element={<RadarPage />} />
          <Route path="/risk-areas/:id/solution/:findingIndex" element={<RiskSolutionPage />} />
          <Route path="/risk-areas/:id/solution/:findingIndex" element={<RiskSolutionPage />} />
          <Route path="/risk-areas/:id" element={<RiskAreasPage />} />
          <Route path="/inventory" element={<InventoryPage />} />
          <Route path="/store" element={<StorePOS />} />
          <Route path="/store/receipt/:saleId" element={<StorePOS />} />
          <Route path="/forecast" element={<ForecastLab />} />
          <Route path="/suppliers" element={<SuppliersPage />} />
          <Route path="/decision/:id" element={<DecisionPage />} />
          <Route path="/audit" element={<AuditPage />} />
        </Routes>
      </main>
    </div>
  );
}
