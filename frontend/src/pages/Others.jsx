import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { meetings as meetingsApi, actionItems, contentCaptures, integrations, docs, prompts, aiTerritory } from "../api";
import { PageHead } from "../Layout";
import { useAuth } from "../auth";
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
  const { user } = useAuth();
  const [list, setList] = useState([]);
  const [edit, setEdit] = useState(null);
  const [form, setForm] = useState({});
  const [busy, setBusy] = useState(false);
  const [oauthBusy, setOauthBusy] = useState(false);
  const [promptBusy, setPromptBusy] = useState(false);
  const [mtPrompt, setMtPrompt] = useState("");
  const [tiSettings, setTiSettings] = useState(null);
  const [tiForm, setTiForm] = useState({ scanFrequencyHours: 24, maxPrompts: 60 });
  const [tiBusy, setTiBusy] = useState(false);
  const [ghlLocs, setGhlLocs] = useState([]);
  const [ghlTokenLocId, setGhlTokenLocId] = useState("");
  const [ghlTokenValue, setGhlTokenValue] = useState("");
  const [ghlTokenSavedIds, setGhlTokenSavedIds] = useState([]);
  const load = () => integrations.status().then(setList);
  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (user?.role !== "admin") return;
    aiTerritory.getSettings().then((r) => {
      setTiSettings(r);
      setTiForm({ scanFrequencyHours: Number(r?.scan_frequency_hours || r?.scanFrequencyHours || 24) || 24, maxPrompts: Number(r?.max_prompts || r?.maxPrompts || 60) || 60 });
    }).catch(() => {});
  }, [user?.role]);
  useEffect(() => {
    if (user?.role !== "admin") return;
    prompts.get("monthly_touch_analysis").then((r) => setMtPrompt(String(r?.text || ""))).catch(() => {});
  }, [user?.role]);
  useEffect(() => {
    const onMsg = (ev) => {
      if (ev?.data?.type === "google_oauth_success") {
        setEdit(null);
        load();
      }
    };
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, []);

  const GOOGLE_OAUTH = new Set([
    "google_calendar",
    "google_meet",
    "google_drive",
    "gmail",
    "google_search_console",
    "google_analytics",
    "google_business_profile",
    "google_lsa",
    "google_ads",
  ]);

  const openConfig = (i) => {
    setEdit(i);
    const next = {};
    (i.fields || []).forEach((f) => {
      if (!f.secret) next[f.key] = (i.metadata || {})[f.key] || "";
    });
    setForm(next);
    if (i.platform === "gohighlevel") {
      integrations.gohighlevelLocations().then((r) => setGhlLocs(r?.locations || [])).catch(() => {});
      if (user?.role === "admin") integrations.gohighlevelLocationTokens().then((r) => setGhlTokenSavedIds(r?.location_ids || [])).catch(() => {});
      setGhlTokenLocId("");
      setGhlTokenValue("");
    }
  };
  const save = async (e) => {
    e.preventDefault(); setBusy(true);
    try {
      if (GOOGLE_OAUTH.has(edit.platform) && (edit.fields || []).length === 0) {
        throw new Error("Use Connect Google for this integration.");
      }
      const credentials = {}; const metadata = {};
      edit.fields.forEach((f) => { if (form[f.key]) { if (f.secret) credentials[f.key] = form[f.key]; else metadata[f.key] = form[f.key]; } });
      await integrations.configure(edit.platform, { credentials, metadata });
      await integrations.test(edit.platform);
      setEdit(null); load();
    } catch (err) { alert(err?.response?.data?.detail || "Failed"); }
    finally { setBusy(false); }
  };

  const connectGoogle = async (platform) => {
    setOauthBusy(true);
    try {
      const res = await integrations.oauthGoogleStart(platform);
      const url = res?.url;
      if (!url) throw new Error("Missing OAuth URL");
      const popup = window.open(url, "google_oauth", "width=520,height=720");
      const startedAt = Date.now();
      const poll = async () => {
        try {
          const st = await integrations.oauthGoogleStatus(platform);
          if (st?.connected) {
            setEdit(null);
            load();
            try { popup?.close(); } catch { }
            return true;
          }
        } catch { }
        return false;
      };
      const timer = window.setInterval(async () => {
        if (Date.now() - startedAt > 90_000) {
          window.clearInterval(timer);
          setOauthBusy(false);
          alert("Google connection timed out. If you see “Connected” in the popup, close it and try again.");
          return;
        }
        const done = await poll();
        if (done) {
          window.clearInterval(timer);
          setOauthBusy(false);
        }
      }, 1200);
    } catch (err) {
      alert(err?.response?.data?.detail || err?.message || "Failed to start Google OAuth");
      setOauthBusy(false);
    }
  };

  const disconnectGoogle = async (platform) => {
    if (!window.confirm("Disconnect your Google account for this integration?")) return;
    setOauthBusy(true);
    try {
      await integrations.oauthGoogleDisconnect(platform);
      await load();
      setEdit(null);
    } catch (err) {
      alert(err?.response?.data?.detail || "Failed");
    } finally {
      setOauthBusy(false);
    }
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
              {i.status === "connected" && (
                GOOGLE_OAUTH.has(i.platform)
                  ? <button className="btn-danger text-xs" onClick={() => disconnectGoogle(i.platform)}>Disconnect</button>
                  : <button className="btn-danger text-xs" onClick={() => disconnect(i.platform)}>Disconnect</button>
              )}
            </div>
            {i.last_synced_at && <div className="text-[10px] mono text-slate-500 mt-2">Last sync · {new Date(i.last_synced_at).toLocaleString()}</div>}
          </div>
        ))}
      </div>

      {user?.role === "admin" && (
        <div className="card-flat p-5 mt-5">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="font-semibold">AI &amp; Territory Intelligence</div>
              <div className="text-xs text-slate-400 mt-0.5">Daily client intelligence scans that generate visibility and territory expansion insights.</div>
            </div>
            <button
              className="btn-primary text-xs"
              disabled={tiBusy}
              onClick={async () => {
                setTiBusy(true);
                try {
                  await aiTerritory.putSettings({ scanFrequencyHours: tiForm.scanFrequencyHours, maxPrompts: tiForm.maxPrompts });
                  const r = await aiTerritory.getSettings();
                  setTiSettings(r);
                  alert("Saved.");
                } catch (e) {
                  alert(e?.response?.data?.detail || e?.message || "Failed to save settings");
                } finally {
                  setTiBusy(false);
                }
              }}
            >
              {tiBusy ? "Saving…" : "Save"}
            </button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-4">
            <div>
              <label className="label">Scan frequency (hours)</label>
              <input className="input mt-1.5" type="number" min={1} max={168} value={tiForm.scanFrequencyHours} onChange={(e) => setTiForm((p) => ({ ...p, scanFrequencyHours: Number(e.target.value || 24) }))} />
              <div className="text-xs text-slate-500 mt-1">Default is 24. Lower values increase cost and runtime.</div>
            </div>
            <div>
              <label className="label">Max prompts per scan</label>
              <input className="input mt-1.5" type="number" min={10} max={200} value={tiForm.maxPrompts} onChange={(e) => setTiForm((p) => ({ ...p, maxPrompts: Number(e.target.value || 60) }))} />
              <div className="text-xs text-slate-500 mt-1">Controls scan size across services and territories.</div>
            </div>
          </div>
          {!!tiSettings && (
            <div className="text-[10px] mono text-slate-500 mt-3">
              Active: every {tiSettings.scan_frequency_hours || 24}h · max {tiSettings.max_prompts || 60} prompts
            </div>
          )}
        </div>
      )}

      {user?.role === "admin" && (
        <div className="card-flat p-5 mt-5">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="font-semibold">Prompt Manager</div>
              <div className="text-xs text-slate-400 mt-0.5">Central prompt templates used by transcript analysis and meeting intelligence.</div>
            </div>
            <button
              className="btn-primary text-xs"
              disabled={promptBusy}
              onClick={async () => {
                setPromptBusy(true);
                try {
                  await prompts.put("monthly_touch_analysis", { text: mtPrompt || "" });
                  alert("Prompt saved.");
                } catch (e) {
                  alert(e?.response?.data?.detail || e?.message || "Failed to save prompt");
                } finally {
                  setPromptBusy(false);
                }
              }}
            >
              {promptBusy ? "Saving…" : "Save"}
            </button>
          </div>
          <div className="mt-4">
            <label className="label">Monthly Touch Analysis Prompt</label>
            <textarea
              className="input mt-1.5 min-h-[220px] !py-3"
              value={mtPrompt}
              onChange={(e) => setMtPrompt(e.target.value)}
              placeholder="Enter analysis prompt..."
            />
          </div>
        </div>
      )}

      {edit && (
        <div className="fixed inset-0 z-30 bg-black/60 flex items-center justify-center p-4" onClick={() => setEdit(null)}>
          <form onClick={(e) => e.stopPropagation()} onSubmit={save} className="card-flat p-6 w-full max-w-lg" data-testid="integration-config-form">
            <div className="flex items-center justify-between mb-1"><h3 className="text-lg font-semibold">Configure {edit.label}</h3><button type="button" className="btn-ghost !p-2" onClick={() => setEdit(null)}><X size={14} /></button></div>
            <p className="text-xs text-slate-400 mb-4">{edit.description}</p>
            {GOOGLE_OAUTH.has(edit.platform) && (
              <div className="card-flat p-4 bg-white/[0.02] border border-white/5">
                <div className="label mb-1">Connect Google</div>
                <div className="text-xs text-slate-400">Each account manager connects their own Google account. Tokens are stored securely and used for calendar + Meet/Drive artifacts on their behalf.</div>
                <div className="flex items-center gap-2 mt-3">
                  <button type="button" className="btn-primary flex-1" onClick={() => connectGoogle(edit.platform)} disabled={oauthBusy} data-testid="google-connect-btn">
                    {oauthBusy ? "Connecting…" : "Connect Google"}
                  </button>
                  {edit.status === "connected" && (
                    <button type="button" className="btn-danger" onClick={() => disconnectGoogle(edit.platform)} disabled={oauthBusy} data-testid="google-disconnect-btn">
                      Disconnect
                    </button>
                  )}
                </div>
              </div>
            )}

            {edit.platform === "gohighlevel" && user?.role === "admin" && (
              <div className="card-flat p-4 bg-white/[0.02] border border-white/5 mt-4">
                <div className="label mb-1">Location Tokens (Admin)</div>
                <div className="text-xs text-slate-400">Paste a sub-account (location) Private Integration Token for locations that restrict contacts/conversations access. Account managers can import/export without seeing the token.</div>
                <div className="grid grid-cols-1 gap-3 mt-3">
                  <div>
                    <label className="label">Location</label>
                    <select className="input mt-1.5" value={ghlTokenLocId} onChange={(e) => setGhlTokenLocId(e.target.value)}>
                      <option value="">Select a location…</option>
                      {ghlLocs.map((l) => <option key={l.id} value={l.id}>{l.name || l.id}{(ghlTokenSavedIds || []).includes(l.id) ? " (saved)" : ""}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="label">Private Integration Token</label>
                    <input type="password" className="input mt-1.5" value={ghlTokenValue} onChange={(e) => setGhlTokenValue(e.target.value)} placeholder="Paste token (stored encrypted)" />
                    <div className="text-[11px] text-slate-500 mt-1.5">Saved tokens are not shown. Paste a new value to rotate.</div>
                  </div>
                  <div className="flex items-center gap-2">
                    <button type="button" className="btn-primary flex-1" disabled={!ghlTokenLocId || !ghlTokenValue || busy} onClick={async () => {
                      try {
                        await integrations.gohighlevelUpsertLocationToken(ghlTokenLocId, ghlTokenValue);
                        setGhlTokenValue("");
                        const r = await integrations.gohighlevelLocationTokens();
                        setGhlTokenSavedIds(r?.location_ids || []);
                        alert("Location token saved.");
                      } catch (e) {
                        alert(e?.response?.data?.detail || e?.message || "Failed to save location token");
                      }
                    }}>Save Location Token</button>
                    <button type="button" className="btn-danger" disabled={!ghlTokenLocId || busy} onClick={async () => {
                      if (!window.confirm("Delete the saved token for this location?")) return;
                      try {
                        await integrations.gohighlevelDeleteLocationToken(ghlTokenLocId);
                        const r = await integrations.gohighlevelLocationTokens();
                        setGhlTokenSavedIds(r?.location_ids || []);
                        alert("Location token deleted.");
                      } catch (e) {
                        alert(e?.response?.data?.detail || e?.message || "Failed to delete location token");
                      }
                    }}>Delete</button>
                  </div>
                </div>
              </div>
            )}

            {(edit.fields || []).length > 0 && (
              <>
                <div className="space-y-3 mt-4">
                  {edit.fields.map((f) => (
                    <div key={f.key}>
                      <label className="label">{f.label}{f.secret && <span className="ml-2 text-[10px] text-[#2FE0C2]">encrypted</span>}</label>
                      <input
                        className="input mt-1.5"
                        type={f.secret ? "password" : "text"}
                        value={form[f.key] || ""}
                        onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                        placeholder={
                          f.secret && (edit.configured_field_keys || []).includes(f.key)
                            ? `Saved (leave blank to keep)${f.help ? ` · ${f.help}` : ""}`
                            : (f.help || "")
                        }
                        data-testid={`field-${edit.platform}-${f.key}`}
                      />
                      {f.help && <div className="text-[11px] text-slate-500 mt-1">{f.help}</div>}
                    </div>
                  ))}
                </div>
                <button type="submit" className="btn-primary w-full mt-5" disabled={busy} data-testid="integration-save-btn">{busy ? "Saving…" : "Save & Verify"}</button>
              </>
            )}
          </form>
        </div>
      )}
    </div>
  );
}

