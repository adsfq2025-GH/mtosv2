import React from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import {
  House, Users, CalendarCheck, CheckSquare, Megaphone, Plugs, BookOpen,
  SignOut, Sparkle, CaretRight,
} from "@phosphor-icons/react";
import { useAuth } from "./auth";

export function Brand() {
  return (
    <Link to="/" className="flex items-center gap-3" data-testid="brand-link">
      <div className="relative h-9 w-9 rounded-md flex items-center justify-center" style={{ background: "linear-gradient(135deg,#3FA9F5,#2FE0C2)" }}>
        <CalendarCheck size={20} weight="bold" color="#0A0E1A" />
      </div>
      <div className="leading-tight">
        <div className="text-[15px] font-bold tracking-tight">Monthly Touch <span style={{ color: "#2FE0C2" }}>OS</span></div>
        <div className="text-[10px] text-slate-400 uppercase tracking-[0.18em]">Powered by Map Ranking</div>
      </div>
    </Link>
  );
}

const NAV = [
  { to: "/", label: "Dashboard", icon: House, end: true, testid: "nav-dashboard" },
  { to: "/clients", label: "Clients", icon: Users, testid: "nav-clients" },
  { to: "/meetings", label: "Meetings", icon: CalendarCheck, testid: "nav-meetings" },
  { to: "/actions", label: "Action Items", icon: CheckSquare, testid: "nav-actions" },
  { to: "/content", label: "Content Queue", icon: Megaphone, testid: "nav-content" },
  { to: "/integrations", label: "Integrations", icon: Plugs, testid: "nav-integrations" },
  { to: "/docs", label: "Documentation", icon: BookOpen, testid: "nav-docs" },
];

export default function Layout({ children }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  return (
    <div className="app-bg min-h-screen flex">
      {/* Sidebar */}
      <aside className="hidden md:flex md:flex-col w-64 shrink-0 border-r border-white/5 px-4 py-5 sticky top-0 h-screen">
        <Brand />
        <nav className="mt-8 flex flex-col gap-1" data-testid="sidebar-nav">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => `sidebar-link ${isActive ? "active" : ""}`} data-testid={n.testid}>
              <n.icon size={18} weight="duotone" />
              <span>{n.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto">
          <div className="card-flat p-3 mb-3">
            <div className="flex items-center gap-2 text-xs text-slate-400 mb-2"><Sparkle size={14} weight="duotone" /> AI Engine</div>
            <div className="text-[12.5px] text-slate-300">Claude · GPT-5.2 · Gemini 3</div>
            <div className="text-[11px] text-slate-500 mt-1">Bring-your-own API keys</div>
          </div>
          <div className="flex items-center justify-between">
            <div className="text-[13px]">
              <div className="font-semibold">{user?.name}</div>
              <div className="text-slate-500 text-[11px] uppercase tracking-wider">{user?.role}</div>
            </div>
            <button className="btn-ghost !p-2" onClick={() => { logout(); navigate("/login"); }} data-testid="logout-btn" title="Sign out">
              <SignOut size={16} />
            </button>
          </div>
        </div>
      </aside>

      <main className="flex-1 min-w-0">
        <header className="glass sticky top-0 z-20 px-6 py-3 border-b border-white/5 flex items-center justify-between">
          <div className="md:hidden"><Brand /></div>
          <div className="hidden md:flex items-center gap-2 text-xs text-slate-400">
            <span className="kbd">⌘</span><span className="kbd">K</span>
            <span className="ml-2">Search clients, meetings, docs…</span>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span className="chip chip-success" data-testid="status-chip"><span className="pulse-dot" /> Live</span>
          </div>
        </header>
        <div className="p-6 md:p-8 max-w-[1500px] mx-auto">{children}</div>
      </main>
    </div>
  );
}

export function PageHead({ title, subtitle, actions, breadcrumbs }) {
  return (
    <div className="flex items-start justify-between mb-6 gap-4 flex-wrap animate-fade-up">
      <div>
        {breadcrumbs && (
          <div className="flex items-center gap-1.5 text-xs text-slate-400 mb-2">
            {breadcrumbs.map((b, i) => (
              <React.Fragment key={i}>
                {b.to ? <Link className="hover:text-white" to={b.to}>{b.label}</Link> : <span>{b.label}</span>}
                {i < breadcrumbs.length - 1 && <CaretRight size={12} />}
              </React.Fragment>
            ))}
          </div>
        )}
        <h1 className="text-2xl md:text-3xl font-bold tracking-tight">{title}</h1>
        {subtitle && <p className="text-slate-400 mt-1 text-[14.5px] max-w-3xl">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
