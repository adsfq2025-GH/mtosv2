import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { clients, libraries, users } from "../api";
import { PageHead } from "../Layout";
import { useAuth } from "../auth";

const isoDate = (d) => {
  try {
    return new Date(d).toISOString().slice(0, 10);
  } catch (e) {
    return "";
  }
};

const last30 = () => {
  const end = new Date();
  const start = new Date();
  start.setDate(end.getDate() - 30);
  return { start: isoDate(start), end: isoDate(end) };
};

export default function WinsLibrary() {
  const { user } = useAuth();
  const [start, setStart] = useState(last30().start);
  const [end, setEnd] = useState(last30().end);
  const [clientId, setClientId] = useState("");
  const [accountManagerId, setAccountManagerId] = useState("");
  const [q, setQ] = useState("");
  const [items, setItems] = useState([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [clientOptions, setClientOptions] = useState([]);
  const [userOptions, setUserOptions] = useState([]);

  const canFilterByManager = user?.role === "admin";

  const load = useCallback(async () => {
    setErr("");
    setBusy(true);
    try {
      const res = await libraries.wins({ start, end, clientId, accountManagerId, q, limit: 1500 });
      setItems(res?.items || []);
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || "Failed to load wins library");
      setItems([]);
    } finally {
      setBusy(false);
    }
  }, [start, end, clientId, accountManagerId, q]);

  useEffect(() => {
    clients.list().then(setClientOptions).catch(() => setClientOptions([]));
  }, []);

  useEffect(() => {
    if (!canFilterByManager) return;
    users.list().then((rows) => setUserOptions((rows || []).filter((u) => u.role === "manager"))).catch(() => setUserOptions([]));
  }, [canFilterByManager]);

  useEffect(() => { load(); }, [load]);

  const visible = useMemo(() => items || [], [items]);

  return (
    <div>
      <PageHead
        title="Wins Library"
        subtitle="Search and review wins across meetings. Defaults to the last 30 days."
        actions={
          <div className="flex items-center gap-2">
            <button className="btn-secondary" onClick={() => { const d = last30(); setStart(d.start); setEnd(d.end); }} type="button">Last 30 days</button>
            <button className="btn-primary" onClick={load} disabled={busy} type="button">{busy ? "Loading…" : "Apply"}</button>
          </div>
        }
      />

      <div className="card-flat p-5">
        <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
          <div>
            <div className="label">Start</div>
            <input className="input mt-1.5" type="date" value={start} onChange={(e) => setStart(e.target.value)} />
          </div>
          <div>
            <div className="label">End</div>
            <input className="input mt-1.5" type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
          </div>
          <div>
            <div className="label">Client</div>
            <select className="input mt-1.5" value={clientId} onChange={(e) => setClientId(e.target.value)}>
              <option value="">All clients</option>
              {(clientOptions || []).map((c) => <option key={c.id} value={c.id}>{c.company || c.name}</option>)}
            </select>
          </div>
          <div>
            <div className="label">Account Manager</div>
            <select className="input mt-1.5" value={accountManagerId} onChange={(e) => setAccountManagerId(e.target.value)} disabled={!canFilterByManager}>
              <option value="">{canFilterByManager ? "All" : "Me"}</option>
              {canFilterByManager && (userOptions || []).map((u) => <option key={u.id} value={u.id}>{u.name || u.email}</option>)}
            </select>
          </div>
          <div>
            <div className="label">Search</div>
            <input className="input mt-1.5" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Title, description, metric…" />
          </div>
        </div>
        {err && <div className="mt-4 text-sm text-rose-200">{err}</div>}
      </div>

      <div className="mt-5 card-flat overflow-hidden">
        {visible.length === 0 && <div className="p-10 text-center text-slate-400">No wins found for this range.</div>}
        {visible.map((row, idx) => (
          <div key={`${row.meeting_id}-${idx}`} className={`p-4 ${idx !== visible.length - 1 ? "border-b border-white/5" : ""}`}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-sm font-semibold truncate">{row.win?.title || "Win"}</div>
                <div className="text-xs text-slate-400 mt-1">{row.client_name} · {row.account_manager_name || "—"} · {row.brief_generated_at ? String(row.brief_generated_at).slice(0, 10) : "—"}</div>
                {row.win?.description && <div className="text-sm text-slate-200 mt-2">{row.win.description}</div>}
                {row.win?.metric && <div className="text-xs text-slate-400 mt-2 mono">{row.win.metric}</div>}
              </div>
              <Link to={`/meetings/${row.meeting_id}`} className="btn-ghost !py-1.5 !px-3 text-xs shrink-0">Open Meeting</Link>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
