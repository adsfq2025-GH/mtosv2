import React, { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { clients, meetings, actionItems, integrations } from "../api";
import { PageHead } from "../Layout";
import { Plus, X, ArrowRight, MapPin, Briefcase, EnvelopeSimple, Phone, Trash, Sparkle } from "@phosphor-icons/react";
import { useAuth } from "../auth";

const healthChip = (h) => h >= 80 ? "chip-success" : h >= 60 ? "chip-info" : h >= 40 ? "chip-warn" : "chip-danger";

export function ClientsList() {
  const [list, setList] = useState([]); const [showNew, setShowNew] = useState(false); const [showImport, setShowImport] = useState(false);
  const [form, setForm] = useState({ name: "", company: "", industry: "", email: "", phone: "", location: "", services: "" });
  const [ghlLocations, setGhlLocations] = useState([]);
  const [importLocationId, setImportLocationId] = useState("");
  const [importQuery, setImportQuery] = useState("");
  const [importContacts, setImportContacts] = useState([]);
  const [importSelected, setImportSelected] = useState({});
  const [importBusy, setImportBusy] = useState(false);
  const [importErr, setImportErr] = useState("");
  const navigate = useNavigate();
  const load = useCallback(() => clients.list().then(setList), []);
  useEffect(() => { load(); }, [load]);

  const create = async (e) => {
    e.preventDefault();
    const c = await clients.create({ ...form, services: form.services.split(",").map(s => s.trim()).filter(Boolean) });
    setShowNew(false); setForm({ name: "", company: "", industry: "", email: "", phone: "", location: "", services: "" });
    navigate(`/clients/${c.id}`);
  };

  return (
    <div>
      <PageHead title="Client Roster" subtitle="Health, churn signals, and recent activity at a glance." actions={
        <div className="flex items-center gap-2">
          <button className="btn-secondary flex items-center gap-2" onClick={() => setShowImport(true)}><ArrowRight size={14} weight="bold" /> Import Clients</button>
          <button className="btn-primary flex items-center gap-2" onClick={() => setShowNew(true)} data-testid="new-client-btn"><Plus size={14} weight="bold" /> New Client</button>
        </div>
      } />
      {list.length === 0 && (
        <div className="card-flat p-10 text-center" data-testid="empty-clients">
          <div className="text-slate-400 mb-3">No clients yet.</div>
          <button className="btn-primary" onClick={() => setShowNew(true)}>Add your first client</button>
        </div>
      )}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {list.map((c) => (
          <Link to={`/clients/${c.id}`} key={c.id} className="card-flat p-5 block animate-fade-up" data-testid={`client-card-${c.id}`}>
            <div className="flex items-start justify-between">
              <div>
                <div className="font-semibold text-base">{c.name}</div>
                <div className="text-slate-400 text-sm">{c.company}</div>
              </div>
              <span className={`chip ${healthChip(c.health_score)}`}><span className="mono">{c.health_score}</span></span>
            </div>
            <div className="text-xs text-slate-400 mt-3 flex flex-wrap gap-2">
              {c.industry && <span className="chip chip-muted"><Briefcase size={11} /> {c.industry}</span>}
              {c.location && <span className="chip chip-muted"><MapPin size={11} /> {c.location}</span>}
              <span className={`chip ${c.churn_risk === "high" ? "chip-danger" : c.churn_risk === "medium" ? "chip-warn" : "chip-success"}`}>{c.churn_risk} risk</span>
            </div>
            <div className="text-xs text-slate-400 mt-3">{(c.services || []).slice(0, 3).join(" · ") || "No services tagged"}</div>
          </Link>
        ))}
      </div>

      {showNew && (
        <div className="fixed inset-0 z-30 bg-black/60 flex items-center justify-center p-4" onClick={() => setShowNew(false)}>
          <form onClick={(e) => e.stopPropagation()} onSubmit={create} className="card-flat p-6 w-full max-w-lg" data-testid="new-client-form">
            <div className="flex items-center justify-between mb-4"><h3 className="text-lg font-semibold">New Client</h3><button type="button" className="btn-ghost !p-2" onClick={() => setShowNew(false)}><X size={14} /></button></div>
            <div className="grid grid-cols-2 gap-3">
              <div><label className="label">Contact Name</label><input className="input mt-1.5" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="new-client-name" /></div>
              <div><label className="label">Company</label><input className="input mt-1.5" required value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} data-testid="new-client-company" /></div>
              <div><label className="label">Industry</label><input className="input mt-1.5" value={form.industry} onChange={(e) => setForm({ ...form, industry: e.target.value })} /></div>
              <div><label className="label">Location</label><input className="input mt-1.5" value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} /></div>
              <div><label className="label">Email</label><input type="email" className="input mt-1.5" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
              <div><label className="label">Phone</label><input className="input mt-1.5" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></div>
              <div className="col-span-2"><label className="label">Services (comma-separated)</label><input className="input mt-1.5" placeholder="SEO, GBP, Google Ads" value={form.services} onChange={(e) => setForm({ ...form, services: e.target.value })} data-testid="new-client-services" /></div>
            </div>
            <button type="submit" className="btn-primary w-full mt-5" data-testid="new-client-submit">Create Client</button>
          </form>
        </div>
      )}

      {showImport && (
        <div className="fixed inset-0 z-30 bg-black/60 flex items-center justify-center p-4" onClick={() => { setShowImport(false); setImportErr(""); }}>
          <div onClick={(e) => e.stopPropagation()} className="card-flat p-6 w-full max-w-3xl">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold">Import Clients (GoHighLevel)</h3>
              <button type="button" className="btn-ghost !p-2" onClick={() => { setShowImport(false); setImportErr(""); }}><X size={14} /></button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div className="md:col-span-2">
                <label className="label">Map Ranking Location</label>
                <select
                  className="input mt-1.5"
                  value={importLocationId}
                  onChange={(e) => setImportLocationId(e.target.value)}
                  onFocus={async () => {
                    if (ghlLocations.length) return;
                    try {
                      const r = await integrations.gohighlevelLocations();
                      setGhlLocations(r?.locations || []);
                    } catch (e2) {
                      setImportErr(e2?.response?.data?.detail || e2?.message || "Failed to load GoHighLevel locations");
                    }
                  }}
                >
                  <option value="">Select a location…</option>
                  {ghlLocations.map((l) => <option key={l.id} value={l.id}>{l.name || l.id}</option>)}
                </select>
              </div>
              <div>
                <label className="label">Search</label>
                <input className="input mt-1.5" value={importQuery} onChange={(e) => setImportQuery(e.target.value)} placeholder="Name, company, email…" />
              </div>
            </div>

            <div className="flex items-center gap-2 mt-4">
              <button
                className="btn-secondary"
                disabled={!importLocationId || importBusy}
                onClick={async () => {
                  setImportErr("");
                  setImportBusy(true);
                  try {
                    const r = await clients.ghlImportContacts({ locationId: importLocationId, query: importQuery, limit: 200 });
                    setImportContacts(r?.contacts || []);
                    setImportSelected({});
                  } catch (e2) {
                    setImportErr(e2?.response?.data?.detail || e2?.message || "Failed to load contacts");
                  } finally {
                    setImportBusy(false);
                  }
                }}
              >
                {importBusy ? "Loading…" : "Load Contacts"}
              </button>
              <button
                className="btn-primary"
                disabled={!importContacts.length || importBusy}
                onClick={async () => {
                  setImportErr("");
                  setImportBusy(true);
                  try {
                    const chosen = importContacts.filter((c) => importSelected[c.id]);
                    const payload = { location_id: importLocationId, contacts: chosen.length ? chosen : importContacts };
                    const r = await clients.importFromGhl(payload);
                    await load();
                    setShowImport(false);
                    setImportContacts([]);
                    setImportSelected({});
                    setImportLocationId("");
                    setImportQuery("");
                    if ((r?.skipped || []).length) {
                      setTimeout(() => alert(`Imported ${r?.created?.length || 0} client(s). Skipped ${r?.skipped?.length || 0} duplicate(s).`), 50);
                    }
                  } catch (e2) {
                    setImportErr(e2?.response?.data?.detail || e2?.message || "Import failed");
                  } finally {
                    setImportBusy(false);
                  }
                }}
              >
                Import {Object.values(importSelected).some(Boolean) ? "Selected" : "All Loaded"}
              </button>
            </div>

            {importErr && (
              <div className="mt-4 card-flat p-3 border border-rose-500/20 bg-rose-500/10 text-rose-200 text-sm">
                {importErr}
              </div>
            )}

            <div className="mt-4 max-h-[48vh] overflow-auto border border-white/5 rounded-xl">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-[#0B1222]">
                  <tr className="text-left text-slate-400">
                    <th className="p-3 w-10"> </th>
                    <th className="p-3">Company</th>
                    <th className="p-3">Contact</th>
                    <th className="p-3">Email</th>
                    <th className="p-3">Phone</th>
                  </tr>
                </thead>
                <tbody>
                  {importContacts.map((c) => (
                    <tr key={c.id} className="border-t border-white/5">
                      <td className="p-3">
                        <input
                          type="checkbox"
                          checked={!!importSelected[c.id]}
                          onChange={(e) => setImportSelected({ ...importSelected, [c.id]: e.target.checked })}
                        />
                      </td>
                      <td className="p-3">{c.company || "—"}</td>
                      <td className="p-3">{c.name || "—"}</td>
                      <td className="p-3">{c.email || "—"}</td>
                      <td className="p-3">{c.phone || "—"}</td>
                    </tr>
                  ))}
                  {!importContacts.length && (
                    <tr><td className="p-6 text-slate-500" colSpan={5}>Load contacts to preview and select what to import.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export function ClientDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const [client, setClient] = useState(null);
  const [meets, setMeets] = useState([]);
  const [actions, setActions] = useState([]);
  const [clickupFolderId, setClickupFolderId] = useState("");
  const [gohighlevelLocationId, setGohighlevelLocationId] = useState("");
  const [googleAdsCustomerId, setGoogleAdsCustomerId] = useState("");
  const [savingBindings, setSavingBindings] = useState(false);
  const [savingGhlBinding, setSavingGhlBinding] = useState(false);
  const [savingGadsBinding, setSavingGadsBinding] = useState(false);
  const [showClickupPicker, setShowClickupPicker] = useState(false);
  const [clickupWorkspaces, setClickupWorkspaces] = useState([]);
  const [clickupTeamId, setClickupTeamId] = useState("");
  const [clickupFolders, setClickupFolders] = useState([]);
  const [clickupQ, setClickupQ] = useState("");
  const [loadingClickup, setLoadingClickup] = useState(false);
  const [showGhlPicker, setShowGhlPicker] = useState(false);
  const [ghlLocations, setGhlLocations] = useState([]);
  const [ghlQ, setGhlQ] = useState("");
  const [loadingGhl, setLoadingGhl] = useState(false);
  const [showGadsPicker, setShowGadsPicker] = useState(false);
  const [gadsCustomers, setGadsCustomers] = useState([]);
  const [gadsQ, setGadsQ] = useState("");
  const [loadingGads, setLoadingGads] = useState(false);
  const [showMeet, setShowMeet] = useState(false);
  const [meetForm, setMeetForm] = useState({ title: "", scheduled_at: "", google_meet_url: "", duration_minutes: 60 });

  const reload = useCallback(
    () => Promise.all([clients.get(id), meetings.list(id), actionItems.list({ client_id: id }), clients.listBindings(id)]).then(([c, m, a, b]) => {
      setClient(c); setMeets(m); setActions(a);
      const clickup = (b || []).find((x) => x.platform === "clickup");
      const folderId = clickup?.external_ids?.folder_id || clickup?.config?.folder_id || "";
      setClickupFolderId(folderId ? String(folderId) : "");
      const ghl = (b || []).find((x) => x.platform === "gohighlevel");
      const locId = ghl?.external_ids?.location_id || ghl?.config?.location_id || "";
      setGohighlevelLocationId(locId ? String(locId) : "");
      const gads = (b || []).find((x) => x.platform === "google_ads");
      const custId = gads?.external_ids?.customer_id || gads?.config?.customer_id || "";
      setGoogleAdsCustomerId(custId ? String(custId) : "");
    }),
    [id],
  );
  useEffect(() => { reload(); }, [reload]);

  const createMeeting = async (e) => {
    e.preventDefault();
    const m = await meetings.create({ ...meetForm, client_id: id });
    setShowMeet(false); setMeetForm({ title: "", scheduled_at: "", google_meet_url: "", duration_minutes: 60 });
    navigate(`/meetings/${m.id}`);
  };

  const remove = async () => {
    if (!window.confirm("Delete this client and all related meetings?")) return;
    await clients.remove(id); navigate("/clients");
  };

  const generateMonthlyTouch = async () => {
    const m = await clients.generateMonthlyTouch(id, {});
    navigate(`/meetings/${m.id}`);
  };

  const saveClickupBinding = async () => {
    setSavingBindings(true);
    try {
      await clients.upsertBinding(id, "clickup", { enabled: true, external_ids: { folder_id: clickupFolderId } });
      await reload();
    } catch (e) {
      alert(e?.response?.data?.detail || "Failed to save ClickUp binding");
    } finally {
      setSavingBindings(false);
    }
  };

  const saveGhlBinding = async () => {
    setSavingGhlBinding(true);
    try {
      await clients.upsertBinding(id, "gohighlevel", { enabled: true, external_ids: { location_id: gohighlevelLocationId } });
      await reload();
    } catch (e) {
      alert(e?.response?.data?.detail || "Failed to save GoHighLevel binding");
    } finally {
      setSavingGhlBinding(false);
    }
  };

  const saveGadsBinding = async () => {
    setSavingGadsBinding(true);
    try {
      await clients.upsertBinding(id, "google_ads", { enabled: true, external_ids: { customer_id: googleAdsCustomerId } });
      await reload();
    } catch (e) {
      alert(e?.response?.data?.detail || "Failed to save Google Ads binding");
    } finally {
      setSavingGadsBinding(false);
    }
  };

  const openClickupPicker = async () => {
    setShowClickupPicker(true);
    setClickupQ("");
    setLoadingClickup(true);
    try {
      const ws = await integrations.clickupWorkspaces();
      const list = ws?.workspaces || [];
      setClickupWorkspaces(list);
      const teamId = list?.[0]?.id ? String(list[0].id) : "";
      setClickupTeamId(teamId);
      if (teamId) {
        const res = await integrations.clickupFolders(teamId);
        setClickupFolders(res?.folders || []);
      } else {
        setClickupFolders([]);
      }
    } catch (e) {
      alert(e?.response?.data?.detail || "Failed to load ClickUp data");
      setClickupWorkspaces([]); setClickupFolders([]); setClickupTeamId("");
    } finally {
      setLoadingClickup(false);
    }
  };

  const changeClickupTeam = async (teamId) => {
    setClickupTeamId(teamId);
    setLoadingClickup(true);
    try {
      const res = await integrations.clickupFolders(teamId);
      setClickupFolders(res?.folders || []);
    } catch (e) {
      alert(e?.response?.data?.detail || "Failed to load ClickUp folders");
      setClickupFolders([]);
    } finally {
      setLoadingClickup(false);
    }
  };

  const openGhlPicker = async () => {
    setShowGhlPicker(true);
    setGhlQ("");
    setLoadingGhl(true);
    try {
      const res = await integrations.gohighlevelLocations();
      setGhlLocations(res?.locations || []);
    } catch (e) {
      alert(e?.response?.data?.detail || "Failed to load GoHighLevel locations");
      setGhlLocations([]);
    } finally {
      setLoadingGhl(false);
    }
  };

  const openGadsPicker = async () => {
    setShowGadsPicker(true);
    setGadsQ("");
    setLoadingGads(true);
    try {
      const res = await integrations.googleAdsCustomers();
      setGadsCustomers(res?.customers || []);
    } catch (e) {
      alert(e?.response?.data?.detail || "Failed to load Google Ads customers");
      setGadsCustomers([]);
    } finally {
      setLoadingGads(false);
    }
  };

  if (!client) return <div className="text-slate-400">Loading…</div>;
  return (
    <div>
      <PageHead
        breadcrumbs={[{ label: "Clients", to: "/clients" }, { label: client.company }]}
        title={`${client.company}`}
        subtitle={`${client.name}${client.industry ? ` · ${client.industry}` : ""}${client.location ? ` · ${client.location}` : ""}`}
        actions={
          <>
            {user?.role === "admin" && (
              <>
                <button
                  className="btn-ghost flex items-center gap-2"
                  onClick={async () => {
                    try {
                      const blob = await clients.exportCommunications(id, "html");
                      const url = window.URL.createObjectURL(blob);
                      const a = document.createElement("a");
                      a.href = url;
                      a.download = `client-communications-${client.company || id}.html`;
                      document.body.appendChild(a);
                      a.click();
                      a.remove();
                      window.URL.revokeObjectURL(url);
                    } catch (e) {
                      alert(e?.response?.data?.detail || e?.message || "Export failed");
                    }
                  }}
                >
                  Export HTML
                </button>
                <button
                  className="btn-ghost flex items-center gap-2"
                  onClick={async () => {
                    try {
                      const blob = await clients.exportCommunications(id, "pdf");
                      const url = window.URL.createObjectURL(blob);
                      const a = document.createElement("a");
                      a.href = url;
                      a.download = `client-communications-${client.company || id}.pdf`;
                      document.body.appendChild(a);
                      a.click();
                      a.remove();
                      window.URL.revokeObjectURL(url);
                    } catch (e) {
                      alert(e?.response?.data?.detail || e?.message || "Export failed");
                    }
                  }}
                >
                  Export PDF
                </button>
              </>
            )}
            <button className="btn-ghost flex items-center gap-1" onClick={remove} data-testid="delete-client-btn"><Trash size={14} /> Delete</button>
            <button className="btn-ghost flex items-center gap-2" onClick={generateMonthlyTouch} data-testid="generate-monthly-touch-btn"><Sparkle size={14} weight="duotone" /> Generate Monthly Touch</button>
            <button className="btn-primary flex items-center gap-2" onClick={() => setShowMeet(true)} data-testid="new-meeting-btn"><Plus size={14} weight="bold" /> New Meeting</button>
          </>
        }
      />
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="card-flat p-5 lg:col-span-1">
          <div className="flex items-center justify-between">
            <div className="label">Account Health</div>
            <span className={`chip ${healthChip(client.health_score)}`}><span className="mono">{client.health_score}</span> / 100</span>
          </div>
          <div className="divider my-4" />
          <div className="space-y-2 text-sm">
            <div className="flex items-center gap-2 text-slate-300"><Briefcase size={14} /> {client.company}</div>
            {client.email && <div className="flex items-center gap-2 text-slate-300"><EnvelopeSimple size={14} /> {client.email}</div>}
            {client.phone && <div className="flex items-center gap-2 text-slate-300"><Phone size={14} /> {client.phone}</div>}
            {client.location && <div className="flex items-center gap-2 text-slate-300"><MapPin size={14} /> {client.location}</div>}
          </div>
          <div className="divider my-4" />
          <div className="label mb-2">Services</div>
          <div className="flex flex-wrap gap-1.5">{(client.services || []).map((s) => <span key={s} className="chip chip-muted">{s}</span>) || "—"}</div>
          <div className="divider my-4" />
          <div className="label mb-2">Signal</div>
          <div className="flex gap-2 text-xs">
            <span className={`chip ${client.churn_risk === "high" ? "chip-danger" : client.churn_risk === "medium" ? "chip-warn" : "chip-success"}`}>{client.churn_risk} risk</span>
            <span className="chip chip-info">{client.sentiment}</span>
            <span className="chip chip-muted">{client.status}</span>
          </div>
          <div className="divider my-4" />
          <div className="label mb-2">ClickUp Mapping</div>
          <label className="text-[11px] text-slate-500">Folder ID</label>
          <div className="flex gap-2 mt-1.5">
            <input className="input flex-1" value={clickupFolderId} onChange={(e) => setClickupFolderId(e.target.value)} placeholder="123456789" data-testid="clickup-folder-id" />
            <button type="button" className="btn-ghost whitespace-nowrap" onClick={openClickupPicker} data-testid="browse-clickup-folders">Browse</button>
          </div>
          <button className="btn-ghost w-full mt-2" onClick={saveClickupBinding} disabled={savingBindings} data-testid="save-clickup-binding">{savingBindings ? "Saving…" : "Save ClickUp Folder"}</button>
          <div className="divider my-4" />
          <div className="label mb-2">GoHighLevel Mapping</div>
          <label className="text-[11px] text-slate-500">Location ID</label>
          <div className="flex gap-2 mt-1.5">
            <input className="input flex-1" value={gohighlevelLocationId} onChange={(e) => setGohighlevelLocationId(e.target.value)} placeholder="ve9EPM428h8vShlRW1KT" data-testid="gohighlevel-location-id" />
            <button type="button" className="btn-ghost whitespace-nowrap" onClick={openGhlPicker} data-testid="browse-ghl-locations">Browse</button>
          </div>
          <button className="btn-ghost w-full mt-2" onClick={saveGhlBinding} disabled={savingGhlBinding} data-testid="save-gohighlevel-binding">{savingGhlBinding ? "Saving…" : "Save GoHighLevel Location"}</button>
          <div className="divider my-4" />
          <div className="label mb-2">Google Ads Mapping</div>
          <label className="text-[11px] text-slate-500">Customer ID</label>
          <div className="flex gap-2 mt-1.5">
            <input className="input flex-1" value={googleAdsCustomerId} onChange={(e) => setGoogleAdsCustomerId(e.target.value)} placeholder="1234567890" data-testid="google-ads-customer-id" />
            <button type="button" className="btn-ghost whitespace-nowrap" onClick={openGadsPicker} data-testid="browse-google-ads-customers">Browse</button>
          </div>
          <button className="btn-ghost w-full mt-2" onClick={saveGadsBinding} disabled={savingGadsBinding} data-testid="save-google-ads-binding">{savingGadsBinding ? "Saving…" : "Save Google Ads Customer"}</button>
        </div>

        <div className="lg:col-span-2 space-y-6">
          <div className="card-flat p-5">
            <div className="flex items-center justify-between mb-3"><h3 className="font-semibold">Meetings</h3><span className="text-xs text-slate-400">{meets.length} total</span></div>
            {meets.length === 0 && <div className="text-slate-500 text-sm py-4">No meetings yet. Schedule a Monthly Touch.</div>}
            <div className="flex flex-col gap-2">
              {meets.map((m) => (
                <Link to={`/meetings/${m.id}`} key={m.id} className="flex items-center justify-between p-3 rounded-md border border-white/5 hover:bg-white/[0.03]" data-testid={`meeting-row-${m.id}`}>
                  <div>
                    <div className="font-medium text-sm">{m.title}</div>
                    <div className="text-xs text-slate-400 mt-0.5">{m.scheduled_at || "Unscheduled"} · {m.duration_minutes} min</div>
                  </div>
                  <div className="flex items-center gap-2"><span className="chip chip-info">{m.status}</span><ArrowRight size={14} className="text-slate-500" /></div>
                </Link>
              ))}
            </div>
          </div>
          <div className="card-flat p-5">
            <div className="flex items-center justify-between mb-3"><h3 className="font-semibold">Action Items</h3><span className="text-xs text-slate-400">{actions.length} total</span></div>
            {actions.length === 0 && <div className="text-slate-500 text-sm py-4">No action items yet. Run a transcript analysis after the meeting.</div>}
            <div className="flex flex-col gap-2">
              {actions.slice(0, 8).map((a) => (
                <div key={a.id} className="flex items-center justify-between p-3 rounded-md border border-white/5">
                  <div>
                    <div className="text-sm font-medium">{a.title}</div>
                    <div className="text-xs text-slate-400 mt-0.5">{a.owner_type} · due {a.due_date || "TBD"}</div>
                  </div>
                  <span className={`chip ${a.status === "completed" ? "chip-success" : a.status === "blocked" ? "chip-danger" : "chip-info"}`}>{a.status}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {showMeet && (
        <div className="fixed inset-0 z-30 bg-black/60 flex items-center justify-center p-4" onClick={() => setShowMeet(false)}>
          <form onClick={(e) => e.stopPropagation()} onSubmit={createMeeting} className="card-flat p-6 w-full max-w-lg" data-testid="new-meeting-form">
            <div className="flex items-center justify-between mb-4"><h3 className="text-lg font-semibold">Schedule Monthly Touch Meeting</h3><button type="button" className="btn-ghost !p-2" onClick={() => setShowMeet(false)}><X size={14} /></button></div>
            <label className="label">Meeting Title</label>
            <input className="input mt-1.5 mb-3" required placeholder="Monthly Touch — January" value={meetForm.title} onChange={(e) => setMeetForm({ ...meetForm, title: e.target.value })} data-testid="new-meeting-title" />
            <label className="label">Scheduled At (ISO)</label>
            <input className="input mt-1.5 mb-3" type="datetime-local" value={meetForm.scheduled_at} onChange={(e) => setMeetForm({ ...meetForm, scheduled_at: e.target.value })} data-testid="new-meeting-date" />
            <label className="label">Google Meet URL</label>
            <input className="input mt-1.5 mb-3" placeholder="https://meet.google.com/..." value={meetForm.google_meet_url} onChange={(e) => setMeetForm({ ...meetForm, google_meet_url: e.target.value })} data-testid="new-meeting-url" />
            <label className="label">Duration (minutes)</label>
            <input className="input mt-1.5 mb-4" type="number" value={meetForm.duration_minutes} onChange={(e) => setMeetForm({ ...meetForm, duration_minutes: parseInt(e.target.value) })} />
            <button type="submit" className="btn-primary w-full" data-testid="new-meeting-submit">Create Meeting</button>
          </form>
        </div>
      )}

      {showClickupPicker && (
        <div className="fixed inset-0 z-40 bg-black/60 flex items-center justify-center p-4" onClick={() => setShowClickupPicker(false)}>
          <div onClick={(e) => e.stopPropagation()} className="card-flat p-6 w-full max-w-2xl" data-testid="clickup-picker">
            <div className="flex items-center justify-between mb-4">
              <div>
                <div className="text-lg font-semibold">Pick ClickUp Folder</div>
                <div className="text-xs text-slate-400">Choose the Folder that represents this client.</div>
              </div>
              <button type="button" className="btn-ghost !p-2" onClick={() => setShowClickupPicker(false)}><X size={14} /></button>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div className="md:col-span-1">
                <label className="label">Workspace</label>
                <select className="input mt-1.5" value={clickupTeamId} onChange={(e) => changeClickupTeam(e.target.value)} disabled={loadingClickup}>
                  {(clickupWorkspaces || []).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                </select>
                <label className="label mt-3">Search</label>
                <input className="input mt-1.5" value={clickupQ} onChange={(e) => setClickupQ(e.target.value)} placeholder="Client name…" />
              </div>
              <div className="md:col-span-2">
                <div className="label">Folders</div>
                <div className="mt-2 max-h-[55vh] overflow-y-auto scroll-thin border border-white/5 rounded-md">
                  {loadingClickup && <div className="p-4 text-sm text-slate-400">Loading…</div>}
                  {!loadingClickup && (clickupFolders || []).filter((f) => !clickupQ || `${f.name} ${f.space || ""}`.toLowerCase().includes(clickupQ.toLowerCase())).map((f) => (
                    <button
                      key={f.id}
                      type="button"
                      className="w-full text-left p-3 border-b border-white/5 hover:bg-white/[0.03]"
                      onClick={() => { setClickupFolderId(String(f.id)); setShowClickupPicker(false); }}
                    >
                      <div className="text-sm font-medium">{f.name}</div>
                      <div className="text-xs text-slate-500 mt-0.5">{f.space || ""} · <span className="mono">{f.id}</span></div>
                    </button>
                  ))}
                  {!loadingClickup && (clickupFolders || []).length === 0 && <div className="p-4 text-sm text-slate-400">No folders found.</div>}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {showGadsPicker && (
        <div className="fixed inset-0 z-40 bg-black/60 flex items-center justify-center p-4" onClick={() => setShowGadsPicker(false)}>
          <div onClick={(e) => e.stopPropagation()} className="card-flat p-6 w-full max-w-xl" data-testid="gads-picker">
            <div className="flex items-center justify-between mb-4">
              <div>
                <div className="text-lg font-semibold">Pick Google Ads Customer</div>
                <div className="text-xs text-slate-400">Select the customer account for this client.</div>
              </div>
              <button type="button" className="btn-ghost !p-2" onClick={() => setShowGadsPicker(false)}><X size={14} /></button>
            </div>
            <label className="label">Search</label>
            <input className="input mt-1.5 mb-3" value={gadsQ} onChange={(e) => setGadsQ(e.target.value)} placeholder="1234567890" />
            <div className="max-h-[55vh] overflow-y-auto scroll-thin border border-white/5 rounded-md">
              {loadingGads && <div className="p-4 text-sm text-slate-400">Loading…</div>}
              {!loadingGads && (gadsCustomers || []).filter((c) => !gadsQ || String(c.id || "").includes(gadsQ)).map((c) => (
                <button
                  key={c.id}
                  type="button"
                  className="w-full text-left p-3 border-b border-white/5 hover:bg-white/[0.03]"
                  onClick={() => { setGoogleAdsCustomerId(String(c.id)); setShowGadsPicker(false); }}
                >
                  <div className="text-sm font-medium">{c.id}</div>
                </button>
              ))}
              {!loadingGads && (gadsCustomers || []).length === 0 && <div className="p-4 text-sm text-slate-400">No customers found.</div>}
            </div>
          </div>
        </div>
      )}

      {showGhlPicker && (
        <div className="fixed inset-0 z-40 bg-black/60 flex items-center justify-center p-4" onClick={() => setShowGhlPicker(false)}>
          <div onClick={(e) => e.stopPropagation()} className="card-flat p-6 w-full max-w-2xl" data-testid="ghl-picker">
            <div className="flex items-center justify-between mb-4">
              <div>
                <div className="text-lg font-semibold">Pick GoHighLevel Location</div>
                <div className="text-xs text-slate-400">Choose the GHL client location for this account.</div>
              </div>
              <button type="button" className="btn-ghost !p-2" onClick={() => setShowGhlPicker(false)}><X size={14} /></button>
            </div>
            <label className="label">Search</label>
            <input className="input mt-1.5" value={ghlQ} onChange={(e) => setGhlQ(e.target.value)} placeholder="Client name…" />
            <div className="mt-3 max-h-[60vh] overflow-y-auto scroll-thin border border-white/5 rounded-md">
              {loadingGhl && <div className="p-4 text-sm text-slate-400">Loading…</div>}
              {!loadingGhl && (ghlLocations || []).filter((l) => !ghlQ || `${l.name} ${l.email || ""} ${l.phone || ""}`.toLowerCase().includes(ghlQ.toLowerCase())).map((l) => (
                <button
                  key={l.id}
                  type="button"
                  className="w-full text-left p-3 border-b border-white/5 hover:bg-white/[0.03]"
                  onClick={() => { setGohighlevelLocationId(String(l.id)); setShowGhlPicker(false); }}
                >
                  <div className="text-sm font-medium">{l.name}</div>
                  <div className="text-xs text-slate-500 mt-0.5">{[l.email, l.phone].filter(Boolean).join(" · ")} · <span className="mono">{l.id}</span></div>
                </button>
              ))}
              {!loadingGhl && (ghlLocations || []).length === 0 && <div className="p-4 text-sm text-slate-400">No locations found.</div>}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
