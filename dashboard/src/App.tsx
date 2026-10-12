import { Link, NavLink, Route, Routes } from "react-router-dom";
import HomePage from "./pages/HomePage";
import RunDetailPage from "./pages/RunDetailPage";
import NewAuditPage from "./pages/NewAuditPage";

export default function App() {
  return (
    <div className="min-h-screen">
      <header className="border-b border-ink/10 bg-white/70 backdrop-blur-sm">
        <div className="mx-auto flex max-w-6xl items-baseline justify-between gap-6 px-6 py-5">
          <Link to="/" className="group">
            <p className="font-display text-2xl font-bold tracking-tight text-ink transition group-hover:text-sea">
              SEO Agentic Solutions
            </p>
            <p className="text-sm text-ink/60">Audit · Prioritize · Remediate</p>
          </Link>
          <nav className="flex gap-5 text-sm font-medium">
            <NavLink
              to="/"
              className={({ isActive }) =>
                isActive ? "text-sea" : "text-ink/70 hover:text-ink"
              }
              end
            >
              Runs
            </NavLink>
            <NavLink
              to="/new"
              className={({ isActive }) =>
                isActive ? "text-sea" : "text-ink/70 hover:text-ink"
              }
            >
              New audit
            </NavLink>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-10">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/new" element={<NewAuditPage />} />
          <Route path="/runs/:runId" element={<RunDetailPage />} />
        </Routes>
      </main>
    </div>
  );
}
