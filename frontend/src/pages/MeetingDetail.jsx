import React, { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { meetings, aiModels, actionItems, contentCaptures } from "../api";
import { PageHead } from "../Layout";
import {
  Sparkle, FileText, ChatCircle, Trophy, Warning, Lightbulb, Question, Megaphone,
  CheckCircle, Clock, ListChecks, Robot, ArrowsClockwise, EnvelopeSimple,
} from "@phosphor-icons/react";

function ModelSelect({ value, onChange }) {
  const [models, setModels] = useState([]);
  const loadModels = useCallback(() => { aiModels.list().then(setModels).catch(() => {}); }, []);
  useEffect(() => { loadModels(); }, [loadModels]);
  return (
    <select className="input !w-auto !py-2 !px-3 text-sm" value={value} onChange={(e) => onChange(e.target.value)} data-testid="ai-model-select">
      {models.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
    </select>
  );
}

const sevChip = (s) => s === "high" ? "chip-danger" : s === "low" ? "chip-success" : "chip-warn";

export default function MeetingDetail() {
  const { id } = useParams();
  const [m, setM] = useState(null);
  const [model, setModel] = useState("llama-fast");
  const [tab, setTab] = useState("brief");
  const [transcript, setTranscript] = useState("");
  const [busy, setBusy] = useState("");
  const [actions, setActions] = useState([]);
  const [content, setContent] = useState([]);
  const [recap, setRecap] = useState(null);
  const [checklist, setChecklist] = useState({});

  const reload = useCallback(
    () => Promise.all([
      meetings.get(id),
      actionItems.list({ meeting_id: id }),
      contentCaptures.list(),
    ]).then(([meeting, a, c]) => {
      setM(meeting); setActions(a);
      setContent(c.filter(cap => cap.meeting_id === id));
      setChecklist(meeting.checklist || {});
      if (meeting.transcript) setTranscript(meeting.transcript);
      if (meeting.recap_html) setRecap({ html: meeting.recap_html, plain: meeting.recap_email });
    }),
    [id],
  );
  useEffect(() => { reload(); }, [reload]);

  const genBrief = async () => {
    setBusy("brief");
    try { await meetings.generateBrief(id, { model }); await reload(); } finally { setBusy(""); }
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
    try { const r = await meetings.generateRecap(id, { model }); setRecap(r); await reload(); } finally { setBusy(""); }
  };
  const toggleCheck = async (key) => {
    const nl = { ...checklist, [key]: !checklist[key] };
    setChecklist(nl); await meetings.update(id, { checklist: nl });
  };

  const CHECKLIST_ITEMS = [
    ["wins", "3 wins delivered"],
    ["issues", "2 issues with action plan"],
    ["progress", "Campaign progress reviewed"],
    ["strategic", "1 new strategic recommendation shared"],
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
              {busy === "brief" ? <ArrowsClockwise size={14} className="animate-spin" /> : <Sparkle size={14} weight="duotone" />} {m.brief_generated_at ? "Regenerate Brief" : "Generate Brief"}
            </button>
            <button className="btn-ghost flex items-center gap-2" onClick={exportHtml} disabled={busy === "export"} data-testid="export-html-btn">
              {busy === "export" ? <ArrowsClockwise size={14} className="animate-spin" /> : <FileText size={14} weight="duotone" />} Export HTML
            </button>
            {m.google_meet_url && <a href={m.google_meet_url} target="_blank" rel="noreferrer" className="btn-primary flex items-center gap-2" data-testid="open-meet-link">Open Meet</a>}
          </>
        }
      />

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
              <div className="flex items-center gap-2 mb-3"><Trophy size={18} weight="duotone" color="#2FE0C2" /><h3 className="font-semibold">3 Wins</h3></div>
              {(m.wins || []).length === 0 && <EmptyHint label="Generate the brief to populate wins from your KPI snapshot." />}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                {(m.wins || []).map((w, i) => (
                  <div key={i} className="p-4 rounded-md border border-[#2FE0C2]/20 bg-[#2FE0C2]/5">
                    <div className="text-[10px] mono text-[#2FE0C2] uppercase tracking-wider">{w.metric || "WIN"} · {w.delta || ""}</div>
                    <div className="font-semibold mt-1 text-sm">{w.title}</div>
                    <div className="text-xs text-slate-300 mt-1.5">{w.description}</div>
                  </div>
                ))}
              </div>
            </section>

            <section className="card-flat p-5">
              <div className="flex items-center gap-2 mb-3"><Warning size={18} weight="duotone" color="#F59E0B" /><h3 className="font-semibold">2 Issues</h3></div>
              {(m.issues || []).length === 0 && <EmptyHint label="Generate the brief to surface 2 transparent issues with action plans." />}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {(m.issues || []).map((iss, i) => (
                  <div key={i} className="p-4 rounded-md border border-white/5 bg-white/[0.02]">
                    <div className="flex items-center justify-between"><div className="font-semibold text-sm">{iss.title}</div><span className={`chip ${sevChip(iss.severity)}`}>{iss.severity}</span></div>
                    <div className="text-xs text-slate-300 mt-1.5">{iss.description}</div>
                    {iss.action_plan && <div className="text-xs text-slate-300 mt-2 p-2 rounded bg-[#3FA9F5]/10 border border-[#3FA9F5]/15"><strong className="text-[#3FA9F5]">Action plan:</strong> {iss.action_plan}</div>}
                  </div>
                ))}
              </div>
            </section>

            <section className="card-flat p-5">
              <div className="flex items-center gap-2 mb-3"><Lightbulb size={18} weight="duotone" color="#3FA9F5" /><h3 className="font-semibold">Talking Points</h3></div>
              {(m.talking_points || []).length === 0 && <EmptyHint />}
              <ul className="space-y-2">{(m.talking_points || []).map((t, i) => <li key={i} className="text-sm"><strong className="text-white">{t.topic}:</strong> <span className="text-slate-300">{t.angle}</span></li>)}</ul>
            </section>

            <section className="card-flat p-5">
              <div className="flex items-center gap-2 mb-3"><Question size={18} weight="duotone" color="#818CF8" /><h3 className="font-semibold">Suggested Engagement Questions</h3></div>
              {(m.suggested_questions || []).length === 0 && <EmptyHint />}
              <ul className="space-y-2 list-disc pl-5">{(m.suggested_questions || []).map((q, i) => <li key={i} className="text-sm text-slate-300">{q}</li>)}</ul>
            </section>
          </div>

          <div className="space-y-5">
            <section className="card-flat p-5">
              <div className="flex items-center gap-2 mb-3"><Megaphone size={18} weight="duotone" color="#2FE0C2" /><h3 className="font-semibold">Testimonial Opportunity</h3></div>
              <div className="text-sm text-slate-300 leading-relaxed">{m.testimonial_opportunity || "—"}</div>
            </section>
            <section className="card-flat p-5">
              <div className="flex items-center gap-2 mb-3"><Sparkle size={18} weight="duotone" color="#3FA9F5" /><h3 className="font-semibold">Strategic Recommendations</h3></div>
              <ul className="space-y-2 list-disc pl-5">{(m.strategic_recommendations || []).map((r, i) => <li key={i} className="text-sm text-slate-300">{r}</li>)}</ul>
              {(m.strategic_recommendations || []).length === 0 && <EmptyHint />}
            </section>
            <section className="card-flat p-5">
              <div className="label mb-2">Health Signal</div>
              <div className="text-sm text-slate-300">{m.health_signal || "—"}</div>
              {m.brief_generated_at && <div className="mt-3 text-[11px] text-slate-500 mono">Brief generated · {new Date(m.brief_generated_at).toLocaleString()} · {m.brief_model}</div>}
            </section>
            <section className="card-flat p-5">
              <div className="label mb-2">KPI Snapshot (demo data)</div>
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
              <button className="btn-primary flex items-center gap-2" onClick={analyze} disabled={busy === "analyze" || !transcript.trim()} data-testid="analyze-transcript-btn">
                {busy === "analyze" ? <ArrowsClockwise size={14} className="animate-spin" /> : <Robot size={14} weight="duotone" />} Analyze with AI
              </button>
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
