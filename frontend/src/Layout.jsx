import React from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import {
  House, Users, CalendarCheck, CheckSquare, Megaphone, Plugs, BookOpen, Bell,
  SignOut, Sparkle, CaretRight, Trophy, Lightbulb, MagnifyingGlass,
  WarningCircle,
} from "@phosphor-icons/react";
import { useAuth } from "./auth";
import { clients as clientsApi, meetings as meetingsApi, docs as docsApi } from "./api";
import { applyDisplayMode, getSavedDisplayMode } from "./displayMode";

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

const NAV_BASE = [
  { to: "/", label: "Dashboard", icon: House, end: true, testid: "nav-dashboard" },
  { to: "/clients", label: "Clients", icon: Users, testid: "nav-clients" },
  { to: "/meetings", label: "Meetings", icon: CalendarCheck, testid: "nav-meetings" },
  { to: "/wins", label: "Wins Library", icon: Trophy, testid: "nav-wins" },
  { to: "/issues", label: "Issues Library", icon: WarningCircle, testid: "nav-issues" },
  { to: "/actions", label: "Action Items", icon: CheckSquare, testid: "nav-actions" },
  { to: "/follow-up", label: "Follow-Up", icon: Bell, testid: "nav-follow-up" },
  { to: "/opportunities", label: "Opportunities", icon: Megaphone, testid: "nav-opportunities" },
  { to: "/testimonials", label: "Testimonials", icon: Trophy, testid: "nav-testimonials" },
  { to: "/strategy", label: "Strategy", icon: Lightbulb, testid: "nav-strategy" },
  { to: "/integrations", label: "Integrations", icon: Plugs, testid: "nav-integrations" },
  { to: "/white-label", label: "White Label", icon: Sparkle, testid: "nav-white-label" },
  { to: "/docs", label: "Dashboard Wiki", icon: BookOpen, testid: "nav-docs" },
];

