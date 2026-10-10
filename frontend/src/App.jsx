import { NavLink, Route, Routes } from "react-router-dom";
import {
  Activity, BrainCircuit, Boxes, ClipboardList, Radar, ShieldCheck, Truck, Zap, Store, Clock3,
} from "lucide-react";
import Overview from "./pages/Overview.jsx";
import RadarPage from "./pages/RadarPage.jsx";
import InventoryPage from "./pages/InventoryPage.jsx";
import InventoryAgeingPage from "./pages/InventoryAgeingPage.jsx";
import SuppliersPage from "./pages/SuppliersPage.jsx";
import DecisionPage from "./pages/DecisionPage.jsx";
import AuditPage from "./pages/AuditPage.jsx";
import ForecastLab from "./pages/ForecastLab.jsx";
import RiskAreasPage from "./pages/RiskAreasPage.jsx";
import RiskSolutionPage from "./pages/RiskSolutionPage.jsx";
import StorePOS from "./pages/StorePOS.jsx";

const links = [
  { to: "/", label: "Command Center", icon: Activity },
  { to: "/radar", label: "Attention Radar", icon: Radar },
  { to: "/inventory", label: "Inventory Network", icon: Boxes },
  { to: "/ageing", label: "Inventory Ageing", icon: Clock3 },
  { to: "/store", label: "Store & POS", icon: Store },
  { to: "/forecast", label: "Forecast Lab", icon: BrainCircuit },
  { to: "/suppliers", label: "Suppliers & POs", icon: Truck },
  { to: "/audit", label: "Action Ledger", icon: ClipboardList },
];

export default function App() {
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><Zap size={18} /></div>
          <div><h1>VoltPilot</h1><p>VoltKart decision agent</p></div>
        </div>
        <nav className="nav">
          {links.map((link) => (
            <NavLink key={link.to} to={link.to} end={link.to === "/"} className={({ isActive }) => (isActive ? "active" : "")}>
              <link.icon size={18} />{link.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <ShieldCheck size={14} /> Human approval required. Supplier and payment actions are simulated.
        </div>
      </aside>
      <main className="main">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/radar" element={<RadarPage />} />
          <Route path="/risk-areas/:id/solution/:findingIndex" element={<RiskSolutionPage />} />
          <Route path="/risk-areas/:id" element={<RiskAreasPage />} />
          <Route path="/inventory" element={<InventoryPage />} />
          <Route path="/ageing" element={<InventoryAgeingPage />} />
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
