import React from "react";
import { prompts } from "@/api";
import { PageHead } from "@/Layout";
import { canManageAdminSurfaces, roleLabel } from "@/rbac";
import { useAuth } from "@/auth";

export default function PromptCenter() {
  const { user } = useAuth();
  const [items, setItems] = React.useState([]);
  const [drafts, setDrafts] = React.useState({});
  const [busyKey, setBusyKey] = React.useState("");
  const [err, setErr] = React.useState("");

  const canManage = canManageAdminSurfaces(user);

  const load = React.useCallback(async () => {
    setErr("");
    try {
      const res = await prompts.list();
      const nextItems = Array.isArray(res?.items) ? res.items : [];
      setItems(nextItems);
      setDrafts(Object.fromEntries(nextItems.map((item) => [item.key, String(item.text || "")])));
    } catch (e) {
      setItems([]);
      setErr(e?.response?.data?.detail || e?.message || "Failed to load prompt templates");
    }
  }, []);

  React.useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <PageHead
        title="Prompt Center"
        subtitle="Admin-managed AI prompt templates for Monthly Touch briefs, audits, recaps, QA, coaching, and retention workflows."
        actions={<button className="btn-secondary" onClick={load} type="button">Refresh</button>}
      />

      {!canManage && (
        <div className="card-flat p-5 text-sm text-slate-300">
          Your role is {roleLabel(user?.role)}. Prompt management is limited to department admins and super admins.
        </div>
      )}

      {err && <div className="card-flat p-4 mb-4 text-sm text-rose-300">{err}</div>}

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        {items.map((item) => (
          <div key={item.key} className="card-flat p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="font-semibold">{item.label || item.key}</div>
                <div className="text-xs text-slate-400 mt-1">{item.description || "Prompt template"}</div>
              </div>
              <span className={`chip ${item.is_customized ? "chip-info" : "chip-muted"}`}>
                {item.is_customized ? "customized" : "default"}
              </span>
            </div>

            <div className="text-[11px] uppercase tracking-[0.16em] text-slate-500 mt-4">{item.category || "general"}</div>
            <label className="label mt-4">Prompt Text</label>
            <textarea
              className="input mt-1.5 min-h-[220px] !py-3"
              value={drafts[item.key] ?? ""}
              disabled={!canManage}
              onChange={(e) => setDrafts((prev) => ({ ...prev, [item.key]: e.target.value }))}
            />

            <div className="mt-4 flex items-center justify-between gap-3">
              <button
                type="button"
                className="btn-ghost text-xs"
                disabled={!canManage}
                onClick={() => setDrafts((prev) => ({ ...prev, [item.key]: String(item.default_text || "") }))}
              >
                Restore Default
              </button>
              <button
                type="button"
                className="btn-primary text-xs"
                disabled={!canManage || busyKey === item.key}
                onClick={async () => {
                  setBusyKey(item.key);
                  try {
                    await prompts.put(item.key, { text: drafts[item.key] || "" });
                    await load();
                  } catch (e) {
                    alert(e?.response?.data?.detail || e?.message || "Failed to save prompt");
                  } finally {
                    setBusyKey("");
                  }
                }}
              >
                {busyKey === item.key ? "Saving…" : "Save Prompt"}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
