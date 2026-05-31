import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { meetings as meetingsApi, actionItems, contentCaptures, integrations, docs } from "../api";
import { PageHead } from "../Layout";
import {
  ArrowRight, CheckCircle, Clock, Megaphone, Plugs, BookOpen, Plus, MagnifyingGlass, Check, X, Sparkle,
} from "@phosphor-icons/react";

export function MeetingsList() {
  const [list, setList] = useState([]);
  useEffect(() => { meetingsApi.list().then(setList); }, []);
  return (
    <div>
      <PageHead title="Meetings" subtitle="Every Monthly Touch — prep, transcripts, recaps and outcomes." />
      {list.length === 0 && <div className="card-flat p-10 text-center text-slate-400" data-testid="empty-meetings">No meetings yet. Open a client to schedule one.</div>}
      <div className="card-flat overflow-hidden">
        {list.map((m, i) => (
          <Link key={m.id} to={`/meetings/${m.id}`} className={`flex items-center justify-between p-4 hover:bg-white/[0.03] ${i !== list.length - 1 ? "border-b border-white/5" : ""}`} data-testid={`meetings-row-${m.id}`}>
            <div>
              <div className="font-medium text-sm">{m.title}</div>
              <div className="text-xs text-slate-400 mt-0.5">{m.client_name} · {m.scheduled_at || "Unscheduled"} · {m.duration_minutes} min</div>
            </div>
            <div className="flex items-center gap-3">
              {m.brief_generated_at && <span className="chip chip-info"><Sparkle size={11} /> brief</span>}
              {m.transcript_analyzed_at && <span className="chip chip-success">analyzed</span>}
              <span className="chip chip-muted">{m.status}</span>
              <ArrowRight size={14} className="text-slate-500" />
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}

export function Actions() {
  const [items, setItems] = useState([]);
  const [filter, setFilter] = useState("all");
  const load = () => actionItems.list().then(setItems);
  useEffect(() => { load(); }, []);
  const filtered = items.filter((a) => filter === "all" || a.status === filter);
  const setStatus = async (id, status) => { await actionItems.update(id, { status }); load(); };

  return (
    <div>
      <PageHead title="Action Items" subtitle="Every commitment from every meeting — owners, due dates, accountability."
        actions={
          <div className="flex gap-1">
            {["all", "open", "in_progress", "completed", "blocked"].map((f) => (
              <button key={f} onClick={() => setFilter(f)} className={`px-3 py-1.5 rounded-md text-xs ${filter === f ? "bg-[#3FA9F5]/15 text-[#3FA9F5] border border-[#3FA9F5]/30" : "text-slate-400 hover:text-white"}`} data-testid={`filter-${f}`}>{f}</button>
            ))}
          </div>
        }
      />
      {filtered.length === 0 && <div className="card-flat p-10 text-center text-slate-400">No action items.</div>}
      <div className="card-flat overflow-hidden">
        {filtered.map((a, i) => (
          <div key={a.id} className={`p-4 flex items-center justify-between gap-3 ${i !== filtered.length - 1 ? "border-b border-white/5" : ""}`} data-testid={`action-row-${a.id}`}>
            <div className="min-w-0">
              <div className="flex items-center gap-2"><span className="text-sm font-medium truncate">{a.title}</span><span className={`chip ${a.priority === "high" ? "chip-danger" : a.priority === "low" ? "chip-success" : "chip-warn"}`}>{a.priority}</span></div>
              <div className="text-xs text-slate-400 mt-1 truncate">{a.description}</div>
              <div className="text-[11px] text-slate-500 mt-1 mono">{a.owner_type} · due {a.due_date || "TBD"} · meeting #{(a.meeting_id || "—").slice(0, 8)}</div>
            </div>
            <div className="flex items-center gap-1">
              <button className="btn-ghost !p-2" title="Mark in progress" onClick={() => setStatus(a.id, "in_progress")} data-testid={`progress-${a.id}`}><Clock size={14} /></button>
              <button className="btn-ghost !p-2" title="Complete" onClick={() => setStatus(a.id, "completed")} data-testid={`complete-${a.id}`}><Check size={14} /></button>
              <button className="btn-ghost !p-2" title="Block" onClick={() => setStatus(a.id, "blocked")} data-testid={`block-${a.id}`}><X size={14} /></button>
              <span className={`chip ${a.status === "completed" ? "chip-success" : a.status === "blocked" ? "chip-danger" : a.status === "in_progress" ? "chip-info" : "chip-warn"}`}>{a.status}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function ContentQueue() {
  const [items, setItems] = useState([]);
  const load = () => contentCaptures.list().then(setItems);
  useEffect(() => { load(); }, []);
  const route = async (id, val) => { await contentCaptures.update(id, { routed_to_marketing: val }); load(); };

  return (
    <div>
      <PageHead title="Content & Testimonial Queue" subtitle="Every marketing-worthy client moment, ready to route to your marketing team." />
      {items.length === 0 && <div className="card-flat p-10 text-center text-slate-400">No content captured yet. Run a transcript analysis after your next MTM.</div>}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {items.map((c) => (
          <div key={c.id} className="card-flat p-5" data-testid={`content-card-${c.id}`}>
            <div className="flex items-center justify-between mb-2">
              <span className="chip chip-success"><Megaphone size={11} /> {c.type}</span>
              {c.routed_to_marketing
                ? <span className="chip chip-info">routed</span>
                : <button className="btn-primary text-xs !py-1 !px-2" onClick={() => route(c.id, true)} data-testid={`route-${c.id}`}>Route to marketing</button>}
            </div>
            <div className="text-sm text-slate-200 italic">"{c.content}"</div>
            {c.notes && <div className="text-xs text-slate-400 mt-2">{c.notes}</div>}
            <div className="text-[11px] mono text-slate-500 mt-2">Client {(c.client_id || "").slice(0, 8)} · Meeting {(c.meeting_id || "—").slice(0, 8)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function Integrations() {
  const [list, setList] = useState([]);
  const [edit, setEdit] = useState(null);
  const [form, setForm] = useState({});
  const [busy, setBusy] = useState(false);
  const load = () => integrations.status().then(setList);
  useEffect(() => { load(); }, []);

  const openConfig = (i) => { setEdit(i); setForm({}); };
  const save = async (e) => {
    e.preventDefault(); setBusy(true);
    try {
      const credentials = {}; const metadata = {};
      edit.fields.forEach((f) => { if (form[f.key]) { if (f.secret) credentials[f.key] = form[f.key]; else metadata[f.key] = form[f.key]; } });
      await integrations.configure(edit.platform, { credentials, metadata });
      await integrations.test(edit.platform);
      setEdit(null); load();
    } catch (err) { alert(err?.response?.data?.detail || "Failed"); }
    finally { setBusy(false); }
  };

  const disconnect = async (platform) => {
    if (!window.confirm("Disconnect this integration?")) return;
    await integrations.disconnect(platform); load();
  };

  const STATUS_CHIP = (s) => s === "connected" ? "chip-success" : s === "error" ? "chip-danger" : "chip-muted";

  return (
    <div>
      <PageHead title="Integrations" subtitle="13 platforms ready to plug in. Connect to power the meeting brief and KPI snapshots." />
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {list.map((i) => (
          <div key={i.platform} className="card-flat p-5" data-testid={`integration-${i.platform}`}>
            <div className="flex items-center justify-between">
              <div>
                <div className="font-semibold">{i.label}</div>
                <div className="text-xs text-slate-500 mt-0.5">{i.category}</div>
              </div>
              <span className={`chip ${STATUS_CHIP(i.status)}`}>{i.status === "connected" ? <CheckCircle size={11} weight="fill" /> : <Plugs size={11} />} {i.status}</span>
            </div>
            <p className="text-xs text-slate-400 mt-3 min-h-[40px]">{i.description}</p>
            <div className="flex items-center gap-2 mt-3">
              <button className="btn-ghost text-xs !py-1.5 !px-2.5 flex-1" onClick={() => openConfig(i)} data-testid={`configure-${i.platform}`}>{i.status === "connected" ? "Reconfigure" : "Configure"}</button>
              {i.status === "connected" && <button className="btn-danger text-xs" onClick={() => disconnect(i.platform)}>Disconnect</button>}
            </div>
            {i.last_synced_at && <div className="text-[10px] mono text-slate-500 mt-2">Last sync · {new Date(i.last_synced_at).toLocaleString()}</div>}
          </div>
        ))}
      </div>

      {edit && (
        <div className="fixed inset-0 z-30 bg-black/60 flex items-center justify-center p-4" onClick={() => setEdit(null)}>
          <form onClick={(e) => e.stopPropagation()} onSubmit={save} className="card-flat p-6 w-full max-w-lg" data-testid="integration-config-form">
            <div className="flex items-center justify-between mb-1"><h3 className="text-lg font-semibold">Configure {edit.label}</h3><button type="button" className="btn-ghost !p-2" onClick={() => setEdit(null)}><X size={14} /></button></div>
            <p className="text-xs text-slate-400 mb-4">{edit.description}</p>
            <div className="space-y-3">
              {edit.fields.map((f) => (
                <div key={f.key}>
                  <label className="label">{f.label}{f.secret && <span className="ml-2 text-[10px] text-[#2FE0C2]">encrypted</span>}</label>
                  <input className="input mt-1.5" type={f.secret ? "password" : "text"} value={form[f.key] || ""} onChange={(e) => setForm({ ...form, [f.key]: e.target.value })} placeholder={f.help || ""} data-testid={`field-${edit.platform}-${f.key}`} />
                  {f.help && <div className="text-[11px] text-slate-500 mt-1">{f.help}</div>}
                </div>
              ))}
            </div>
            <button type="submit" className="btn-primary w-full mt-5" disabled={busy} data-testid="integration-save-btn">{busy ? "Saving…" : "Save & Verify"}</button>
          </form>
        </div>
      )}
    </div>
  );
}

export function DocsHub() {
  const [data, setData] = useState({ items: [], categories: [] });
  const [active, setActive] = useState(null);
  const [doc, setDoc] = useState(null);
  const [q, setQ] = useState("");
  useEffect(() => { docs.list().then((d) => { setData(d); if (d.items[0]) { setActive(d.items[0].slug); } }); }, []);
  useEffect(() => { if (active) docs.get(active).then(setDoc); }, [active]);

  const filtered = data.items.filter((d) => !q || d.title.toLowerCase().includes(q.toLowerCase()) || d.summary.toLowerCase().includes(q.toLowerCase()));

  return (
    <div>
      <PageHead title="Documentation Hub" subtitle="The full Monthly Touch Meeting operating system — frameworks, SOPs, playbooks, scorecards, automation maps." />
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-5">
        <aside className="card-flat p-4 lg:max-h-[78vh] overflow-y-auto scroll-thin">
          <div className="relative mb-3">
            <MagnifyingGlass size={14} className="absolute left-2.5 top-2.5 text-slate-500" />
            <input className="input !pl-8 !py-2 text-sm" placeholder="Search docs…" value={q} onChange={(e) => setQ(e.target.value)} data-testid="docs-search" />
          </div>
          {data.categories.map((cat) => (
            <div key={cat.category} className="mb-3">
              <div className="label mb-1">{cat.category}</div>
              {filtered.filter((d) => d.category === cat.category).map((d) => (
                <button key={d.slug} onClick={() => setActive(d.slug)} className={`block w-full text-left px-2 py-1.5 rounded text-[13px] ${active === d.slug ? "bg-[#3FA9F5]/15 text-white" : "text-slate-300 hover:bg-white/[0.04]"}`} data-testid={`doc-${d.slug}`}>{d.title}</button>
              ))}
            </div>
          ))}
        </aside>
        <article className="lg:col-span-3 card-flat p-7">
          {!doc && <div className="text-slate-400">Loading…</div>}
          {doc && (
            <div>
              <div className="chip chip-info mb-3">{doc.category}</div>
              <h2 className="text-2xl font-bold mb-1">{doc.title}</h2>
              <p className="text-slate-400 text-sm">{doc.summary}</p>
              <div className="divider my-5" />
              <div className="prose-doc" dangerouslySetInnerHTML={{ __html: mdToHtml(doc.body) }} />
            </div>
          )}
        </article>
      </div>
    </div>
  );
}

// Minimal markdown → HTML (headers, bold, italic, lists, tables, code, blockquotes)
function mdToHtml(md) {
  if (!md) return "";
  const escape = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  let lines = md.split("\n");
  let out = []; let inList = null; let inTable = false; let tableRows = [];
  const flushList = () => { if (inList) { out.push(`</${inList}>`); inList = null; } };
  const flushTable = () => {
    if (inTable) {
      out.push("<table><thead><tr>" + tableRows[0].map((c) => `<th>${c}</th>`).join("") + "</tr></thead><tbody>" +
        tableRows.slice(2).map((r) => "<tr>" + r.map((c) => `<td>${c}</td>`).join("") + "</tr>").join("") +
        "</tbody></table>");
      inTable = false; tableRows = [];
    }
  };
  for (let raw of lines) {
    let l = raw;
    const tableMatch = l.match(/^\|(.+)\|$/);
    if (tableMatch) { flushList(); inTable = true; tableRows.push(tableMatch[1].split("|").map((c) => c.trim())); continue; }
    if (inTable) flushTable();
    if (/^#\s/.test(l)) { flushList(); out.push(`<h1>${inline(escape(l.replace(/^#\s/, "")))}</h1>`); continue; }
    if (/^##\s/.test(l)) { flushList(); out.push(`<h2>${inline(escape(l.replace(/^##\s/, "")))}</h2>`); continue; }
    if (/^###\s/.test(l)) { flushList(); out.push(`<h3>${inline(escape(l.replace(/^###\s/, "")))}</h3>`); continue; }
    if (/^\>\s/.test(l)) { flushList(); out.push(`<blockquote>${inline(escape(l.replace(/^\>\s/, "")))}</blockquote>`); continue; }
    if (/^\s*[-*]\s/.test(l)) {
      if (inList !== "ul") { flushList(); out.push("<ul>"); inList = "ul"; }
      out.push(`<li>${inline(escape(l.replace(/^\s*[-*]\s/, "")))}</li>`); continue;
    }
    if (/^\s*\d+\.\s/.test(l)) {
      if (inList !== "ol") { flushList(); out.push("<ol>"); inList = "ol"; }
      out.push(`<li>${inline(escape(l.replace(/^\s*\d+\.\s/, "")))}</li>`); continue;
    }
    if (l.trim() === "") { flushList(); out.push(""); continue; }
    flushList();
    out.push(`<p>${inline(escape(l))}</p>`);
  }
  flushList(); flushTable();
  return out.join("\n");
  function inline(s) {
    return s
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\*(.+?)\*/g, "<em>$1</em>")
      .replace(/`(.+?)`/g, "<code>$1</code>");
  }
}
