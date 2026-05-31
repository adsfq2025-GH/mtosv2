import React, { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { clients, meetings, actionItems } from "../api";
import { PageHead } from "../Layout";
import { Plus, X, ArrowRight, MapPin, Briefcase, EnvelopeSimple, Phone, Trash } from "@phosphor-icons/react";

const healthChip = (h) => h >= 80 ? "chip-success" : h >= 60 ? "chip-info" : h >= 40 ? "chip-warn" : "chip-danger";

export function ClientsList() {
  const [list, setList] = useState([]); const [showNew, setShowNew] = useState(false);
  const [form, setForm] = useState({ name: "", company: "", industry: "", email: "", phone: "", location: "", services: "" });
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
        <button className="btn-primary flex items-center gap-2" onClick={() => setShowNew(true)} data-testid="new-client-btn"><Plus size={14} weight="bold" /> New Client</button>
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
    </div>
  );
}

export function ClientDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [client, setClient] = useState(null);
  const [meets, setMeets] = useState([]);
  const [actions, setActions] = useState([]);
  const [showMeet, setShowMeet] = useState(false);
  const [meetForm, setMeetForm] = useState({ title: "", scheduled_at: "", google_meet_url: "", duration_minutes: 60 });

  const reload = useCallback(
    () => Promise.all([clients.get(id), meetings.list(id), actionItems.list({ client_id: id })]).then(([c, m, a]) => { setClient(c); setMeets(m); setActions(a); }),
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

  if (!client) return <div className="text-slate-400">Loading…</div>;
  return (
    <div>
      <PageHead
        breadcrumbs={[{ label: "Clients", to: "/clients" }, { label: client.company }]}
        title={`${client.company}`}
        subtitle={`${client.name}${client.industry ? ` · ${client.industry}` : ""}${client.location ? ` · ${client.location}` : ""}`}
        actions={
          <>
            <button className="btn-ghost flex items-center gap-1" onClick={remove} data-testid="delete-client-btn"><Trash size={14} /> Delete</button>
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
    </div>
  );
}