export function DocsHub() {
  const [data, setData] = useState({ items: [], categories: [], wiki_type: "tenant" });
  const [active, setActive] = useState(null);
  const [doc, setDoc] = useState(null);
  const [q, setQ] = useState("");
  useEffect(() => { docs.list().then((d) => { setData(d); if (d.items[0]) { setActive(d.items[0].slug); } }); }, []);
  useEffect(() => { if (active) docs.get(active).then(setDoc); }, [active]);

  const filtered = data.items.filter((d) => !q || d.title.toLowerCase().includes(q.toLowerCase()) || d.summary.toLowerCase().includes(q.toLowerCase()));

  return (
    <div>
      <PageHead
        title="Dashboard Wiki"
        subtitle={data.wiki_type === "internal"
          ? "Internal Map Ranking wiki — SOPs, playbooks, tutorials, and admin procedures (role-gated)."
          : "Tenant wiki — SOPs, playbooks, tutorials, and FAQs aligned to your branding and terminology."}
      />
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-5">
        <aside className="card-flat p-4 lg:max-h-[78vh] overflow-y-auto scroll-thin">
          <div className="relative mb-3">
            <MagnifyingGlass size={14} className="absolute left-2.5 top-2.5 text-slate-500" />
            <input className="input !pl-8 !py-2 text-sm" placeholder="Search wiki…" value={q} onChange={(e) => setQ(e.target.value)} data-testid="docs-search" />
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
