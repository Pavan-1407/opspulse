import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import "./styles.css";
import Overview from "./pages/Overview";
import Queue from "./pages/Queue";
import Workbench from "./pages/Workbench";
import ForecastPage from "./pages/Forecast";
import ModelPage from "./pages/Model";
import Intake from "./pages/Intake";

const NAV = [
  { to: "/", label: "Overview", icon: "▦" },
  { to: "/queue", label: "Work queue", icon: "☰" },
  { to: "/workbench", label: "Analyst workbench", icon: "◷" },
  { to: "/forecast", label: "Forecast & capacity", icon: "↗" },
  { to: "/model", label: "Model card", icon: "◎" },
  { to: "/intake", label: "Intake & upload", icon: "⇪" },
];

function App() {
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <img src="/favicon.svg" alt="" width={28} height={28} />
          <div>
            <strong>OpsPulse</strong>
            <span>Operations intelligence</span>
            <small className="tagline">Work Management | SLA Risk | Forecasting</small>
          </div>
        </div>
        <nav>
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === "/"} className={({ isActive }) => (isActive ? "active" : "")}>
              <span className="nav-icon" aria-hidden>{n.icon}</span>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          Demo on synthetic data.
          <br />
          <a href="/docs" target="_blank" rel="noreferrer">API docs</a>
        </div>
      </aside>
      <main className="content">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/queue" element={<Queue />} />
          <Route path="/workbench" element={<Workbench />} />
          <Route path="/forecast" element={<ForecastPage />} />
          <Route path="/model" element={<ModelPage />} />
          <Route path="/intake" element={<Intake />} />
        </Routes>
      </main>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
