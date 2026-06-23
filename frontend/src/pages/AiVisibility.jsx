import React from "react";
import { PageHead } from "@/Layout";
import { clients as clientsApi, aiVisibility as aiVisibilityApi } from "@/api";
import { useAuth } from "@/auth";
import { ArrowsClockwise, ChartBar, CheckCircle, Lightning, Sparkle, TrendUp, WarningCircle } from "@phosphor-icons/react";
import { canManageAdminSurfaces } from "@/rbac";

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
  const [inferredBrand, setInferredBrand] = React.useState("");
  const [inferredDomain, setInferredDomain] = React.useState("");
  const [brandOverrideEnabled, setBrandOverrideEnabled] = React.useState(false);
  const [brandOverride, setBrandOverride] = React.useState("");
  const [domainOverrideEnabled, setDomainOverrideEnabled] = React.useState(false);
  const [domainOverride, setDomainOverride] = React.useState("");
  const [marketOverrideEnabled, setMarketOverrideEnabled] = React.useState(false);
  const [marketOverride, setMarketOverride] = React.useState("");
  const [scans, setScans] = React.useState([]);
  const [selectedScanId, setSelectedScanId] = React.useState("");
  const [runs, setRuns] = React.useState([]);
  const [busy, setBusy] = React.useState(false);
  const [regenBusy, setRegenBusy] = React.useState(false);
  const [saveBusy, setSaveBusy] = React.useState(false);
  const [runBusy, setRunBusy] = React.useState(false);
  const [loadingRuns, setLoadingRuns] = React.useState(false);
  const [err, setErr] = React.useState("");

  const loadEnt = React.useCallback(async () => {
    try {
      const r = await aiVisibilityApi.entitlement();
      setEnt(r);
    } catch {
      setEnt({ ok: false, enabled: canManageAdminSurfaces(user), reason: "unknown" });
    }
  }, [user]);

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

  const loadScans = React.useCallback(async (cfgId) => {
    if (!cfgId) { setScans([]); setSelectedScanId(""); return; }
    const r = await aiVisibilityApi.listScans(cfgId, 30);
    const s = r?.scans || [];
    setScans(s);
    const first = s[0]?.scan_id || "";
    setSelectedScanId(first);
  }, []);

  const loadRuns = React.useCallback(async (cfgId, scanId) => {
    if (!cfgId || !scanId) { setRuns([]); return; }
    const r = await aiVisibilityApi.listRuns(cfgId, 150, scanId);
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
    setScans([]);
    setSelectedScanId("");
    setRuns([]);
    setErr("");
    loadConfigs(clientId).catch((e) => setErr(e?.response?.data?.detail || "Failed to load configs"));
  }, [clientId, loadConfigs]);

  React.useEffect(() => {
    const cfg = configs.find((c) => c.id === configId);
    if (!cfg) {
      setInferredBrand("");
      setInferredDomain("");
      setBrandOverrideEnabled(false);
      setBrandOverride("");
      setDomainOverrideEnabled(false);
      setDomainOverride("");
      setMarketOverrideEnabled(false);
      setMarketOverride("");
      setScans([]);
      setSelectedScanId("");
      setRuns([]);
      return;
    }
    setInferredBrand(cfg.inferred_brand || "");
    setInferredDomain(cfg.inferred_domain || "");
    const bo = String(cfg.brand_override || "").trim();
    setBrandOverrideEnabled(!!bo);
    setBrandOverride(bo || String(cfg.inferred_brand || ""));
    const dno = String(cfg.domain_override || "").trim();
    setDomainOverrideEnabled(!!dno);
    setDomainOverride(dno || String(cfg.inferred_domain || ""));
    const mo = String(cfg.market_override || "").trim();
    setMarketOverrideEnabled(!!mo);
    setMarketOverride(mo || String(cfg.market || ""));
    loadScans(cfg.id).catch(() => {});
  }, [configId, configs, loadScans]);

  React.useEffect(() => {
    if (!configId || !selectedScanId) return;
    setLoadingRuns(true);
    loadRuns(configId, selectedScanId).catch(() => {}).finally(() => setLoadingRuns(false));
  }, [configId, loadRuns, selectedScanId]);

  const enabled = !!ent?.enabled || canManageAdminSurfaces(user);

  const ensureConfig = async () => {
    if (!clientId) return;
    setBusy(true);
    setErr("");
    try {
      const r = await aiVisibilityApi.createConfig(clientId, {});
      const cid = r?.config?.id || "";
      await loadConfigs(clientId);
      if (cid) setConfigId(cid);
    } catch (e) {
      setErr(e?.response?.data?.detail || "Enable failed");
    } finally {
      setBusy(false);
    }
  };

  const refreshIntelligence = async () => {
    if (!configId) return;
    setRegenBusy(true);
    setErr("");
    try {
      await aiVisibilityApi.updateConfig(configId, {});
      await loadConfigs(clientId);
      await loadScans(configId);
    } catch (e) {
      setErr(e?.response?.data?.detail || "Refresh failed");
    } finally {
      setRegenBusy(false);
    }
  };

  const saveOverrides = async () => {
    if (!configId) return;
    setSaveBusy(true);
    setErr("");
    try {
      await aiVisibilityApi.updateConfig(configId, {
        brand_override: brandOverrideEnabled ? String(brandOverride || "").trim() : null,
        domain_override: domainOverrideEnabled ? String(domainOverride || "").trim() : null,
        market_override: marketOverrideEnabled ? String(marketOverride || "").trim() : null,
      });
      await loadConfigs(clientId);
      await loadScans(configId);
    } catch (e) {
      setErr(e?.response?.data?.detail || "Save failed");
    } finally {
      setSaveBusy(false);
    }
  };

  const runScan = async () => {
    if (!configId) return;
    setRunBusy(true);
    setErr("");
    try {
      const r = await aiVisibilityApi.run(configId);
      await loadScans(configId);
      if (r?.scan_id) setSelectedScanId(r.scan_id);
      if (r?.scan_id) await loadRuns(configId, r.scan_id);
    } catch (e) {
      setErr(e?.response?.data?.detail || "Scan failed");
    } finally {
      setRunBusy(false);
    }
  };

  const selectedScan = (scans || []).find((s) => s.scan_id === selectedScanId) || scans?.[0] || null;
  const overallScore = selectedScan?.overall_visibility_score ?? null;
  const marketRank = selectedScan?.share_of_voice?.market_rank ?? null;
  const sovItems = selectedScan?.share_of_voice?.items || [];
  const clientSov = (sovItems || []).find((x) => x?.is_client) || null;
  const platform = selectedScan?.platform_rankings || {};
  const trend = (scans || []).slice().reverse().slice(-10);
  const cfg = configs.find((c) => c.id === configId) || null;
  const autoMarket = selectedScan?.market || cfg?.market || "";

  return (
    <div>
      <PageHead
        title="AI Visibility"
        subtitle="Automated prompt intelligence and competitor discovery. No manual prompts, themes, competitors, or keyword inputs."
        actions={
          <div className="flex items-center gap-2">
            {!configId && (
              <button className="btn-primary text-xs" onClick={ensureConfig} disabled={!enabled || busy || !clientId} data-testid="ai-vis-enable">
                <CheckCircle size={14} /> {busy ? "Enabling…" : "Enable"}
              </button>
            )}
            {!!configId && (
              <>
                <button className="btn-ghost text-xs" onClick={refreshIntelligence} disabled={!enabled || regenBusy} data-testid="ai-vis-refresh-intel">
                  <ArrowsClockwise size={14} /> {regenBusy ? "Refreshing…" : "Refresh intelligence"}
                </button>
                <button className="btn-primary text-xs" onClick={runScan} disabled={!enabled || runBusy} data-testid="ai-vis-run">
                  <Lightning size={14} /> {runBusy ? "Scanning…" : "Run scan"}
                </button>
              </>
            )}
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

          {!!clientId && !configId && (
            <div className="text-[11px] text-slate-500 mt-3">
              No manual setup. Click Enable to auto-generate market, themes, prompts, and competitors from Website + GBP.
            </div>
          )}

          {!!configId && (
            <>
              <div className="divider my-4" />
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div className="p-3 rounded-md border border-white/5 bg-white/[0.02]">
                  <div className="text-xs text-slate-400">Brand match</div>
                  <input
                    className="input mt-2"
                    value={brandOverrideEnabled ? brandOverride : inferredBrand}
                    onFocus={() => {
                      if (!brandOverrideEnabled) {
                        setBrandOverrideEnabled(true);
                        setBrandOverride(inferredBrand || "");
                      }
                    }}
                    onChange={(e) => setBrandOverride(e.target.value)}
                    placeholder={inferredBrand || "Brand"}
                  />
                  {brandOverrideEnabled && (
                    <button
                      className="btn-ghost text-xs mt-2"
                      onClick={() => {
                        setBrandOverrideEnabled(false);
                        setBrandOverride("");
                      }}
                      type="button"
                    >
                      Use auto
                    </button>
                  )}
                </div>
                <div className="p-3 rounded-md border border-white/5 bg-white/[0.02]">
                  <div className="text-xs text-slate-400">Domain match</div>
                  <input
                    className="input mt-2"
                    value={domainOverrideEnabled ? domainOverride : inferredDomain}
                    onFocus={() => {
                      if (!domainOverrideEnabled) {
                        setDomainOverrideEnabled(true);
                        setDomainOverride(inferredDomain || "");
                      }
                    }}
                    onChange={(e) => setDomainOverride(e.target.value)}
                    placeholder={inferredDomain || "Domain"}
                  />
                  {domainOverrideEnabled && (
                    <button
                      className="btn-ghost text-xs mt-2"
                      onClick={() => {
                        setDomainOverrideEnabled(false);
                        setDomainOverride("");
                      }}
                      type="button"
                    >
                      Use auto
                    </button>
                  )}
                </div>
              </div>
              <div className="p-3 rounded-md border border-white/5 bg-white/[0.02] mt-3">
                <div className="text-xs text-slate-400">Market (auto)</div>
                <div className="mt-1 text-sm text-slate-200">{autoMarket || "—"}</div>
                <div className="text-xs text-slate-400 mt-3">Market override</div>
                <input
                  className="input mt-2"
                  value={marketOverrideEnabled ? marketOverride : ""}
                  onChange={(e) => {
                    if (!marketOverrideEnabled) setMarketOverrideEnabled(true);
                    setMarketOverride(e.target.value);
                  }}
                  placeholder="Optional override (leave blank to use auto)"
                />
                {marketOverrideEnabled && (
                  <button
                    className="btn-ghost text-xs mt-2"
                    onClick={() => {
                      setMarketOverrideEnabled(false);
                      setMarketOverride("");
                    }}
                    type="button"
                  >
                    Clear override
                  </button>
                )}
              </div>
              <div className="p-3 rounded-md border border-white/5 bg-white/[0.02] mt-3">
                <div className="text-xs text-slate-400">Automation inputs</div>
                <div className="mt-1 text-sm text-slate-200">Website crawl · GBP metadata · Services</div>
                <div className="text-[11px] text-slate-500 mt-1">Prompts/themes/competitors are regenerated dynamically every scan.</div>
              </div>
              <div className="flex items-center justify-end mt-3">
                <button className="btn-primary text-xs" onClick={saveOverrides} disabled={!enabled || saveBusy}>
                  {saveBusy ? "Saving…" : "Save"}
                </button>
              </div>
            </>
          )}
        </div>

        <div className="card-flat p-5">
          <div className="flex items-center justify-between mb-3">
            <div>
              <div className="text-sm font-semibold flex items-center gap-2"><Sparkle size={16} weight="duotone" /> AI Visibility Command Center</div>
              <div className="text-xs text-slate-500">Overall score · Market rank · Share of voice · Platform rankings · Trend</div>
            </div>
            {!!selectedScan && (
              <select className="input !py-1 !text-xs !w-[220px]" value={selectedScanId} onChange={(e) => setSelectedScanId(e.target.value)}>
                {scans.map((s) => (
                  <option key={s.scan_id} value={s.scan_id}>{fmtDate(s.created_at)} · {s.overall_visibility_score}%</option>
                ))}
              </select>
            )}
          </div>

          {!selectedScan && <div className="p-10 text-center text-slate-400" data-testid="ai-vis-empty-runs">Run the first scan to populate the Command Center.</div>}

          {!!selectedScan && (
            <>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4" data-testid="ai-vis-command-center">
                <div className="p-4 rounded-lg border border-white/5 bg-white/[0.02]">
                  <div className="text-xs text-slate-400">Overall Visibility Score</div>
                  <div className="mt-1 text-2xl font-bold flex items-center gap-2"><ChartBar size={18} /> {overallScore}%</div>
                  <div className="text-[11px] text-slate-500 mt-1">{selectedScan.hits}/{selectedScan.total} hits</div>
                </div>
                <div className="p-4 rounded-lg border border-white/5 bg-white/[0.02]">
                  <div className="text-xs text-slate-400">Overall Market Rank</div>
                  <div className="mt-1 text-2xl font-bold">#{marketRank || "—"}</div>
                  <div className="text-[11px] text-slate-500 mt-1">Ranked by mention frequency across prompts</div>
                </div>
                <div className="p-4 rounded-lg border border-white/5 bg-white/[0.02]">
                  <div className="text-xs text-slate-400">Share of Voice</div>
                  <div className="mt-1 text-2xl font-bold flex items-center gap-2"><TrendUp size={18} /> {clientSov ? `${Math.round((clientSov.share || 0) * 100)}%` : "—"}</div>
                  <div className="text-[11px] text-slate-500 mt-1">{clientSov ? `${clientSov.mentions} mentions` : ""}</div>
                </div>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <div className="p-4 rounded-lg border border-white/5 bg-white/[0.02]">
                  <div className="text-sm font-semibold mb-2">Platform Rankings</div>
                  <div className="space-y-2">
                    {Object.entries(platform).map(([k, v]) => (
                      <div key={k} className="flex items-center justify-between">
                        <div className="text-sm text-slate-300">{k}</div>
                        <div className="mono text-sm text-slate-200">{v.score}%</div>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="p-4 rounded-lg border border-white/5 bg-white/[0.02]">
                  <div className="text-sm font-semibold mb-2">Visibility Trend (last 10 scans)</div>
                  {trend.length === 0 && <div className="text-sm text-slate-500">No history yet.</div>}
                  {trend.length > 0 && (
                    <div className="space-y-2">
                      {trend.map((s) => (
                        <div key={s.scan_id} className="flex items-center gap-3">
                          <div className="mono text-[11px] text-slate-500 w-24">{fmtDate(s.created_at)}</div>
                          <div className="flex-1 h-2 rounded-full bg-white/5 overflow-hidden">
                            <div className="h-2 bg-[#2FE0C2]" style={{ width: `${Math.min(100, Math.max(0, Number(s.overall_visibility_score || 0)))}%` }} />
                          </div>
                          <div className="mono text-[11px] text-slate-400 w-12 text-right">{s.overall_visibility_score}%</div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mt-4">
                <div className="p-4 rounded-lg border border-white/5 bg-white/[0.02]">
                  <div className="text-sm font-semibold mb-2">Top Competitors (AI mentions)</div>
                  {(selectedScan.competitors || []).length === 0 && <div className="text-sm text-slate-500">No competitor mentions captured.</div>}
                  <div className="space-y-2">
                    {(selectedScan.competitors || []).slice(0, 8).map((c, idx) => (
                      <div key={`${c.domain || c.name}-${idx}`} className="flex items-center justify-between gap-3">
                        <div className="min-w-0">
                          <div className="text-sm text-slate-200 truncate">{c.name || c.domain || "—"}</div>
                          {!!c.domain && <div className="text-[11px] text-slate-500 mono truncate">{c.domain}</div>}
                        </div>
                        <span className="chip chip-muted mono">{c.mentions}</span>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="p-4 rounded-lg border border-white/5 bg-white/[0.02]">
                  <div className="text-sm font-semibold mb-2">Dynamic Theme Discovery</div>
                  <div className="text-xs text-slate-500 mb-2">Generated every scan (service, trust, pricing, reviews, location, industry, competitor).</div>
                  <div className="space-y-2 max-h-[260px] overflow-auto">
                    {(selectedScan.themes || []).slice(0, 12).map((t, idx) => (
                      <div key={`${t.name}-${idx}`} className="p-3 rounded-md border border-white/5">
                        <div className="flex items-center justify-between gap-3">
                          <div className="text-sm font-medium">{t.name}</div>
                          <span className="chip chip-muted">{(t.prompts || []).length} prompts</span>
                        </div>
                        <div className="text-[11px] text-slate-500 mt-1">{t.type}</div>
                        <div className="mt-2 space-y-1">
                          {(t.prompts || []).slice(0, 4).map((p0, j) => (
                            <div key={j} className="text-xs text-slate-300">• {p0.query}</div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mt-4">
                <div className="p-4 rounded-lg border border-white/5 bg-white/[0.02]">
                  <div className="text-sm font-semibold mb-2">AI Content Intelligence</div>
                  <div className="text-xs text-slate-500">Merged: Content Audit + Optimizer + Keyword Planner → one module.</div>
                  <div className="mt-2 text-sm text-slate-300">Source: Website + GBP. Outputs are generated automatically (no manual inputs).</div>
                </div>
                <div className="p-4 rounded-lg border border-white/5 bg-white/[0.02]">
                  <div className="text-sm font-semibold mb-2">AI Growth Engine™</div>
                  <div className="text-xs text-slate-500">Merged: Recommendation Center + Takeover Plan + Simulator → one workflow.</div>
                  <div className="mt-2 text-sm text-slate-300">Source: Scan mentions + KPI context. Produces prioritized fixes and roadmap steps.</div>
                </div>
              </div>

              <div className="divider my-4" />

              <div className="flex items-center justify-between">
                <div className="text-sm font-semibold">Latest scan details</div>
                <div className="text-xs text-slate-500">{loadingRuns ? "Loading…" : `${runs.length} runs`}</div>
              </div>

              {runs.length > 0 && (
                <div className="mt-3 overflow-hidden rounded-lg border border-white/5">
                  {runs.slice(0, 90).map((r, i) => (
                    <div key={r.id || i} className={`p-3 flex items-center justify-between gap-3 ${i !== Math.min(runs.length, 90) - 1 ? "border-b border-white/5" : ""}`}>
                      <div className="min-w-0">
                        <div className="text-[13px] truncate">{r.keyword}</div>
                        <div className="text-[11px] text-slate-500 mono">{r.provider} · {r.prompt_kind || "—"} · {r.theme || "—"}</div>
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
            </>
          )}
        </div>
      </div>
    </div>
  );
}
