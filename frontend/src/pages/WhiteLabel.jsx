import React, { useEffect, useMemo, useState } from "react";
import { PageHead } from "../Layout";
import { settings as settingsApi, whiteLabel } from "../api";
import { ArrowsClockwise, UploadSimple, Sparkle } from "@phosphor-icons/react";

export default function WhiteLabel() {
  const [cfg, setCfg] = useState(null);
  const [uploads, setUploads] = useState([]);
  const [busy, setBusy] = useState("");
  const [file, setFile] = useState(null);

  const load = async () => {
    const [s, u] = await Promise.all([
      settingsApi.get().catch(() => null),
      whiteLabel.uploads().catch(() => []),
    ]);
    setCfg(s);
    setUploads(u);
  };

  useEffect(() => { load(); }, []);

  const draft = useMemo(() => ({
    branding: cfg?.branding || {},
    terminology: cfg?.terminology || {},
    workflows: cfg?.workflows || {},
    analysis: cfg?.analysis || {},
  }), [cfg]);

  const setDraft = (next) => setCfg({ ...(cfg || {}), ...next });

  const save = async () => {
    setBusy("save");
    try {
      const updated = await settingsApi.put(draft);
      setCfg(updated);
    } catch (e) {
      alert(e?.response?.data?.detail || "Save failed");
    } finally {
      setBusy("");
    }
  };

  const doUpload = async () => {
    if (!file) return;
    setBusy("upload");
    try {
      await whiteLabel.upload(file, "documentation");
      setFile(null);
      await load();
    } catch (e) {
      alert(e?.response?.data?.detail || "Upload failed");
    } finally {
      setBusy("");
    }
  };

  const analyze = async () => {
    setBusy("analyze");
    try {
      const res = await whiteLabel.analyze();
      setCfg(res.settings);
    } catch (e) {
      alert(e?.response?.data?.detail || "Analyze failed");
    } finally {
      setBusy("");
    }
  };

  return (
    <div>
      <PageHead
        title="White Label Configuration Center"
        subtitle="Upload SOPs, process guides, and training docs. The system adapts terminology and meeting workflows to your agency."
        actions={
          <>
            <button className="btn-ghost flex items-center gap-2" onClick={analyze} disabled={busy === "analyze"} data-testid="wl-analyze-btn">
              {busy === "analyze" ? <ArrowsClockwise size={14} className="animate-spin" /> : <Sparkle size={14} weight="duotone" />} Analyze uploads
            </button>
            <button className="btn-primary flex items-center gap-2" onClick={save} disabled={busy === "save"} data-testid="wl-save-btn">
              {busy === "save" ? <ArrowsClockwise size={14} className="animate-spin" /> : "Save settings"}
            </button>
          </>
        }
      />

      {!cfg && <div className="text-slate-400">Loading…</div>}
      {cfg && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="card-flat p-6">
            <div className="label mb-2">Branding</div>
            <div className="space-y-3">
              <Field label="Product name" value={draft.branding.product_name || ""} onChange={(v) => setDraft({ branding: { ...draft.branding, product_name: v } })} />
              <Field label="Primary color" value={draft.branding.primary_color || ""} onChange={(v) => setDraft({ branding: { ...draft.branding, primary_color: v } })} placeholder="#3FA9F5" />
              <Field label="Secondary color" value={draft.branding.secondary_color || ""} onChange={(v) => setDraft({ branding: { ...draft.branding, secondary_color: v } })} placeholder="#2FE0C2" />
            </div>
            <div className="divider my-5" />
            <div className="label mb-2">Terminology</div>
            <div className="space-y-3">
              <Field label="Client (singular)" value={draft.terminology.client_singular || ""} onChange={(v) => setDraft({ terminology: { ...draft.terminology, client_singular: v } })} placeholder="Client" />
              <Field label="Client (plural)" value={draft.terminology.client_plural || ""} onChange={(v) => setDraft({ terminology: { ...draft.terminology, client_plural: v } })} placeholder="Clients" />
              <Field label="Monthly Touch name" value={draft.terminology.monthly_touch || ""} onChange={(v) => setDraft({ terminology: { ...draft.terminology, monthly_touch: v } })} placeholder="Monthly Touch" />
              <Field label="Account manager title" value={draft.terminology.account_manager || ""} onChange={(v) => setDraft({ terminology: { ...draft.terminology, account_manager: v } })} placeholder="Account Manager" />
            </div>
          </div>

          <div className="space-y-6">
            <div className="card-flat p-6">
              <div className="label mb-2">Upload SOPs & Docs</div>
              <div className="flex items-center gap-2">
                <input className="input" type="file" onChange={(e) => setFile(e.target.files?.[0] || null)} data-testid="wl-file-input" />
                <button className="btn-primary flex items-center gap-2" onClick={doUpload} disabled={!file || busy === "upload"} data-testid="wl-upload-btn">
                  {busy === "upload" ? <ArrowsClockwise size={14} className="animate-spin" /> : <UploadSimple size={14} weight="duotone" />} Upload
                </button>
              </div>
              <div className="text-[11px] text-slate-500 mt-2">Supported extraction: txt/md/json/csv, docx, pdf, zip (text files inside).</div>
            </div>

            <div className="card-flat p-6">
              <div className="flex items-center justify-between mb-3">
                <div className="label">Uploaded documents</div>
                <button className="btn-ghost text-xs" onClick={load} disabled={busy} data-testid="wl-refresh-btn">Refresh</button>
              </div>
              {uploads.length === 0 && <div className="text-slate-500 text-sm py-6 text-center">No uploads yet.</div>}
              {uploads.length > 0 && (
                <div className="space-y-2">
                  {uploads.map((u) => (
                    <div key={u.id} className="p-3 rounded-md border border-white/5">
                      <div className="text-sm font-medium">{u.filename || u.id}</div>
                      <div className="text-[11px] text-slate-500 mono mt-1">{u.mime_type || "—"} · {u.size_bytes || 0} bytes · extracted {u.extracted_chars || 0} chars</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, value, onChange, placeholder }) {
  return (
    <div>
      <label className="label">{label}</label>
      <input className="input mt-1.5" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder || ""} />
    </div>
  );
}