export default function Layout({ children }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const nav = React.useMemo(() => {
    const base = [...NAV_BASE];
    if (user?.role === "admin") {
      const idx = base.findIndex((x) => x.to === "/integrations");
      const insertAt = idx === -1 ? base.length : idx;
      base.splice(insertAt, 0, { to: "/ai-visibility", label: "AI Visibility", icon: MagnifyingGlass, testid: "nav-ai-visibility" });
    }
    return base;
  }, [user?.role]);
  const [displayMode, setDisplayMode] = React.useState("dark");
  const [displayOpen, setDisplayOpen] = React.useState(false);
  const displayRef = React.useRef(null);
  const [searchOpen, setSearchOpen] = React.useState(false);
  const [searchQ, setSearchQ] = React.useState("");
  const [searchLoading, setSearchLoading] = React.useState(false);
  const [searchErr, setSearchErr] = React.useState("");
  const [searchData, setSearchData] = React.useState({ clients: [], meetings: [], docs: [] });
  const searchInputRef = React.useRef(null);
  const isMac = (() => {
    try { return /Mac|iPhone|iPad|iPod/.test(navigator.platform); } catch (e) { return false; }
  })();
  React.useEffect(() => {
    try {
      setDisplayMode(getSavedDisplayMode());
    } catch (e) {}
  }, []);
  React.useEffect(() => {
    if (!displayOpen) return;
    const onDown = (e) => {
      if (!displayRef.current) return;
      if (!displayRef.current.contains(e.target)) setDisplayOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [displayOpen]);

  React.useEffect(() => {
    const onKey = (e) => {
      const tag = String(e?.target?.tagName || "").toLowerCase();
      const isEditable = tag === "input" || tag === "textarea" || tag === "select" || !!e?.target?.isContentEditable;
      if (isEditable) return;
      const key = String(e.key || "").toLowerCase();
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && key === "k") {
        e.preventDefault();
        setSearchOpen(true);
        return;
      }
      if (!e.metaKey && !e.ctrlKey && !e.altKey && key === "/") {
        e.preventDefault();
        setSearchOpen(true);
        return;
      }
      if (key === "escape") {
        setSearchOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  React.useEffect(() => {
    if (!searchOpen) return;
    setSearchErr("");
    setSearchQ("");
    setTimeout(() => { try { searchInputRef.current?.focus?.(); } catch (e) {} }, 0);
    if ((searchData.clients || []).length || (searchData.meetings || []).length || (searchData.docs || []).length) return;
    setSearchLoading(true);
    Promise.all([
      clientsApi.list().catch(() => []),
      meetingsApi.list().catch(() => []),
      docsApi.list().catch(() => ({ items: [] })),
    ]).then(([clients, meetings, docs]) => {
      setSearchData({
        clients: Array.isArray(clients) ? clients : [],
        meetings: Array.isArray(meetings) ? meetings : [],
        docs: Array.isArray(docs?.items) ? docs.items : [],
      });
    }).catch(() => {
      setSearchErr("Search is unavailable right now.");
    }).finally(() => {
      setSearchLoading(false);
    });
  }, [searchOpen, searchData.clients, searchData.docs, searchData.meetings]);

  const searchQuery = String(searchQ || "").trim().toLowerCase();
  const clientMatches = (searchData.clients || [])
    .filter((c) => !searchQuery || `${c?.name || ""} ${c?.company || ""}`.toLowerCase().includes(searchQuery))
    .slice(0, 8);
  const meetingMatches = (searchData.meetings || [])
    .filter((m) => !searchQuery || `${m?.title || ""} ${m?.client_name || ""}`.toLowerCase().includes(searchQuery))
    .slice(0, 8);
  const docMatches = (searchData.docs || [])
    .filter((d) => !searchQuery || `${d?.title || ""} ${d?.summary || ""}`.toLowerCase().includes(searchQuery))
    .slice(0, 8);

  const openSearch = () => setSearchOpen(true);
  const goto = (to) => { setSearchOpen(false); navigate(to); };
  return (
    <div className="app-bg min-h-screen flex">
      {/* Sidebar */}
      <aside className="hidden md:flex md:flex-col w-64 shrink-0 border-r border-white/5 px-4 py-5 sticky top-0 h-screen">
        <Brand />
        <nav className="mt-8 flex flex-col gap-1" data-testid="sidebar-nav">
          {nav.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => `sidebar-link ${isActive ? "active" : ""}`} data-testid={n.testid}>
              <n.icon size={18} weight="duotone" />
              <span>{n.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto">
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
          <button
            type="button"
            className="hidden md:flex items-center gap-3 px-3 py-2 rounded-md border border-white/10 bg-white/[0.02] hover:bg-white/[0.04] text-left min-w-[420px]"
            onClick={openSearch}
            data-testid="global-search-trigger"
          >
            <div className="flex items-center gap-1 text-xs text-slate-400">
              {isMac ? (<><span className="kbd">⌘</span><span className="kbd">⇧</span><span className="kbd">K</span><span className="text-slate-500 mx-1">or</span><span className="kbd">/</span></>) : (<><span className="kbd">Ctrl</span><span className="kbd">⇧</span><span className="kbd">K</span><span className="text-slate-500 mx-1">or</span><span className="kbd">/</span></>)}
            </div>
            <div className="text-xs text-slate-400 truncate">Search clients, meetings, wiki…</div>
          </button>
          <div className="flex items-center gap-3 text-sm">
            <div className="relative" ref={displayRef}>
              <button className="btn-ghost !py-1.5 !px-3 text-xs" type="button" onClick={() => setDisplayOpen((v) => !v)} data-testid="display-toggle">
                Display: {displayMode === "easy" ? "Easy" : displayMode === "light" ? "Light" : "Dark"}
              </button>
              {displayOpen && (
                <div className="absolute right-0 mt-2 w-44 card-flat p-1 z-30">
                  {[
                    { key: "dark", label: "Dark" },
                    { key: "light", label: "Light" },
                    { key: "easy", label: "Easy read" },
                  ].map((o) => (
                    <button
                      key={o.key}
                      type="button"
                      className={`w-full text-left px-3 py-2 rounded text-[13px] ${displayMode === o.key ? "bg-[#3FA9F5]/15 text-[var(--text)]" : "text-[var(--text-muted)] hover:bg-black/5"}`}
                      onClick={() => {
                        const m = applyDisplayMode(o.key);
                        setDisplayMode(m);
                        setDisplayOpen(false);
                      }}
                    >
                      {o.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <span className="chip chip-success" data-testid="status-chip"><span className="pulse-dot" /> Live</span>
          </div>
        </header>
        <div className="p-6 md:p-8 max-w-[1500px] mx-auto">{children}</div>
      </main>

      {searchOpen && (
        <div className="fixed inset-0 z-40 bg-black/60 flex items-start justify-center p-4" onClick={() => setSearchOpen(false)}>
          <div className="card-flat p-5 w-full max-w-2xl mt-16" onClick={(e) => e.stopPropagation()} data-testid="global-search-modal">
            <div className="flex items-center justify-between gap-3 mb-3">
              <div className="font-semibold">Search</div>
              <button className="btn-ghost !py-1 !px-2 text-xs" type="button" onClick={() => setSearchOpen(false)}>Esc</button>
            </div>
            <input
              ref={searchInputRef}
              className="input !py-2"
              value={searchQ}
              onChange={(e) => setSearchQ(e.target.value)}
              onKeyDown={(e) => {
                if (e.key !== "Enter") return;
                if (clientMatches[0]?.id) goto(`/clients/${clientMatches[0].id}`);
                else if (meetingMatches[0]?.id) goto(`/meetings/${meetingMatches[0].id}`);
                else if (docMatches[0]) goto("/docs");
              }}
              placeholder="Type a client, meeting, or wiki page…"
              aria-label="Search"
            />
            {searchErr && <div className="mt-3 text-xs text-rose-200">{searchErr}</div>}
            {searchLoading && <div className="mt-4 text-sm text-slate-400">Loading…</div>}
            {!searchLoading && !searchErr && (
              <div className="mt-4 space-y-4">
                <div>
                  <div className="label mb-2">Clients</div>
                  {clientMatches.length === 0 && <div className="text-xs text-slate-400">No clients found.</div>}
                  <div className="space-y-1">
                    {clientMatches.map((c) => (
                      <button
                        key={c.id}
                        type="button"
                        className="w-full text-left px-3 py-2 rounded-md hover:bg-white/[0.04] border border-white/5"
                        onClick={() => goto(`/clients/${c.id}`)}
                      >
                        <div className="text-sm text-slate-200">{c.name || "Client"}</div>
                        <div className="text-xs text-slate-400">{c.company || "—"}</div>
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <div className="label mb-2">Meetings</div>
                  {meetingMatches.length === 0 && <div className="text-xs text-slate-400">No meetings found.</div>}
                  <div className="space-y-1">
                    {meetingMatches.map((m) => (
                      <button
                        key={m.id}
                        type="button"
                        className="w-full text-left px-3 py-2 rounded-md hover:bg-white/[0.04] border border-white/5"
                        onClick={() => goto(`/meetings/${m.id}`)}
                      >
                        <div className="text-sm text-slate-200">{m.title || "Meeting"}</div>
                        <div className="text-xs text-slate-400">{m.client_name || "—"}</div>
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <div className="label mb-2">Dashboard Wiki</div>
                  {docMatches.length === 0 && <div className="text-xs text-slate-400">No wiki pages found.</div>}
                  <div className="space-y-1">
                    {docMatches.map((d) => (
                      <button
                        key={d.slug || d.title}
                        type="button"
                        className="w-full text-left px-3 py-2 rounded-md hover:bg-white/[0.04] border border-white/5"
                        onClick={() => goto("/docs")}
                      >
                        <div className="text-sm text-slate-200">{d.title || "Wiki page"}</div>
                        <div className="text-xs text-slate-400 truncate">{d.summary || "—"}</div>
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
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
                    {b.to ? <Link className="hover:text-[var(--text)]" to={b.to}>{b.label}</Link> : <span>{b.label}</span>}
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
