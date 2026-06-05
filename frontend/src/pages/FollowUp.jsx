import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { actionItems, clients } from "../api";
import { PageHead } from "../Layout";
import { Bell, Check, Clock, PencilSimple, Plus, Warning } from "@phosphor-icons/react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "../components/ui/dialog";

const statusChip = (s) => s === "completed" ? "chip-success" : s === "blocked" ? "chip-danger" : s === "in_progress" ? "chip-info" : "chip-warn";
const prioChip = (p) => p === "high" ? "chip-danger" : p === "low" ? "chip-success" : "chip-warn";

function EditActionDialog({ item, onSave }) {
  const [form, setForm] = useState({});
  useEffect(() => { setForm(item || {}); }, [item]);
  if (!item) return null;
  return (
    <Dialog>
      <DialogTrigger asChild>
        <button className="btn-ghost !p-2" title="Edit" type="button">
          <PencilSimple size={14} />
        </button>
      </DialogTrigger>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Edit Action Item</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <div className="label mb-1">Title</div>
            <input className="input" value={form.title || ""} onChange={(e) => setForm((p) => ({ ...p, title: e.target.value }))} />
          </div>
          <div>
            <div className="label mb-1">Description</div>
            <textarea className="input !min-h-[90px]" value={form.description || ""} onChange={(e) => setForm((p) => ({ ...p, description: e.target.value }))} />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <div className="label mb-1">Owner Type</div>
              <select className="input" value={form.owner_type || "agency"} onChange={(e) => setForm((p) => ({ ...p, owner_type: e.target.value }))}>
                <option value="agency">agency</option>
                <option value="client">client</option>
              </select>
            </div>
            <div>
              <div className="label mb-1">Owner</div>
              <input className="input" value={form.owner || ""} onChange={(e) => setForm((p) => ({ ...p, owner: e.target.value }))} placeholder="Name or role" />
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div>
              <div className="label mb-1">Due Date</div>
              <input className="input" type="date" value={form.due_date || ""} onChange={(e) => setForm((p) => ({ ...p, due_date: e.target.value }))} />
            </div>
            <div>
              <div className="label mb-1">Priority</div>
              <select className="input" value={form.priority || "medium"} onChange={(e) => setForm((p) => ({ ...p, priority: e.target.value }))}>
                <option value="high">high</option>
                <option value="medium">medium</option>
                <option value="low">low</option>
              </select>
            </div>
            <div>
              <div className="label mb-1">Status</div>
              <select className="input" value={form.status || "open"} onChange={(e) => setForm((p) => ({ ...p, status: e.target.value }))}>
                <option value="open">open</option>
                <option value="in_progress">in_progress</option>
                <option value="blocked">blocked</option>
                <option value="completed">completed</option>
              </select>
            </div>
          </div>
          <div className="flex items-center justify-end gap-2">
            <button className="btn-primary" type="button" onClick={() => onSave(item.id, {
              title: form.title,
              description: form.description,
              owner_type: form.owner_type,
              owner: form.owner,
              due_date: form.due_date || null,
              priority: form.priority,
              status: form.status,
            })}>Save</button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function AddActionDialog({ ownerType, clientId, meetingId, clientsList, onCreate }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ owner_type: ownerType, client_id: clientId || "", meeting_id: meetingId || "" });
  useEffect(() => { setForm({ owner_type: ownerType, client_id: clientId || "", meeting_id: meetingId || "" }); }, [clientId, meetingId, ownerType]);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <button className="btn-ghost flex items-center gap-2" type="button">
          <Plus size={14} /> Add {ownerType === "client" ? "Client" : "Internal"} Task
        </button>
      </DialogTrigger>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Add Action Item</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          {!clientId && (
            <div>
              <div className="label mb-1">Client</div>
              <select className="input" value={form.client_id} onChange={(e) => setForm((p) => ({ ...p, client_id: e.target.value }))}>
                <option value="">Select client…</option>
                {(clientsList || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
          )}
          <div>
            <div className="label mb-1">Title</div>
            <input className="input" value={form.title || ""} onChange={(e) => setForm((p) => ({ ...p, title: e.target.value }))} placeholder={ownerType === "client" ? "Upload 10 new photos to GBP" : "Launch new city page cluster"} />
          </div>
          <div>
            <div className="label mb-1">Description</div>
            <textarea className="input !min-h-[90px]" value={form.description || ""} onChange={(e) => setForm((p) => ({ ...p, description: e.target.value }))} placeholder="Context, what done looks like, any assets/links needed…" />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <div className="label mb-1">Owner</div>
              <input className="input" value={form.owner || ""} onChange={(e) => setForm((p) => ({ ...p, owner: e.target.value }))} placeholder={ownerType === "client" ? "Client / Office Manager" : "SEO Dept / AM"} />
            </div>
            <div>
              <div className="label mb-1">Due Date</div>
              <input className="input" type="date" value={form.due_date || ""} onChange={(e) => setForm((p) => ({ ...p, due_date: e.target.value }))} />
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <div className="label mb-1">Priority</div>
              <select className="input" value={form.priority || "medium"} onChange={(e) => setForm((p) => ({ ...p, priority: e.target.value }))}>
                <option value="high">high</option>
                <option value="medium">medium</option>
                <option value="low">low</option>
              </select>
            </div>
            <div>
              <div className="label mb-1">Status</div>
              <select className="input" value={form.status || "open"} onChange={(e) => setForm((p) => ({ ...p, status: e.target.value }))}>
                <option value="open">open</option>
                <option value="in_progress">in_progress</option>
                <option value="blocked">blocked</option>
                <option value="completed">completed</option>
              </select>
            </div>
          </div>
          <div className="flex items-center justify-end gap-2">
            <button className="btn-primary" type="button" onClick={async () => {
              if (!form.client_id) return;
              await onCreate({
                client_id: form.client_id,
                meeting_id: form.meeting_id || null,
                title: form.title || "Action item",
                description: form.description || null,
                owner: form.owner || null,
                owner_type: ownerType,
                due_date: form.due_date || null,
                priority: form.priority || "medium",
              });
              setOpen(false);
            }}>Create</button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function ActionRow({ item, onStatus, onRemind, onSave }) {
  return (
    <div className="p-4 rounded-md border border-white/5 bg-white/[0.02] flex items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <div className="text-sm font-medium truncate">{item.title}</div>
          <span className={`chip ${prioChip(item.priority)}`}>{item.priority}</span>
          {item.is_overdue && <span className="chip chip-danger">overdue</span>}
          {item.reminder_due && <span className="chip chip-warn">reminder due</span>}
        </div>
        {item.description && <div className="text-xs text-slate-400 mt-1">{item.description}</div>}
        <div className="text-[11px] text-slate-500 mt-1 mono">
          {item.client_name || item.client_id?.slice(0, 8)} · {item.owner_type} · {item.owner || "—"} · due {item.due_date || "TBD"}
          {item.meeting_id && (
            <>
              {" "}· <Link className="text-[#3FA9F5] hover:underline" to={`/meetings/${item.meeting_id}`}>{item.meeting_title || "Meeting"}</Link>
            </>
          )}
        </div>
      </div>
      <div className="flex items-center gap-1 shrink-0">
        <button className="btn-ghost !p-2" title="Mark in progress" onClick={() => onStatus(item.id, "in_progress")} type="button"><Clock size={14} /></button>
        <button className="btn-ghost !p-2" title="Complete" onClick={() => onStatus(item.id, "completed")} type="button"><Check size={14} /></button>
        <button className="btn-ghost !p-2" title="Send reminder (logs in system)" onClick={() => onRemind(item.id)} type="button"><Bell size={14} /></button>
        <EditActionDialog item={item} onSave={onSave} />
        <span className={`chip ${statusChip(item.status)}`}>{item.status}</span>
      </div>
    </div>
  );
}

export default function FollowUp() {
  const [sp] = useSearchParams();
  const clientId = sp.get("client_id") || "";
  const meetingId = sp.get("meeting_id") || "";
  const [data, setData] = useState(null);
  const [clientList, setClientList] = useState([]);
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    const res = await actionItems.followUp({ ...(clientId ? { client_id: clientId } : {}), ...(meetingId ? { meeting_id: meetingId } : {}), upcoming_days: 14 });
    setData(res);
  }, [clientId, meetingId]);

  useEffect(() => { load().catch(() => {}); }, [load]);
  useEffect(() => { clients.list().then(setClientList).catch(() => {}); }, []);

  const onStatus = async (id, status) => {
    setBusy(id);
    try { await actionItems.update(id, { status }); await load(); } finally { setBusy(""); }
  };
  const onRemind = async (id) => {
    setBusy(id);
    try { await actionItems.remind(id); await load(); } finally { setBusy(""); }
  };
  const onSave = async (id, patch) => {
    setBusy(id);
    try { await actionItems.update(id, patch); await load(); } finally { setBusy(""); }
  };
  const onCreate = async (payload) => {
    setBusy("create");
    try { await actionItems.create(payload); await load(); } finally { setBusy(""); }
  };

  const counts = data?.counts || {};
  const sections = useMemo(() => ([
    { key: "client_pending", title: "Client Pending Tasks", items: data?.client_pending || [] },
    { key: "internal_pending", title: "Internal Pending Tasks", items: data?.internal_pending || [] },
    { key: "overdue", title: "Overdue Items", items: data?.overdue || [] },
    { key: "upcoming", title: "Upcoming Deadlines", items: data?.upcoming || [] },
  ]), [data]);

  return (
    <div>
      <PageHead
        title="Follow-Up Dashboard"
        subtitle="Accountability tracking across client + internal tasks, deadlines, and reminders."
        actions={
          <div className="flex items-center gap-2">
            <AddActionDialog ownerType="client" clientId={clientId} meetingId={meetingId} clientsList={clientList} onCreate={onCreate} />
            <AddActionDialog ownerType="agency" clientId={clientId} meetingId={meetingId} clientsList={clientList} onCreate={onCreate} />
            <button className="btn-ghost" onClick={() => load()} disabled={busy === "create"} type="button">Refresh</button>
          </div>
        }
      />

      {!data && <div className="card-flat p-10 text-center text-slate-400">Loading…</div>}

      {!!data && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-5 gap-3 mb-5">
            {[
              { k: "client_pending", label: "Client Pending", val: counts.client_pending, icon: Warning },
              { k: "internal_pending", label: "Internal Pending", val: counts.internal_pending, icon: Warning },
              { k: "overdue", label: "Overdue", val: counts.overdue, icon: Warning },
              { k: "upcoming", label: "Upcoming", val: counts.upcoming, icon: Clock },
              { k: "reminders_due", label: "Reminders Due", val: counts.reminders_due, icon: Bell },
            ].map((s) => (
              <div key={s.k} className="card-flat p-4">
                <div className="text-xs text-slate-400 flex items-center gap-2"><s.icon size={14} /> {s.label}</div>
                <div className="text-2xl font-bold mt-1">{s.val || 0}</div>
              </div>
            ))}
          </div>

          {(data.reminders_due || []).length > 0 && (
            <div className="card-flat p-5 mb-5 border border-[#F59E0B]/30 bg-[#F59E0B]/10">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="font-semibold flex items-center gap-2"><Bell size={16} /> Reminders Due</div>
                  <div className="text-xs text-slate-300 mt-1">These tasks are due soon/overdue and haven’t been reminded today.</div>
                </div>
              </div>
              <div className="mt-4 space-y-2">
                {(data.reminders_due || []).slice(0, 20).map((it) => (
                  <div key={it.id} className={busy === it.id ? "opacity-60 pointer-events-none" : ""}>
                    <ActionRow item={it} onStatus={onStatus} onRemind={onRemind} onSave={onSave} />
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            {sections.map((s) => (
              <section key={s.key} className="card-flat p-5">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="font-semibold">{s.title}</h3>
                  <span className="chip chip-muted">{(s.items || []).length}</span>
                </div>
                {(s.items || []).length === 0 && <div className="text-sm text-slate-500 py-6 text-center">Nothing here.</div>}
                <div className="space-y-2">
                  {(s.items || []).slice(0, 40).map((it) => (
                    <div key={it.id} className={busy === it.id ? "opacity-60 pointer-events-none" : ""}>
                      <ActionRow item={it} onStatus={onStatus} onRemind={onRemind} onSave={onSave} />
                    </div>
                  ))}
                </div>
              </section>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

