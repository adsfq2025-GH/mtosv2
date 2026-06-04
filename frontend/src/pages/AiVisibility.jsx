import React from "react";
import { PageHead } from "@/Layout";
import { clients as clientsApi, aiVisibility as aiVisibilityApi } from "@/api";
import { useAuth } from "@/auth";
import { CheckCircle, Lightning, Plus, WarningCircle } from "@phosphor-icons/react";

function fmtDate(v) {
  if (!v) return "";
  try {
    const d = typeof v === "string" ? new Date(v) : v;
    return d.toLocaleString();
  } catch {
    return String(v);
  }
}

export default function AiVisibility() {
  const { user } = useAuth();
  const [ent, setEnt] = React.useState(null);
  const [list, setList] = React.useState([]);
  const [clientId, setClientId] = React.useState("");
  const [configs, setConfigs] = React.useState([]);
  const [configId, setConfigId] = React.useState("");
  const [market, setMarket] = React.useState("");
  const [brandOverride, setBrandOverride] = React.useState("");
  const [domainOverride, setDomainOverride] = React.useState("");
  const [keywords, setKeywords] = React.useState(["", "", "", "", ""]);
  const [inferredBrand, setInferredBrand] = React.useState("");
  const [inferredDomain, setInferredDomain] = React.useState("");
  const [runs, setRuns] = React.useState([]);
  const [busy, setBusy] = React.useState(false);
  const [runBusy, setRunBusy] = React.useState(false);
  const [lastRun, setLastRun] = React.useState(null);
  const [err, setErr] = React.useState("");

  const loadEnt = React.useCallback(async () => {
    try {
      const r = await aiVisibilityApi.entitlement();
      setEnt(r);
    } catch {
      setEnt({ ok: false, enabled: user?.role === "admin", reason: "unknown" });
    }
  }, [user?.role]);

  const loadClients = React.useCallback(async () => {
    const r = await clientsApi.list();
    setList(r || []);
  }, []);

  const loadConfigs = React.useCallback(async (cid) => {
    if (!cid) return;
    const r = await aiVisibilityApi.listConfigs(cid);
    const cfgs = r?.configs || [];
    setConfigs(cfgs);
    const first = cfgs[0]?.id || "";
    setConfigId(first);
  }, []);

  const loadRuns = React.useCallback(async (cfgId) => {
    if (!cfgId) { setRuns([]); return; }
    const r = await aiVisibilityApi.listRuns(cfgId, 150);
    setRuns(r?.runs || []);
  }, []);

  React.useEffect(() => {
    loadEnt();
    loadClients();
  }, [loadClients, loadEnt]);

  React.useEffect(() => {
    if (!clientId) return;
    setConfigs([]);
    setConfigId("");
    setRuns([]);
    setLastRun(null);
    setErr("");
    loadConfigs(clientId).catch((e) => setErr(e?.response?.data?.detail || "Failed to load configs"));
  }, [clientId, loadConfigs]);

  React.useEffect(() => {
    const cfg = configs.find((c) => c.id === configId);
    if (!cfg) {
      setMarket("");
      setBrandOverride("");
      setDomainOverride("");
      setKeywords(["", "", "", "", ""]);
      setInferredBrand("");
      setInferredDomain("");
      return;
    }
    setMarket(cfg.market || "");
    setBrandOverride(cfg.brand_override || "");
    setDomainOverride(cfg.domain_override || "");
    setKeywords((cfg.keyword_slots || cfg.keywords || []).length ? (cfg.keyword_slots || cfg.keywords) : ["", "", "", "", ""]);
    setInferredBrand(cfg.inferred_brand || "");
    setInferredDomain(cfg.inferred_domain || "");
    loadRuns(cfg.id).catch(() => {});
  }, [configId, configs, loadRuns]);

  const enabled = !!ent?.enabled || user?.role === "admin";

  const upsert = async () => {
    if (!clientId) return;
    setBusy(true);
    setErr("");
    try {
      const payload = {
        market: market || "",
        keywords: (keywords || []).map((k) => String(k || "").trim()).filter(Boolean),
        brand_override: brandOverride || null,
        domain_override: domainOverride || null,
        enabled: true,
      };
      if (configId) {
        const r = await aiVisibilityApi.updateConfig(configId, payload);
        setConfigId(r?.config?.id || configId);
      } else {
        const r = await aiVisibilityApi.createConfig(clientId, payload);
        setConfigId(r?.config?.id || "");
      }
      await loadConfigs(clientId);
    } catch (e) {
      setErr(e?.response?.data?.detail || "Save failed");
    } finally {
      setBusy(false);
    }
  };

  const runScan = async () => {
    if (!configId) return;
    setRunBusy(true);
    setErr("");
    try {
      const r = await aiVisibilityApi.run(configId);
      setLastRun(r);
      await loadRuns(configId);
    } catch (e) {
      setErr(e?.response?.data?.detail || "Scan failed");
    } finally {
      setRunBusy(false);
    }
  };

  const addKeyword = () => setKeywords((ks) => [...(ks || []), ""]);
  const setKeyword = (idx, val) => setKeywords((ks) => (ks || []).map((k, i) => (i === idx ? val : k)));

  return (
    <div>
      <PageHead
        title="AI Visibility"
        subtitle="Track whether your clients appear in ChatGPT / Gemini / Perplexity-style answers for a set of keywords."
        actions={
          <div className="flex items-center gap-2">
            <button className="btn-primary text-xs" onClick={upsert} disabled={!enabled || busy || !clientId} data-testid="ai-vis-save">
              <CheckCircle size={14} /> {busy ? "Saving…" : "Save"}
            </button>
            <button className="btn-ghost text-xs" onClick={runScan} disabled={!enabled || runBusy || !configId} data-testid="ai-vis-run">
              <Lightning size={14} /> {runBusy ? "Scanning…" : "Run scan"}
            </button>
          </div>
        }
      />

      {!enabled && (
        <div className="card-flat p-5 flex items-start gap-3 text-slate-300" data-testid="ai-vis-locked">
          <WarningCircle size={18} className="text-amber-300 mt-0.5" />
          <div>
            <div className="font-semibold">AI Visibility is not enabled for this tenant.</div>
            <div className="text-sm text-slate-400 mt-1">Ask an admin to enable it, or access it from your super admin account.</div>
          </div>
        </div>
      )}

      {err && <div className="card-flat p-4 text-sm text-red-200 border border-red-500/20 bg-red-500/5 mb-4" data-testid="ai-vis-error">{err}</div>}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="card-flat p-5">
          <div className="text-xs text-slate-400 mb-2">Client</div>
          <select className="input w-full" value={clientId} onChange={(e) => setClientId(e.target.value)} data-testid="ai-vis-client">
            <option value="">Select client…</option>
            {list.map((c) => (
              <option key={c.id} value={c.id}>{c.company ? `${c.company} — ${c.name}` : c.name}</option>
            ))}
          </select>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-4">
            <div>
              <div className="text-xs text-slate-400 mb-2">Market (optional)</div>
              <input className="input w-full" value={market} onChange={(e) => setMarket(e.target.value)} placeholder="San Diego, CA" data-testid="ai-vis-market" />
            </div>
            <div>
              <div className="text-xs text-slate-400 mb-2">Config</div>
              <select className="input w-full" value={configId} onChange={(e) => setConfigId(e.target.value)} disabled={!configs.length} data-testid="ai-vis-config">
                {!configs.length && <option value="">No config yet</option>}
                {configs.map((c) => (
                  <option key={c.id} value={c.id}>{c.market ? c.market : "Default"}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-4">
            <div>
              <div className="text-xs text-slate-400 mb-2">Brand match override (optional)</div>
              <input className="input w-full" value={brandOverride} onChange={(e) => setBrandOverride(e.target.value)} placeholder={inferredBrand || "Inferred from client"} data-testid="ai-vis-brand" />
              {!!inferredBrand && <div className="text-[11px] text-slate-500 mt-1">Inferred: {inferredBrand}</div>}
            </div>
            <div>
              <div className="text-xs text-slate-400 mb-2">Domain match override (optional)</div>
              <input className="input w-full" value={domainOverride} onChange={(e) => setDomainOverride(e.target.value)} placeholder={inferredDomain || "Inferred from website"} data-testid="ai-vis-domain" />
              {!!inferredDomain && <div className="text-[11px] text-slate-500 mt-1">Inferred: {inferredDomain}</div>}
            </div>
          </div>

          <div className="flex items-center justify-between mt-6 mb-2">
            <div className="text-xs text-slate-400">Keywords</div>
            <button type="button" className="btn-ghost text-xs" onClick={addKeyword} data-testid="ai-vis-add-keyword">
              <Plus size={14} /> Add keyword
            </button>
          </div>
          <div className="flex flex-col gap-2">
            {(keywords || []).map((k, i) => (
              <input
                key={i}
                className="input w-full"
                value={k}
                onChange={(e) => setKeyword(i, e.target.value)}
                placeholder={i < 5 ? `Keyword ${i + 1}` : `Keyword ${i + 1} (extra)`}
                data-testid={`ai-vis-keyword-${i}`}
              />
            ))}
          </div>

          {!configs.length && (
            <div className="text-[11px] text-slate-500 mt-3">
              Create your first config by selecting a client, adding at least 1 keyword, and clicking Save.
            </div>
          )}
        </div>

        <div className="card-flat p-5">
          <div className="flex items-center justify-between mb-3">
            <div>
              <div className="text-sm font-semibold">Latest scan</div>
              <div className="text-xs text-slate-500">Runs 3 providers per keyword.</div>
            </div>
            {lastRun && (
              <div className="text-xs text-slate-400">
                Hits: <span className="text-slate-200">{lastRun.hits}</span> · Created: <span className="text-slate-200">{lastRun.created}</span>
              </div>
            )}
          </div>

          {lastRun && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4" data-testid="ai-vis-last-run">
              {Object.entries(lastRun.providers || {}).map(([k, v]) => (
                <div key={k} className="p-4 rounded-lg border border-white/5 bg-white/[0.02]">
                  <div className="text-xs text-slate-400">{k}</div>
                  <div className="mt-1 text-sm">
                    <span className="text-slate-200">{v.hits}</span>
                    <span className="text-slate-500"> / {v.total} hits</span>
                  </div>
                  {!!v.errors && <div className="text-[11px] text-amber-300 mt-1">{v.errors} errors</div>}
                </div>
              ))}
            </div>
          )}

          <div className="flex items-center justify-between">
            <div className="text-sm font-semibold">Recent results</div>
            <button className="btn-ghost text-xs" onClick={() => loadRuns(configId)} disabled={!configId} data-testid="ai-vis-refresh-runs">
              <Plus size={14} /> Refresh
            </button>
          </div>

          {runs.length === 0 && (
            <div className="p-10 text-center text-slate-400" data-testid="ai-vis-empty-runs">No scans yet.</div>
          )}

          {runs.length > 0 && (
            <div className="mt-3 overflow-hidden rounded-lg border border-white/5">
              {runs.slice(0, 80).map((r, i) => (
                <div key={r.id || i} className={`p-3 flex items-center justify-between gap-3 ${i !== Math.min(runs.length, 80) - 1 ? "border-b border-white/5" : ""}`}>
                  <div className="min-w-0">
                    <div className="text-[13px] truncate">{r.keyword}</div>
                    <div className="text-[11px] text-slate-500 mono">{r.provider} · {fmtDate(r.created_at)}</div>
                  </div>
                  <div className="shrink-0 flex items-center gap-2">
                    {r.hit ? <span className="chip chip-success">hit</span> : <span className="chip chip-muted">miss</span>}
                    {!!r.hit_domain && <span className="chip chip-info">domain</span>}
                    {!!r.hit_brand && <span className="chip chip-warn">brand</span>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

