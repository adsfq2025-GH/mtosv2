import React, { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { meetings, aiModels, actionItems, contentCaptures } from "../api";
import { PageHead } from "../Layout";
import {
  Sparkle, FileText, ChatCircle, Trophy, Warning, Lightbulb, Question, Megaphone,
  CheckCircle, Clock, ListChecks, Robot, ArrowsClockwise, EnvelopeSimple, Info,
} from "@phosphor-icons/react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "../components/ui/dialog";

function ExplainDialog({ title, explain }) {
  if (!explain) return null;
  const sources = explain.data_sources_analyzed || explain.dataSourcesAnalyzed || [];
  const timePeriod = explain.time_period || explain.timePeriod || {};
  return (
    <Dialog>
      <DialogTrigger asChild>
        <button className="chip !px-2 !py-1 !bg-white/5 !border-white/10 hover:!bg-white/10" type="button" aria-label="AI source transparency">
          <Info size={14} weight="duotone" />
        </button>
      </DialogTrigger>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            <div className="p-3 rounded-md border border-white/10 bg-white/[0.02]">
              <div className="text-xs text-white/60">Source Used</div>
              <div className="mt-1">{String(explain.source_used || explain.sourceUsed || "—")}</div>
            </div>
            <div className="p-3 rounded-md border border-white/10 bg-white/[0.02]">
              <div className="text-xs text-white/60">Confidence</div>
              <div className="mt-1">{typeof explain.confidence === "number" ? `${explain.confidence}%` : String(explain.confidence || "—")}</div>
            </div>
          </div>
          <div className="p-3 rounded-md border border-white/10 bg-white/[0.02]">
            <div className="text-xs text-white/60">Time Period</div>
            <div className="mt-1">
              <div>Current: {String(timePeriod.current || timePeriod.current_period || "—")}</div>
              <div>Compared: {String(timePeriod.comparison || timePeriod.comparison_period || "—")}</div>
            </div>
          </div>
          <div className="p-3 rounded-md border border-white/10 bg-white/[0.02]">
            <div className="text-xs text-white/60">Logic Used</div>
            <div className="mt-1">{String(explain.logic_used || explain.logicUsed || "—")}</div>
          </div>
          <div className="p-3 rounded-md border border-white/10 bg-white/[0.02]">
            <div className="text-xs text-white/60">How AI Reached Conclusion</div>
            <div className="mt-1 whitespace-pre-wrap">{String(explain.calculation || explain.reasoning || explain.how || "—")}</div>
          </div>
          {!!sources.length && (
            <div className="p-3 rounded-md border border-white/10 bg-white/[0.02]">
              <div className="text-xs text-white/60">Data Sources Analyzed</div>
              <div className="mt-1 flex flex-wrap gap-2">
                {sources.map((s) => (
                  <span key={String(s)} className="chip">{String(s)}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function ModelSelect({ value, onChange }) {
  const [models, setModels] = useState([]);
  const loadModels = useCallback(() => { aiModels.list().then(setModels).catch(() => {}); }, []);
  useEffect(() => { loadModels(); }, [loadModels]);
  useEffect(() => {
    if (!models.length) return;
    if (models.some((m) => m.key === value && m.enabled !== false)) return;
    const preferred = models.find((m) => m.recommended && m.enabled !== false) || models.find((m) => m.enabled !== false) || models[0];
    if (preferred?.key) onChange(preferred.key);
  }, [models, onChange, value]);
  return (
    <select className="input !w-auto !py-2 !px-3 text-sm" value={value} onChange={(e) => onChange(e.target.value)} data-testid="ai-model-select">
      {models.map((m) => (
        <option key={m.key} value={m.key} disabled={m.enabled === false}>
          {m.label}{m.enabled === false && m.required_env ? ` (set ${m.required_env})` : ""}
        </option>
      ))}
    </select>
  );
}

const sevChip = (s) => s === "high" ? "chip-danger" : s === "low" ? "chip-success" : "chip-warn";

export default function MeetingDetail() {
  const { id } = useParams();
  const [m, setM] = useState(null);
  const [model, setModel] = useState("gemini-direct");
  const [tab, setTab] = useState("brief");
  const [transcript, setTranscript] = useState("");
  const [busy, setBusy] = useState("");
  const [aiErr, setAiErr] = useState("");
  const [actions, setActions] = useState([]);
  const [content, setContent] = useState([]);
  const [recap, setRecap] = useState(null);
  const [checklist, setChecklist] = useState({});
  const [automation, setAutomation] = useState(null);
  const [qaScorecard, setQaScorecard] = useState(null);

  const reload = useCallback(
    () => Promise.all([
      meetings.get(id),
      actionItems.list({ meeting_id: id }),
      contentCaptures.list(),
      meetings.automation(id).catch(() => null),
      meetings.qa(id).catch(() => null),
    ]).then(([meeting, a, c, autoRes, qaRes]) => {
      setM(meeting); setActions(a);
      setContent(c.filter(cap => cap.meeting_id === id));
      setChecklist(meeting.checklist || {});
      if (meeting.transcript) setTranscript(meeting.transcript);
      if (meeting.recap_html) setRecap({ html: meeting.recap_html, plain: meeting.recap_email });
      setAutomation(autoRes);
      setQaScorecard(qaRes?.scorecard || null);
    }),
    [id],
  );
  useEffect(() => { reload(); }, [reload]);

  const genBrief = async () => {
    setBusy("brief");
    setAiErr("");
    try {
      const meeting = await meetings.generateBrief(id, { model });
      setM(meeting);
      setChecklist(meeting.checklist || {});
      await reload().catch(() => {});
    } catch (e) {
      const raw = e?.response?.data;
      const detail = typeof raw === "string" ? raw : raw?.detail;
      const status = e?.response?.status;
      if (detail) setAiErr(String(detail));
      else if (status) setAiErr(`Brief generation failed (HTTP ${status})`);
      else setAiErr(`Brief generation failed (${e?.message || "Network error"})`);
    } finally {
      setBusy("");
    }
  };
  const exportHtml = async () => {
    setBusy("export");
    try {
      const res = await meetings.exportHtml(id);
      const html = res?.html || "";
      const blob = new Blob([html], { type: "text/html;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${m?.title || "meeting"}.html`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } finally {
      setBusy("");
    }
  };
  const analyze = async () => {
    if (!transcript.trim()) return;
    setBusy("analyze");
    try { await meetings.analyzeTranscript(id, { transcript, model }); await reload(); setTab("analysis"); } finally { setBusy(""); }
  };
  const genRecap = async () => {
    setBusy("recap"); setTab("recap"); setRecap(null);
    try {
      const r = await meetings.generateRecap(id, { model });
      setRecap(r);
      await reload().catch(() => {});
    } catch (e) {
      alert(e?.response?.data?.detail || "Recap generation failed");
    } finally {
      setBusy("");
    }
  };

  const syncMeetTranscript = async () => {
    setBusy("sync_meet");
    try {
      const updated = await meetings.syncMeetTranscript(id);
      setM(updated);
      setTranscript(updated.transcript || "");
    } catch (e) {
      alert(e?.response?.data?.detail || "Google Meet transcript sync failed");
    } finally {
      setBusy("");
    }
  };

  const genAutomation = async () => {
    setBusy("automation");
    try {
      const r = await meetings.generateAutomation(id);
      setAutomation(r);
      await reload().catch(() => {});
    } catch (e) {
      alert(e?.response?.data?.detail || "Automation generation failed");
    } finally {
      setBusy("");
    }
  };

  const approveAutomation = async () => {
    if (!window.confirm("Approve this automation draft and create internal tasks/tickets?")) return;
    setBusy("approve_automation");
    try {
      await meetings.approveAutomation(id);
      await reload().catch(() => {});
    } catch (e) {
      alert(e?.response?.data?.detail || "Automation approval failed");
    } finally {
      setBusy("");
    }
  };

  const scoreQa = async () => {
    setBusy("qa");
    try {
      const r = await meetings.scoreQa(id);
      setQaScorecard(r?.scorecard || null);
      await reload().catch(() => {});
    } catch (e) {
      alert(e?.response?.data?.detail || "QA scoring failed");
    } finally {
      setBusy("");
    }
  };
  const toggleCheck = async (key) => {
    const nl = { ...checklist, [key]: !checklist[key] };
    setChecklist(nl); await meetings.update(id, { checklist: nl });
  };

  const CHECKLIST_ITEMS = [
    ["wins", "Wins delivered"],
    ["issues", "Issues with action plan"],
    ["progress", "Campaign progress reviewed"],
    ["strategic", "Strategic recommendation shared"],
    ["client_voice", "Open-ended client questions asked"],
    ["testimonial", "Testimonial / content opportunity assessed"],
    ["next30", "Next 30 days plan agreed"],
    ["actions", "Named action items with owners + dates"],
    ["nextmeeting", "Next meeting date confirmed"],
    ["sentiment", "Sentiment read logged"],
  ];

  if (!m) return <div className="text-slate-400">Loading…</div>;

  return (
    <div>
      <PageHead
        breadcrumbs={[{ label: "Clients", to: "/clients" }, { label: m.client_name, to: `/clients/${m.client_id}` }, { label: m.title }]}
        title={m.title}
        subtitle={`${m.client_name} · ${m.scheduled_at || "Unscheduled"} · ${m.duration_minutes} min · ${m.status}`}
        actions={
          <>
            <ModelSelect value={model} onChange={setModel} />
            <button className="btn-ghost flex items-center gap-2" onClick={genBrief} disabled={busy === "brief"} data-testid="generate-brief-btn">
              {busy === "brief" ? <ArrowsClockwise size={14} className="animate-spin" /> : <Sparkle size={14} weight="duotone" />} {busy === "brief" ? "Generating…" : (m.brief_generated_at ? "Regenerate Brief" : "Generate Brief")}
            </button>
            <button className="btn-ghost flex items-center gap-2" onClick={exportHtml} disabled={busy === "export"} data-testid="export-html-btn">
              {busy === "export" ? <ArrowsClockwise size={14} className="animate-spin" /> : <FileText size={14} weight="duotone" />} Export HTML
            </button>
            {m.google_meet_url && <a href={m.google_meet_url} target="_blank" rel="noreferrer" className="btn-primary flex items-center gap-2" data-testid="open-meet-link">Open Meet</a>}
          </>
        }
      />
      {aiErr && <div className="card-flat p-4 mb-5 border border-red-500/30 bg-red-500/10 text-red-200 text-sm" data-testid="ai-error">{aiErr}</div>}

      {/* Tabs */}
      <div className="flex items-center gap-1 mb-5 overflow-x-auto">
        {[
          { k: "brief", label: "Brief", icon: FileText },
          { k: "live", label: "Live Mode", icon: ListChecks },
          { k: "transcript", label: "Transcript & Analysis", icon: ChatCircle },
          { k: "analysis", label: "AI Findings", icon: Robot },
          { k: "recap", label: "Recap Email", icon: EnvelopeSimple },
        ].map((t) => (
          <button key={t.k} onClick={() => setTab(t.k)} className={`px-4 py-2 rounded-md text-sm flex items-center gap-2 ${tab === t.k ? "bg-white/5 text-white border border-white/10" : "text-slate-400 hover:text-white"}`} data-testid={`tab-${t.k}`}>
            <t.icon size={14} weight="duotone" /> {t.label}
          </button>
        ))}
      </div>

      {/* BRIEF TAB */}
      {tab === "brief" && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
          <div className="lg:col-span-2 space-y-5">
            <section className="card-flat p-5">
              <div className="flex items-center gap-2 mb-3"><Trophy size={18} weight="duotone" color="#2FE0C2" /><h3 className="font-semibold">Wins</h3></div>
              {(m.wins || []).length === 0 && <EmptyHint label="Generate the brief to populate wins from your KPI snapshot." />}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                {(m.wins || []).map((w, i) => (
                  <div key={i} className="p-4 rounded-md border border-[#2FE0C2]/20 bg-[#2FE0C2]/5">
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-[10px] mono text-[#2FE0C2] uppercase tracking-wider">{w.metric || "WIN"} · {w.delta || ""}</div>
                      <ExplainDialog title={w.title || "Win"} explain={w.explain} />
                    </div>
                    <div className="font-semibold mt-1 text-sm">{w.title}</div>
                    <div className="text-xs text-slate-300 mt-1.5">{w.description}</div>
                  </div>
                ))}
              </div>
              {(m.wins_library || []).length > (m.wins || []).length && (
                <details className="mt-4">
                  <summary className="cursor-pointer text-xs text-[#3FA9F5]">View full wins library</summary>
                  <div className="mt-3 space-y-2">
                    {(m.wins_library || []).map((w, i) => (
                      <div key={i} className="p-3 rounded-md border border-white/5 bg-white/[0.02]">
                        <div className="text-[10px] mono text-slate-400 uppercase tracking-wider">{w.metric || "WIN"} · {w.delta || ""}</div>
                        <div className="font-medium text-sm mt-1">{w.title}</div>
                        <div className="text-xs text-slate-300 mt-1.5">{w.description}</div>
                      </div>
                    ))}
                  </div>
                </details>
              )}
            </section>

            <section className="card-flat p-5">
              <div className="flex items-center gap-2 mb-3"><Warning size={18} weight="duotone" color="#F59E0B" /><h3 className="font-semibold">Issues</h3></div>
              {(m.issues || []).length === 0 && <EmptyHint label="Generate the brief to surface important issues with action plans." />}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {(m.issues || []).map((iss, i) => (
                  <div key={i} className="p-4 rounded-md border border-white/5 bg-white/[0.02]">
                    <div className="flex items-center justify-between gap-2">
                      <div className="font-semibold text-sm">{iss.title}</div>
                      <div className="flex items-center gap-2">
                        <ExplainDialog title={iss.title || "Issue"} explain={iss.explain} />
                        <span className={`chip ${sevChip(iss.severity)}`}>{iss.severity}</span>
                      </div>
                    </div>
                    <div className="text-xs text-slate-300 mt-1.5">{iss.description}</div>
                    {iss.action_plan && <div className="text-xs text-slate-300 mt-2 p-2 rounded bg-[#3FA9F5]/10 border border-[#3FA9F5]/15"><strong className="text-[#3FA9F5]">Action plan:</strong> {iss.action_plan}</div>}
                  </div>
                ))}
              </div>
              {(m.issues_library || []).length > (m.issues || []).length && (
                <details className="mt-4">
                  <summary className="cursor-pointer text-xs text-[#3FA9F5]">View full issues library</summary>
                  <div className="mt-3 space-y-2">
                    {(m.issues_library || []).map((iss, i) => (
                      <div key={i} className="p-3 rounded-md border border-white/5 bg-white/[0.02]">
                        <div className="flex items-center justify-between"><div className="font-medium text-sm">{iss.title}</div><span className={`chip ${sevChip(iss.severity)}`}>{iss.severity}</span></div>
                        <div className="text-xs text-slate-300 mt-1.5">{iss.description}</div>
                        {iss.action_plan && <div className="text-xs text-slate-300 mt-2 p-2 rounded bg-[#3FA9F5]/10 border border-[#3FA9F5]/15"><strong className="text-[#3FA9F5]">Action plan:</strong> {iss.action_plan}</div>}
                      </div>
                    ))}
                  </div>
                </details>
              )}
            </section>

            <section className="card-flat p-5">
              <div className="flex items-center gap-2 mb-3"><Lightbulb size={18} weight="duotone" color="#3FA9F5" /><h3 className="font-semibold">Talking Points</h3></div>
              {(m.talking_points || []).length === 0 && <EmptyHint />}
              <ul className="space-y-2">{(m.talking_points || []).map((t, i) => <li key={i} className="text-sm"><strong className="text-white">{t.topic}:</strong> <span className="text-slate-300">{t.angle}</span></li>)}</ul>
              {(m.talking_points_library || []).length > (m.talking_points || []).length && (
                <details className="mt-4">
                  <summary className="cursor-pointer text-xs text-[#3FA9F5]">View full talking points library</summary>
                  <ul className="mt-3 space-y-2">
                    {(m.talking_points_library || []).map((t, i) => <li key={i} className="text-sm"><strong className="text-white">{t.topic}:</strong> <span className="text-slate-300">{t.angle}</span></li>)}
                  </ul>
                </details>
              )}
            </section>

            <section className="card-flat p-5">
              <div className="flex items-center gap-2 mb-3"><Question size={18} weight="duotone" color="#818CF8" /><h3 className="font-semibold">Suggested Engagement Questions</h3></div>
              {(m.suggested_questions || []).length === 0 && <EmptyHint />}
              <ul className="space-y-2 list-disc pl-5">{(m.suggested_questions || []).map((q, i) => <li key={i} className="text-sm text-slate-300">{q}</li>)}</ul>
            </section>

            <section className="card-flat p-5">
              <div className="flex items-center gap-2 mb-3"><ListChecks size={18} weight="duotone" color="#3FA9F5" /><h3 className="font-semibold">Preparation Checklist</h3></div>
              {(m.prep_checklist || []).length === 0 && <EmptyHint label="Generate the brief to get a tailored pre-meeting checklist." />}
              <ul className="space-y-2 list-disc pl-5">{(m.prep_checklist || []).map((p, i) => <li key={i} className="text-sm text-slate-300">{p}</li>)}</ul>
            </section>

            <section className="card-flat p-5">
              <div className="flex items-center gap-2 mb-3"><Robot size={18} weight="duotone" color="#2FE0C2" /><h3 className="font-semibold">Ace Up The Sleeve</h3></div>
              {(m.ace_up_the_sleeve || []).length === 0 && <EmptyHint label="Generate the brief to get backup responses and pivots for difficult moments." />}
              <div className="space-y-3">
                {(m.ace_up_the_sleeve || []).map((a, i) => (
                  <div key={i} className="p-3 rounded-md border border-white/5 bg-white/[0.02]">
                    <div className="text-xs text-slate-400 mono uppercase tracking-wider">Scenario</div>
                    <div className="text-sm text-slate-200 mt-1">{a.scenario || "—"}</div>
                    <div className="text-xs text-slate-400 mono uppercase tracking-wider mt-3">Response</div>
                    <div className="text-sm text-slate-300 mt-1">{a.response || "—"}</div>
                    {a.follow_up_question && <div className="text-sm text-slate-300 mt-2"><strong className="text-white">Follow-up:</strong> {a.follow_up_question}</div>}
                  </div>
                ))}
              </div>
            </section>
          </div>

          <div className="space-y-5">
            <section className="card-flat p-5">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2"><Megaphone size={18} weight="duotone" color="#2FE0C2" /><h3 className="font-semibold">Testimonial Opportunity</h3></div>
                <Link to="/testimonials" className="text-xs text-[#3FA9F5] hover:underline">View all</Link>
              </div>
              <div className="text-sm text-slate-300 leading-relaxed">{m.testimonial_opportunity || "—"}</div>
            </section>
            <section className="card-flat p-5">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2"><Sparkle size={18} weight="duotone" color="#3FA9F5" /><h3 className="font-semibold">Strategic Recommendations</h3></div>
                <Link to="/strategy" className="text-xs text-[#3FA9F5] hover:underline">View all</Link>
              </div>
              <ul className="space-y-2 list-disc pl-5">{(m.strategic_recommendations || []).map((r, i) => <li key={i} className="text-sm text-slate-300">{r}</li>)}</ul>
              {(m.strategic_recommendations || []).length === 0 && <EmptyHint />}
            </section>
            <section className="card-flat p-5">
              <div className="label mb-2">Health Signal</div>
              <div className="text-sm text-slate-300">{m.health_signal || "—"}</div>
              {m.brief_generated_at && <div className="mt-3 text-[11px] text-slate-500 mono">Brief generated · {new Date(m.brief_generated_at).toLocaleString()} · {m.brief_model}</div>}
            </section>
            <section className="card-flat p-5">
              <div className="label mb-2">KPI Snapshot</div>
              <details className="text-xs text-slate-300">
                <summary className="cursor-pointer text-[#3FA9F5]">View raw snapshot</summary>
                <pre className="mt-2 max-h-72 overflow-auto p-3 bg-black/40 rounded mono text-[11px]">{JSON.stringify(m.kpi_snapshot || {}, null, 2)}</pre>
              </details>
            </section>
          </div>
        </div>
      )}

      {/* LIVE MODE */}
      {tab === "live" && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
          <div className="lg:col-span-2 card-flat p-5">
            <h3 className="font-semibold mb-4 flex items-center gap-2"><ListChecks size={18} weight="duotone" /> Mandatory Talking Points Checklist</h3>
            <div className="space-y-2">
              {CHECKLIST_ITEMS.map(([k, label]) => (
                <label key={k} className="flex items-center gap-3 p-3 rounded-md border border-white/5 hover:bg-white/[0.03] cursor-pointer" data-testid={`check-${k}`}>
                  <input type="checkbox" checked={!!checklist[k]} onChange={() => toggleCheck(k)} className="w-4 h-4 accent-[#3FA9F5]" />
                  <span className={`text-sm ${checklist[k] ? "line-through text-slate-500" : "text-slate-200"}`}>{label}</span>
                  {checklist[k] && <CheckCircle size={14} className="ml-auto text-[#2FE0C2]" weight="fill" />}
                </label>
              ))}
            </div>
          </div>
          <div className="card-flat p-5">
            <h3 className="font-semibold mb-3 flex items-center gap-2"><Clock size={18} weight="duotone" /> Suggested Pacing</h3>
            <ol className="space-y-2 text-sm text-slate-300">
              <li><span className="mono text-[#3FA9F5]">0–3</span> · Rapport & agenda</li>
              <li><span className="mono text-[#3FA9F5]">3–13</span> · 3 Wins</li>
              <li><span className="mono text-[#3FA9F5]">13–25</span> · Performance & strategy</li>
              <li><span className="mono text-[#3FA9F5]">25–35</span> · 2 Issues + plan</li>
              <li><span className="mono text-[#3FA9F5]">35–45</span> · Client voice + testimonial moment</li>
              <li><span className="mono text-[#3FA9F5]">45–55</span> · Next 30 days</li>
              <li><span className="mono text-[#3FA9F5]">55–60</span> · Recap & close</li>
            </ol>
            <div className="divider my-4" />
            <p className="text-xs text-slate-400">After the call, paste the Google Meet transcript in the next tab to auto-extract action items, sentiment and content moments.</p>
          </div>
        </div>
      )}

      {/* TRANSCRIPT */}
      {tab === "transcript" && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
          <div className="lg:col-span-2 card-flat p-5">
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-semibold flex items-center gap-2"><ChatCircle size={18} weight="duotone" /> Meeting Transcript</h3>
              <div className="flex items-center gap-2">
                {m.google_meet_url && (
                  <button className="btn-ghost flex items-center gap-2" onClick={syncMeetTranscript} disabled={busy === "sync_meet"} data-testid="sync-meet-transcript-btn">
                    {busy === "sync_meet" ? <ArrowsClockwise size={14} className="animate-spin" /> : "Sync from Meet"}
                  </button>
                )}
                <button className="btn-primary flex items-center gap-2" onClick={analyze} disabled={busy === "analyze" || !transcript.trim()} data-testid="analyze-transcript-btn">
                  {busy === "analyze" ? <ArrowsClockwise size={14} className="animate-spin" /> : <Robot size={14} weight="duotone" />} Analyze with AI
                </button>
              </div>
            </div>
            <textarea
              className="input !min-h-[440px] font-mono text-[12.5px] leading-relaxed"
              placeholder="Paste your Google Meet transcript (from 'Gemini takes notes' in Drive) or write meeting notes here…"
              value={transcript}
              onChange={(e) => setTranscript(e.target.value)}
              data-testid="transcript-textarea"
            />
            <div className="text-[11px] text-slate-500 mt-2 mono">{transcript.length} chars</div>
          </div>
          <div className="card-flat p-5">
            <h3 className="font-semibold mb-2">How it works</h3>
            <ol className="text-sm text-slate-300 space-y-2 list-decimal pl-4">
              <li>In Google Meet, turn on <strong>“Take notes with Gemini”</strong>.</li>
              <li>After the call Drive saves the transcript Doc.</li>
              <li>Copy the transcript and paste it here.</li>
              <li>Click <strong>Analyze with AI</strong> — we extract action items, sentiment, content opportunities & churn signals.</li>
            </ol>
            <div className="divider my-4" />
            <p className="text-xs text-slate-400">When the Google Drive integration is connected, transcripts will auto-attach to the most recent meeting.</p>
          </div>
        </div>
      )}

      {/* ANALYSIS */}
      {tab === "analysis" && (
        <div className="space-y-5">
          {!m.transcript_analyzed_at && <EmptyHint label="Run the transcript analysis to populate this tab." />}
          {m.transcript_analyzed_at && (
            <>
              <div className="card-flat p-5">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="font-semibold">Sentiment & Summary</h3>
                  <span className={`chip ${m.sentiment === "positive" ? "chip-success" : m.sentiment === "negative" ? "chip-danger" : "chip-info"}`}>{m.sentiment}</span>
                </div>
                <p className="text-sm text-slate-300">{m.sentiment_summary}</p>
              </div>
              {(() => {
                const profile = m?.transcript_analysis?.client_profile || {};
                const has =
                  profile.personality ||
                  profile.decision_making_style ||
                  (profile.business_goals || []).length ||
                  (profile.growth_goals || []).length ||
                  (profile.trust_issues || []).length ||
                  (profile.frustrations || []).length ||
                  (profile.hidden_risks || []).length ||
                  (profile.relationship_opportunities || []).length ||
                  (profile.operational_bottlenecks || []).length;
                if (!has) return null;
                return (
                  <div className="card-flat p-5">
                    <h3 className="font-semibold mb-3">Client Intelligence</h3>
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                      <div className="p-3 rounded-md border border-white/5 bg-white/[0.02]">
                        <div className="label mb-1">Personality</div>
                        <div className="text-sm text-slate-300">{profile.personality || "—"}</div>
                      </div>
                      <div className="p-3 rounded-md border border-white/5 bg-white/[0.02]">
                        <div className="label mb-1">Decision-Making Style</div>
                        <div className="text-sm text-slate-300">{profile.decision_making_style || "—"}</div>
                      </div>
                    </div>
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mt-3">
                      <InsightList title="Business Goals" items={profile.business_goals} />
                      <InsightList title="Growth Goals" items={profile.growth_goals} />
                      <InsightList title="Trust Issues" items={profile.trust_issues} />
                      <InsightList title="Frustrations" items={profile.frustrations} />
                      <InsightList title="Hidden Risks" items={profile.hidden_risks} />
                      <InsightList title="Relationship Opportunities" items={profile.relationship_opportunities} />
                      <InsightList title="Operational Bottlenecks" items={profile.operational_bottlenecks} />
                    </div>
                  </div>
                );
              })()}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
                <div className="card-flat p-5">
                  <h3 className="font-semibold mb-3">Action Items ({actions.length})</h3>
                  {actions.length === 0 && <EmptyHint />}
                  <div className="space-y-2">
                    {actions.map((a) => (
                      <div key={a.id} className="p-3 rounded-md border border-white/5">
                        <div className="flex items-center justify-between"><div className="text-sm font-medium">{a.title}</div><span className={`chip ${a.priority === "high" ? "chip-danger" : a.priority === "low" ? "chip-success" : "chip-warn"}`}>{a.priority}</span></div>
                        <div className="text-xs text-slate-400 mt-1">{a.description}</div>
                        <div className="text-xs text-slate-500 mt-1 mono">{a.owner_type} · due {a.due_date || "TBD"}</div>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="card-flat p-5">
                  <h3 className="font-semibold mb-3 flex items-center gap-2"><Megaphone size={16} weight="duotone" color="#2FE0C2" /> Content Opportunities</h3>
                  {content.length === 0 && <EmptyHint label="No marketing-worthy moments detected." />}
                  <div className="space-y-2">
                    {content.map((c) => (
                      <div key={c.id} className="p-3 rounded-md border border-[#2FE0C2]/20 bg-[#2FE0C2]/5">
                        <div className="flex items-center justify-between"><span className="chip chip-success">{c.type}</span><span className="text-[10px] text-slate-500">→ Marketing queue</span></div>
                        <div className="text-sm text-slate-200 mt-2 italic">"{c.content}"</div>
                        {c.notes && <div className="text-xs text-slate-400 mt-2">Why strong: {c.notes}</div>}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
              <div className="card-flat p-5">
                <button className="btn-primary flex items-center gap-2" onClick={genRecap} disabled={busy === "recap"} data-testid="generate-recap-btn">
                  {busy === "recap" ? <ArrowsClockwise size={14} className="animate-spin" /> : <EnvelopeSimple size={14} weight="duotone" />} Generate Recap Email
                </button>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
                <div className="card-flat p-5">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="font-semibold">Meeting Automation</h3>
                    <div className="flex items-center gap-2">
                      <button className="btn-ghost text-xs" onClick={genAutomation} disabled={busy === "automation"} data-testid="gen-automation-btn">
                        {busy === "automation" ? <ArrowsClockwise size={12} className="animate-spin" /> : "Generate draft"}
                      </button>
                      <button className="btn-primary text-xs" onClick={approveAutomation} disabled={busy === "approve_automation" || !(automation?.draft)} data-testid="approve-automation-btn">
                        {busy === "approve_automation" ? <ArrowsClockwise size={12} className="animate-spin" /> : "Approve"}
                      </button>
                    </div>
                  </div>
                  {!(automation?.draft) && <div className="text-sm text-slate-500 py-6 text-center">Generate a draft to create recap, action items, department tickets, and escalations.</div>}
                  {automation?.draft && (
                    <div className="space-y-3">
                      <div className="p-3 rounded-md border border-white/5 bg-white/[0.02]">
                        <div className="label mb-1">Meeting summary</div>
                        <div className="text-sm text-slate-300">{automation.draft.meeting_summary || "—"}</div>
                      </div>
                      <div className="grid grid-cols-3 gap-3">
                        <MiniStat label="Actions" value={(automation.draft.follow_up_action_items || []).length} />
                        <MiniStat label="Tickets" value={(automation.draft.department_tickets || []).length} />
                        <MiniStat label="Escalations" value={(automation.draft.escalation_requests || []).length} />
                      </div>
                    </div>
                  )}
                </div>

                <div className="card-flat p-5">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="font-semibold">QA Scorecard</h3>
                    <button className="btn-ghost text-xs" onClick={scoreQa} disabled={busy === "qa"} data-testid="score-qa-btn">
                      {busy === "qa" ? <ArrowsClockwise size={12} className="animate-spin" /> : "Score meeting"}
                    </button>
                  </div>
                  {!qaScorecard && <div className="text-sm text-slate-500 py-6 text-center">Score the meeting to get coaching feedback and KPI scoring.</div>}
                  {qaScorecard && (
                    <div className="space-y-3">
                      <div className="flex items-center justify-between">
                        <div className="label">Total score</div>
                        <span className="chip chip-info mono">{qaScorecard.total_score}</span>
                      </div>
                      <div className="grid grid-cols-2 gap-2">
                        {Object.entries(qaScorecard.dimensions || {}).map(([k, v]) => (
                          <div key={k} className="p-3 rounded-md border border-white/5 bg-white/[0.02]">
                            <div className="text-[11px] text-slate-500 uppercase tracking-wider">{k.replaceAll("_", " ")}</div>
                            <div className="text-sm mono mt-1">{v}</div>
                          </div>
                        ))}
                      </div>
                      {qaScorecard.feedback && <div className="text-sm text-slate-300 leading-relaxed">{qaScorecard.feedback}</div>}
                    </div>
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {/* RECAP */}
      {tab === "recap" && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          <div className="card-flat p-5">
            <h3 className="font-semibold mb-3">Recap Email (HTML preview)</h3>
            {busy === "recap" && (
              <div className="flex items-center gap-3 text-sm text-slate-300 py-10 justify-center border border-dashed border-white/10 rounded-md" data-testid="recap-loading">
                <ArrowsClockwise size={16} className="animate-spin" /> Generating recap email…
              </div>
            )}
            {!recap && busy !== "recap" && <EmptyHint label="Generate recap from the AI Findings tab." />}
            {recap && <div className="prose-doc max-h-[600px] overflow-auto p-4 bg-white/[0.02] rounded border border-white/5" data-testid="recap-html" dangerouslySetInnerHTML={{ __html: recap.html }} />}
          </div>
          <div className="card-flat p-5">
            <h3 className="font-semibold mb-3">Plain Text</h3>
            {recap && <textarea className="input !min-h-[600px] font-mono text-[12.5px]" defaultValue={recap.plain} data-testid="recap-plain-text" />}
            {!recap && <EmptyHint label="Plain text version appears here after generation." />}
          </div>
        </div>
      )}
    </div>
  );
}

function EmptyHint({ label }) {
  return <div className="text-sm text-slate-500 py-6 text-center border border-dashed border-white/10 rounded-md">{label || "Nothing here yet. Run the AI generator above."}</div>;
}

function MiniStat({ label, value }) {
  return (
    <div className="p-3 rounded-md border border-white/5 bg-white/[0.02]">
      <div className="text-[11px] text-slate-500 uppercase tracking-wider">{label}</div>
      <div className="text-xl font-bold mono mt-1">{value}</div>
    </div>
  );
}

function InsightList({ title, items }) {
  const list = Array.isArray(items) ? items.filter((x) => String(x || "").trim()) : [];
  return (
    <div className="p-3 rounded-md border border-white/5 bg-white/[0.02]">
      <div className="label mb-1">{title}</div>
      {list.length === 0 ? (
        <div className="text-sm text-slate-500">—</div>
      ) : (
        <ul className="list-disc pl-5 text-sm text-slate-300 space-y-1">
          {list.map((x, i) => (
            <li key={i}>{String(x)}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
