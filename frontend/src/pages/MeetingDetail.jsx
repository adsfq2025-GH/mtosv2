import React, { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { meetings, aiModels, actionItems, contentCaptures, clients, roadmap, aiTerritory } from "../api";
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
  const kpiPaths = explain.kpi_paths || explain.kpiPaths || [];
  const observed = explain.observed_values || explain.observedValues || {};
  const confVal = typeof explain.confidence === "number"
    ? (explain.confidence <= 1 ? Math.round(explain.confidence * 100) : Math.round(explain.confidence))
    : null;
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
              <div className="mt-1">{confVal !== null ? `${confVal}%` : String(explain.confidence || "—")}</div>
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
          {!!(Array.isArray(kpiPaths) && kpiPaths.length) && (
            <div className="p-3 rounded-md border border-white/10 bg-white/[0.02]">
              <div className="text-xs text-white/60">KPI Evidence</div>
              <div className="mt-2 space-y-2">
                {kpiPaths.map((p) => (
                  <div key={String(p)} className="flex items-start justify-between gap-3">
                    <div className="mono text-[11px] text-slate-300 break-all">{String(p)}</div>
                    <div className="mono text-[11px] text-slate-400">
                      {Object.prototype.hasOwnProperty.call(observed, p) ? JSON.stringify(observed[p]) : "—"}
                    </div>
                  </div>
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
const prioChip = (p) => p === "high" ? "chip-danger" : p === "low" ? "chip-success" : "chip-warn";
const statusChip = (s) => s === "completed" ? "chip-success" : s === "blocked" ? "chip-danger" : s === "in_progress" ? "chip-info" : "chip-warn";

const _num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const _str = (v) => (v === null || v === undefined ? "" : String(v));
const _fmtDeltaPct = (v) => {
  const n = _num(v);
  if (n === null) return "";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n}%`;
};

function MetricLine({ label, cur, prev, delta }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5">
      <div className="text-sm text-slate-200">{label}</div>
      <div className="flex items-center gap-3 text-xs text-slate-300">
        <span className="chip !bg-white/5 !border-white/10">{_str(cur || "—")}</span>
        <span className="text-slate-500">vs</span>
        <span className="chip !bg-white/5 !border-white/10">{_str(prev || "—")}</span>
        {!!delta && <span className="chip !bg-[#3FA9F5]/10 !border-[#3FA9F5]/20 !text-[#9CCBFF]">{delta}</span>}
      </div>
    </div>
  );
}

function ReviewSection({ title, children }) {
  return (
    <div className="p-4 rounded-md border border-white/5 bg-white/[0.02]">
      <div className="font-semibold text-sm">{title}</div>
      <div className="mt-3 space-y-2">{children}</div>
    </div>
  );
}

function RoadmapAddDialog({ clientId, meetingId, week, onCreated }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ week, owner_type: "agency", create_action_item: true });
  useEffect(() => { setForm((p) => ({ ...p, week })); }, [week]);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <button className="btn-ghost" type="button">Add Roadmap Item</button>
      </DialogTrigger>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Add Roadmap Item</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <div className="label mb-1">Week</div>
              <input className="input" type="number" min={1} max={12} value={form.week || 1} onChange={(e) => setForm((p) => ({ ...p, week: Number(e.target.value || 1) }))} />
            </div>
            <div>
              <div className="label mb-1">Owner Type</div>
              <select className="input" value={form.owner_type || "agency"} onChange={(e) => setForm((p) => ({ ...p, owner_type: e.target.value }))}>
                <option value="agency">agency</option>
                <option value="client">client</option>
              </select>
            </div>
          </div>
          <div>
            <div className="label mb-1">Title</div>
            <input className="input" value={form.title || ""} onChange={(e) => setForm((p) => ({ ...p, title: e.target.value }))} placeholder="Example: Publish 3 new city pages" />
          </div>
          <div>
            <div className="label mb-1">Description</div>
            <textarea className="input !min-h-[90px]" value={form.description || ""} onChange={(e) => setForm((p) => ({ ...p, description: e.target.value }))} placeholder="What done looks like, requirements, links/assets…" />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div>
              <div className="label mb-1">Owner</div>
              <input className="input" value={form.owner || ""} onChange={(e) => setForm((p) => ({ ...p, owner: e.target.value }))} placeholder="SEO Dept / AM / Client" />
            </div>
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
          </div>
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <input type="checkbox" checked={!!form.create_action_item} onChange={(e) => setForm((p) => ({ ...p, create_action_item: e.target.checked }))} />
            Also create a linked action item (recommended)
          </div>
          <div className="flex items-center justify-end gap-2">
            <button className="btn-primary" type="button" onClick={async () => {
              if (!clientId || !form.title) return;
              await roadmap.addItem(clientId, { ...form, meeting_id: meetingId || null });
              setOpen(false);
              onCreated?.();
            }}>Create</button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export default function MeetingDetail() {
  const { id } = useParams();
  const [m, setM] = useState(null);
  const [client, setClient] = useState(null);
  const [intelScan, setIntelScan] = useState(null);
  const [intelEvents, setIntelEvents] = useState([]);
  const [intelShowSources, setIntelShowSources] = useState(false);
  const [intelErr, setIntelErr] = useState("");
  const [roadmapData, setRoadmapData] = useState(null);
  const [roadmapWeek, setRoadmapWeek] = useState(1);
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
  const [reviewsDraft, setReviewsDraft] = useState({});
  const [feedbackDraft, setFeedbackDraft] = useState({ lead_quality: 3, campaign_quality: 3, satisfaction: 3, results: 3, notes: "" });
  const [savingFeedback, setSavingFeedback] = useState(false);
  const [healthDraft, setHealthDraft] = useState({ nps_score: "", sentiment_classification: "", health_notes: "" });
  const [savingHealth, setSavingHealth] = useState(false);

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
      setReviewsDraft(meeting.deliverable_reviews || {});
      setHealthDraft({
        nps_score: meeting.nps_score === null || meeting.nps_score === undefined ? "" : String(meeting.nps_score),
        sentiment_classification: String(meeting.sentiment_classification || ""),
        health_notes: String(meeting.health_notes || ""),
      });
      if (meeting.feedback) {
        setFeedbackDraft({
          lead_quality: Number(meeting.feedback.lead_quality || 3),
          campaign_quality: Number(meeting.feedback.campaign_quality || 3),
          satisfaction: Number(meeting.feedback.satisfaction || 3),
          results: Number(meeting.feedback.results || 3),
          notes: meeting.feedback.notes || "",
        });
      }
      clients.get(meeting.client_id).then(setClient).catch(() => setClient(null));
      aiTerritory.latest(meeting.client_id).then((r) => {
        setIntelScan(r?.scan || null);
        setIntelEvents(r?.events || []);
        setIntelErr("");
      }).catch(() => {
        setIntelScan(null);
        setIntelEvents([]);
        setIntelErr("AI & Territory Intelligence data not available.");
      });
      roadmap.get(meeting.client_id).then((r) => {
        setRoadmapData(r);
        const cw = Number(r?.current_week || 1) || 1;
        setRoadmapWeek(cw);
      }).catch(() => setRoadmapData(null));
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

  const runIntelNow = async () => {
    if (!m?.client_id) return;
    setBusy("intel");
    setIntelErr("");
    try {
      await aiTerritory.runNow(m.client_id);
      const r = await aiTerritory.latest(m.client_id);
      setIntelScan(r?.scan || null);
      setIntelEvents(r?.events || []);
    } catch (e) {
      const raw = e?.response?.data;
      const detail = typeof raw === "string" ? raw : raw?.detail;
      const msg = String(detail || "AI & Territory Intelligence scan failed");
      setIntelErr(msg);
    } finally {
      setBusy("");
    }
  };

  const intelConf = intelScan?.data_confidence && typeof intelScan.data_confidence === "object" ? intelScan.data_confidence : null;
  const intelConfPct = typeof intelConf?.percent === "number" ? intelConf.percent : null;
  const intelConfLevel = typeof intelConf?.level === "string" ? intelConf.level : "";
  const intelAvail = intelConf?.availability && typeof intelConf.availability === "object" ? intelConf.availability : {};
  const intelHasData = !!intelScan && (Number(intelScan?.total || 0) > 0 || Number(intelScan?.prompts_total || 0) > 0);
  const intelSovItems = Array.isArray(intelScan?.share_of_voice?.items) ? intelScan.share_of_voice.items : [];
  const intelClientSov = intelSovItems.find((x) => x?.is_client) || null;
  const intelTerritoryCovered = Array.isArray(intelScan?.territory_intelligence?.covered_markets) ? intelScan.territory_intelligence.covered_markets : [];
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

  const isAdsClient = (() => {
    const ss = (client?.services || []).map((s) => String(s || "").toLowerCase());
    return ss.some((s) => s.includes("google ads") || s.includes("meta") || s.includes("facebook") || s.includes("instagram") || s.includes("paid ads"));
  })();
  const feedbackComplete = (() => {
    const f = m?.feedback || null;
    if (!f) return false;
    const vals = [f.lead_quality, f.campaign_quality, f.satisfaction, f.results];
    return vals.every((v) => typeof v === "number" && v >= 1 && v <= 5);
  })();

  const saveFeedback = async () => {
    setSavingFeedback(true);
    try {
      const payload = {
        lead_quality: Number(feedbackDraft.lead_quality || 0),
        campaign_quality: Number(feedbackDraft.campaign_quality || 0),
        satisfaction: Number(feedbackDraft.satisfaction || 0),
        results: Number(feedbackDraft.results || 0),
        notes: feedbackDraft.notes || "",
      };
      const updated = await meetings.update(id, { feedback: payload });
      setM(updated);
      await reload().catch(() => {});
    } catch (e) {
      alert(e?.response?.data?.detail || "Failed to save feedback");
    } finally {
      setSavingFeedback(false);
    }
  };

  const saveHealth = async () => {
    setSavingHealth(true);
    try {
      const nps = healthDraft.nps_score === "" ? null : Number(healthDraft.nps_score || 0);
      const sentiment = String(healthDraft.sentiment_classification || "").trim() || null;
      const notes = String(healthDraft.health_notes || "").trim();
      const updated = await meetings.update(id, {
        nps_score: nps,
        sentiment_classification: sentiment,
        health_notes: notes ? notes : null,
      });
      setM(updated);
      await reload().catch(() => {});
    } catch (e) {
      alert(e?.response?.data?.detail || "Failed to save client health");
    } finally {
      setSavingHealth(false);
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

  const setReviewNote = (deliverableKey, sectionKey, value) => {
    setReviewsDraft((prev) => {
      const next = { ...(prev || {}) };
      const d = { ...(next[deliverableKey] || {}) };
      const sections = { ...(d.sections || {}) };
      sections[sectionKey] = value;
      d.sections = sections;
      next[deliverableKey] = d;
      return next;
    });
  };

  const saveReviews = async () => {
    setBusy("save_reviews");
    try {
      const updated = await meetings.update(id, { deliverable_reviews: reviewsDraft });
      setM(updated);
      setReviewsDraft(updated.deliverable_reviews || {});
    } catch (e) {
      alert(e?.response?.data?.detail || "Failed to save deliverable reviews");
    } finally {
      setBusy("");
    }
  };

  const refreshRoadmap = async () => {
    if (!m?.client_id) return;
    const r = await roadmap.get(m.client_id);
    setRoadmapData(r);
    if (!roadmapWeek) setRoadmapWeek(Number(r?.current_week || 1) || 1);
  };

  const setRoadmapStatus = async (itemId, status) => {
    if (!m?.client_id) return;
    setBusy(`roadmap_${itemId}`);
    try {
      await roadmap.patchItem(m.client_id, itemId, { status });
      await refreshRoadmap();
    } finally {
      setBusy("");
    }
  };

  const CHECKLIST_ITEMS = [
    ["wins", "Review wins"],
    ["issues", "Review issues & next steps"],
    ["progress", "Campaign progress reviewed"],
    ["strategic", "Share one clear recommendation"],
    ["client_voice", "Open-ended client questions asked"],
    ["testimonial", "Testimonial / content opportunity assessed"],
    ["next30", "Next 30 days plan agreed"],
    ["actions", "Named action items with owners + dates"],
    ["nextmeeting", "Next meeting date confirmed"],
    ["sentiment", "Log client sentiment"],
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
          { k: "reviews", label: "Reviews", icon: Megaphone },
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

      {/* REVIEWS TAB */}
      {tab === "reviews" && (
        <div className="space-y-5">
          <div className="card-flat p-5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="font-semibold">Deliverable Reviews</div>
                <div className="text-xs text-slate-400 mt-1">
                  Structured review sections per deliverable. Save notes so the meeting review is repeatable and consistent.
                </div>
              </div>
              <button className="btn-primary" onClick={saveReviews} disabled={busy === "save_reviews"} type="button">
                {busy === "save_reviews" ? "Saving…" : "Save Review Notes"}
              </button>
            </div>
          </div>

          <div className="card-flat p-5">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="font-semibold flex items-center gap-2">
                  <Clock size={16} weight="duotone" /> 12-Week Roadmap
                </div>
                <div className="text-xs text-slate-400 mt-1">
                  Current week, completion %, pending and overdue items. Roadmap items can create linked action items for accountability.
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <Link to={`/follow-up?client_id=${encodeURIComponent(m.client_id)}`} className="btn-ghost">Open Follow-Up</Link>
                <RoadmapAddDialog clientId={m.client_id} meetingId={m.id} week={roadmapWeek} onCreated={refreshRoadmap} />
              </div>
            </div>

            {!roadmapData && <div className="text-sm text-slate-500 mt-4">Loading roadmap…</div>}
            {!!roadmapData && (
              <div className="mt-4 space-y-4">
                <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                  <div className="p-3 rounded-md border border-white/5 bg-white/[0.02]">
                    <div className="text-xs text-slate-400">Current Week</div>
                    <div className="text-xl font-bold mt-1">{roadmapData.current_week || 1}/12</div>
                  </div>
                  <div className="p-3 rounded-md border border-white/5 bg-white/[0.02]">
                    <div className="text-xs text-slate-400">Completed</div>
                    <div className="text-xl font-bold mt-1">{roadmapData.counts?.completed_items || 0}</div>
                  </div>
                  <div className="p-3 rounded-md border border-white/5 bg-white/[0.02]">
                    <div className="text-xs text-slate-400">Pending</div>
                    <div className="text-xl font-bold mt-1">{roadmapData.counts?.pending_items || 0}</div>
                  </div>
                  <div className="p-3 rounded-md border border-white/5 bg-white/[0.02]">
                    <div className="text-xs text-slate-400">Overdue</div>
                    <div className="text-xl font-bold mt-1">{roadmapData.counts?.overdue_items || 0}</div>
                  </div>
                  <div className="p-3 rounded-md border border-white/5 bg-white/[0.02]">
                    <div className="text-xs text-slate-400">Completion</div>
                    <div className="text-xl font-bold mt-1">{roadmapData.counts?.completion_percentage || 0}%</div>
                  </div>
                </div>

                <div className="w-full h-2 rounded-full bg-white/5 overflow-hidden">
                  <div className="h-2 bg-[#3FA9F5]" style={{ width: `${roadmapData.counts?.completion_percentage || 0}%` }} />
                </div>

                <div className="flex flex-wrap gap-2">
                  {Array.from({ length: 12 }).map((_, i) => {
                    const w = i + 1;
                    const isCurrent = w === (roadmapData.current_week || 1);
                    const isSelected = w === roadmapWeek;
                    const cls = isSelected ? "chip chip-info" : isCurrent ? "chip chip-warn" : "chip chip-muted";
                    return (
                      <button key={w} type="button" className={cls} onClick={() => setRoadmapWeek(w)}>
                        Week {w}
                      </button>
                    );
                  })}
                </div>

                {(() => {
                  const items = roadmapData.items || [];
                  const weekItems = items.filter((it) => Number(it.week || 0) === Number(roadmapWeek || 1));
                  const overdueItems = items.filter((it) => !!it.due_date && it.due_date < (roadmapData.today || "") && it.status !== "completed");
                  const shown = [...overdueItems.slice(0, 5), ...weekItems].slice(0, 25);
                  return (
                    <div className="space-y-2">
                      {shown.length === 0 && <div className="text-sm text-slate-500 py-4 text-center">No roadmap items for this week yet.</div>}
                      {shown.map((it) => (
                        <div key={it.id} className={`p-4 rounded-md border border-white/5 bg-white/[0.02] flex items-start justify-between gap-3 ${busy === `roadmap_${it.id}` ? "opacity-60 pointer-events-none" : ""}`}>
                          <div className="min-w-0">
                            <div className="flex items-center gap-2">
                              <div className="text-sm font-medium truncate">{it.title}</div>
                              <span className={`chip ${prioChip(it.priority)}`}>{it.priority}</span>
                              {it.due_date && it.due_date < (roadmapData.today || "") && it.status !== "completed" && <span className="chip chip-danger">overdue</span>}
                              <span className="chip chip-muted">Week {it.week}</span>
                            </div>
                            {it.description && <div className="text-xs text-slate-400 mt-1">{it.description}</div>}
                            <div className="text-[11px] text-slate-500 mt-1 mono">{it.owner_type} · {it.owner || "—"} · due {it.due_date || "TBD"}</div>
                          </div>
                          <div className="flex items-center gap-1 shrink-0">
                            <button className="btn-ghost !p-2" type="button" title="In progress" onClick={() => setRoadmapStatus(it.id, "in_progress")}><Clock size={14} /></button>
                            <button className="btn-ghost !p-2" type="button" title="Complete" onClick={() => setRoadmapStatus(it.id, "completed")}><CheckCircle size={14} /></button>
                            <span className={`chip ${statusChip(it.status)}`}>{it.status}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  );
                })()}
              </div>
            )}
          </div>

          {(() => {
            const services = (client?.services || []).map((s) => String(s || "").toLowerCase());
            const showSeo = !client || services.some((s) => s.includes("seo"));
            const showGbp = !client || services.some((s) => s.includes("gbp") || s.includes("google business"));
            const showGads = !client || services.some((s) => s.includes("google ads") || s.includes("ppc"));
            const showMeta = !client || services.some((s) => s.includes("meta") || s.includes("facebook") || s.includes("instagram"));

            const kpi = m?.kpi_snapshot || {};
            const gbp = kpi.google_business_profile || {};
            const map = kpi.map_checkins || {};
            const gsc = kpi.google_search_console || {};
            const ga = kpi.google_analytics || {};
            const ahrefs = kpi.ahrefs || {};
            const gads = kpi.google_ads || {};
            const meta = kpi.meta_ads || {};
            const clickup = kpi.clickup || {};

            return (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
                {showSeo && (
                  <section className="card-flat p-5">
                    <div className="flex items-center justify-between mb-4">
                      <div className="flex items-center gap-2"><Lightbulb size={18} weight="duotone" color="#2FE0C2" /><h3 className="font-semibold">SEO Review</h3></div>
                      <span className="chip">SEO</span>
                    </div>
                    <div className="space-y-3">
                      <ReviewSection title="SEO Structure">
                        <div className="text-xs text-slate-400">{_str(ahrefs.competitor_gap || "—")}</div>
                        <textarea className="input !min-h-[90px]" value={reviewsDraft?.seo?.sections?.seo_structure || ""} onChange={(e) => setReviewNote("seo", "seo_structure", e.target.value)} placeholder="Notes: site architecture, service pages, city pages, schema, internal linking, technical blockers…" />
                      </ReviewSection>
                      <ReviewSection title="Rankings">
                        <MetricLine label="Avg Grid Rank" cur={map?.avg_grid_rank?.value} prev={map?.avg_grid_rank?.previous} delta={_str(map?.avg_grid_rank?.delta)} />
                        <MetricLine label="Top 3 %" cur={_str(map?.top_3_pct?.value)} prev={_str(map?.top_3_pct?.previous)} delta={_fmtDeltaPct(map?.top_3_pct?.delta_pct)} />
                        <MetricLine label="Keywords Improved" cur={map?.keywords_improved} prev="" delta="" />
                        <MetricLine label="Keywords Dropped" cur={map?.keywords_dropped} prev="" delta="" />
                        <textarea className="input !min-h-[90px]" value={reviewsDraft?.seo?.sections?.rankings || ""} onChange={(e) => setReviewNote("seo", "rankings", e.target.value)} placeholder="Notes: keyword clusters, grid wins/losses, competitor movement, next ranking push…" />
                      </ReviewSection>
                      <ReviewSection title="Traffic">
                        <MetricLine label="GSC Impressions" cur={gsc?.impressions?.value} prev="" delta={_fmtDeltaPct(gsc?.impressions?.delta_pct)} />
                        <MetricLine label="GSC Clicks" cur={gsc?.clicks?.value} prev="" delta={_fmtDeltaPct(gsc?.clicks?.delta_pct)} />
                        <MetricLine label="GA Sessions" cur={ga?.sessions?.value} prev="" delta={_fmtDeltaPct(ga?.sessions?.delta_pct)} />
                        <MetricLine label="GA Conversions" cur={ga?.conversions?.value} prev="" delta={_fmtDeltaPct(ga?.conversions?.delta_pct)} />
                        <textarea className="input !min-h-[90px]" value={reviewsDraft?.seo?.sections?.traffic || ""} onChange={(e) => setReviewNote("seo", "traffic", e.target.value)} placeholder="Notes: traffic quality, conversion drivers, landing pages, CTA issues, form/call tracking…" />
                      </ReviewSection>
                      <ReviewSection title="Check-ins">
                        <MetricLine label="Field Check-ins" cur={map?.field_checkins} prev="" delta="" />
                        <textarea className="input !min-h-[70px]" value={reviewsDraft?.seo?.sections?.checkins || ""} onChange={(e) => setReviewNote("seo", "checkins", e.target.value)} placeholder="Notes: check-in cadence, grid coverage, location factors…" />
                      </ReviewSection>
                      <ReviewSection title="Reviews">
                        <MetricLine label="New Reviews" cur={gbp?.new_reviews?.value} prev="" delta="" />
                        <MetricLine label="Avg Rating" cur={gbp?.new_reviews?.avg_rating} prev="" delta="" />
                        <textarea className="input !min-h-[70px]" value={reviewsDraft?.seo?.sections?.reviews || ""} onChange={(e) => setReviewNote("seo", "reviews", e.target.value)} placeholder="Notes: review velocity, response %, ask process, QR/follow-up plan…" />
                      </ReviewSection>
                      <ReviewSection title="Roadmap Progress">
                        <div className="text-xs text-slate-400">ClickUp completed (30d): {_str(clickup?.tasks_completed_last_30d || "—")} · Overdue: {_str(clickup?.overdue || "—")} · Blocked: {_str(clickup?.blocked || "—")}</div>
                        <textarea className="input !min-h-[90px]" value={reviewsDraft?.seo?.sections?.roadmap_progress || ""} onChange={(e) => setReviewNote("seo", "roadmap_progress", e.target.value)} placeholder="Notes: 12-week roadmap progress, what shipped, what’s blocked, what’s next…" />
                      </ReviewSection>
                      <ReviewSection title="Tasks">
                        <div className="text-xs text-slate-400">Open action items in this meeting: {_str((actions || []).filter((x) => x.status !== "completed").length)}</div>
                        <textarea className="input !min-h-[90px]" value={reviewsDraft?.seo?.sections?.tasks || ""} onChange={(e) => setReviewNote("seo", "tasks", e.target.value)} placeholder="Notes: key tasks, owners, due dates, approvals needed…" />
                      </ReviewSection>
                    </div>
                  </section>
                )}

                {showGads && (
                  <section className="card-flat p-5">
                    <div className="flex items-center justify-between mb-4">
                      <div className="flex items-center gap-2"><Megaphone size={18} weight="duotone" color="#3FA9F5" /><h3 className="font-semibold">Google Ads Review</h3></div>
                      <span className="chip">Google Ads</span>
                    </div>
                    <div className="space-y-3">
                      <ReviewSection title="Campaign Structure">
                        <div className="text-xs text-slate-400">{_str(gads?.issue || "—")}</div>
                        <textarea className="input !min-h-[90px]" value={reviewsDraft?.google_ads?.sections?.campaign_structure || ""} onChange={(e) => setReviewNote("google_ads", "campaign_structure", e.target.value)} placeholder="Notes: campaign/ad group structure, keyword match types, negatives, geo, schedule, tracking…" />
                      </ReviewSection>
                      <ReviewSection title="Spend">
                        <MetricLine label="Spend" cur={gads?.spend?.value} prev="" delta={_fmtDeltaPct(gads?.spend?.delta_pct)} />
                        <textarea className="input !min-h-[70px]" value={reviewsDraft?.google_ads?.sections?.spend || ""} onChange={(e) => setReviewNote("google_ads", "spend", e.target.value)} placeholder="Notes: pacing, budget shifts, wasted spend, opportunities…" />
                      </ReviewSection>
                      <ReviewSection title="Leads">
                        <MetricLine label="Leads" cur={gads?.leads?.value} prev="" delta={_fmtDeltaPct(gads?.leads?.delta_pct)} />
                        <MetricLine label="Qualified Leads" cur={gads?.qualified_leads} prev="" delta="" />
                        <textarea className="input !min-h-[70px]" value={reviewsDraft?.google_ads?.sections?.leads || ""} onChange={(e) => setReviewNote("google_ads", "leads", e.target.value)} placeholder="Notes: lead mix, quality, attribution gaps, follow-up workflow…" />
                      </ReviewSection>
                      <ReviewSection title="Cost Per Lead">
                        <MetricLine label="CPL" cur={gads?.cpl?.value} prev={gads?.cpl?.previous} delta={_str(gads?.cpl?.trend || "")} />
                        <textarea className="input !min-h-[70px]" value={reviewsDraft?.google_ads?.sections?.cpl || ""} onChange={(e) => setReviewNote("google_ads", "cpl", e.target.value)} placeholder="Notes: CPL drivers, keyword pruning, landing page fixes, offer alignment…" />
                      </ReviewSection>
                      <ReviewSection title="Conversion Rate">
                        <textarea className="input !min-h-[90px]" value={reviewsDraft?.google_ads?.sections?.conversion_rate || ""} onChange={(e) => setReviewNote("google_ads", "conversion_rate", e.target.value)} placeholder="Notes: conversion rate, tracking integrity, landing page performance…" />
                      </ReviewSection>
                      <ReviewSection title="Call Quality">
                        <textarea className="input !min-h-[90px]" value={reviewsDraft?.google_ads?.sections?.call_quality || ""} onChange={(e) => setReviewNote("google_ads", "call_quality", e.target.value)} placeholder="Notes: call recordings findings, missed calls, lead handling, sales bottlenecks…" />
                      </ReviewSection>
                      <ReviewSection title="Offer Performance">
                        <textarea className="input !min-h-[90px]" value={reviewsDraft?.google_ads?.sections?.offer_performance || ""} onChange={(e) => setReviewNote("google_ads", "offer_performance", e.target.value)} placeholder="Notes: which offer/angle is winning, ad copy tests, extensions, promos…" />
                      </ReviewSection>
                      <ReviewSection title="Missing Offers">
                        <textarea className="input !min-h-[90px]" value={reviewsDraft?.google_ads?.sections?.missing_offers || ""} onChange={(e) => setReviewNote("google_ads", "missing_offers", e.target.value)} placeholder="Notes: missing offers, seasonal promos, upsells, service bundles to test…" />
                      </ReviewSection>
                    </div>
                  </section>
                )}

                {showMeta && (
                  <section className="card-flat p-5">
                    <div className="flex items-center justify-between mb-4">
                      <div className="flex items-center gap-2"><Robot size={18} weight="duotone" color="#818CF8" /><h3 className="font-semibold">Meta Ads Review</h3></div>
                      <span className="chip">Meta</span>
                    </div>
                    <div className="space-y-3">
                      <ReviewSection title="Reach">
                        <textarea className="input !min-h-[90px]" value={reviewsDraft?.meta_ads?.sections?.reach || ""} onChange={(e) => setReviewNote("meta_ads", "reach", e.target.value)} placeholder="Notes: reach, frequency, audience saturation, expansion opportunities…" />
                      </ReviewSection>
                      <ReviewSection title="Leads">
                        <MetricLine label="Leads" cur={meta?.leads?.value} prev="" delta={_fmtDeltaPct(meta?.leads?.delta_pct)} />
                        <textarea className="input !min-h-[70px]" value={reviewsDraft?.meta_ads?.sections?.leads || ""} onChange={(e) => setReviewNote("meta_ads", "leads", e.target.value)} placeholder="Notes: lead quality, lead form vs landing page, follow-up speed…" />
                      </ReviewSection>
                      <ReviewSection title="Cost Per Lead">
                        <MetricLine label="CPL" cur={meta?.cpl?.value} prev={meta?.cpl?.previous} delta="" />
                        <textarea className="input !min-h-[70px]" value={reviewsDraft?.meta_ads?.sections?.cpl || ""} onChange={(e) => setReviewNote("meta_ads", "cpl", e.target.value)} placeholder="Notes: CPL drivers, creative fatigue, audience refinement…" />
                      </ReviewSection>
                      <ReviewSection title="Creative Performance">
                        <div className="text-xs text-slate-400">{_str(meta?.top_creative || "—")}</div>
                        <textarea className="input !min-h-[90px]" value={reviewsDraft?.meta_ads?.sections?.creative_performance || ""} onChange={(e) => setReviewNote("meta_ads", "creative_performance", e.target.value)} placeholder="Notes: top creatives, hooks, UGC needs, next tests…" />
                      </ReviewSection>
                      <ReviewSection title="Offer Performance">
                        <textarea className="input !min-h-[90px]" value={reviewsDraft?.meta_ads?.sections?.offer_performance || ""} onChange={(e) => setReviewNote("meta_ads", "offer_performance", e.target.value)} placeholder="Notes: best performing offers, promo ideas, message-market fit…" />
                      </ReviewSection>
                    </div>
                  </section>
                )}

                {showGbp && (
                  <section className="card-flat p-5">
                    <div className="flex items-center justify-between mb-4">
                      <div className="flex items-center gap-2"><Trophy size={18} weight="duotone" color="#F59E0B" /><h3 className="font-semibold">GBP Review</h3></div>
                      <span className="chip">GBP</span>
                    </div>
                    <div className="space-y-3">
                      <ReviewSection title="Calls">
                        <MetricLine label="Calls" cur={gbp?.calls?.value} prev="" delta={_fmtDeltaPct(gbp?.calls?.delta_pct)} />
                        <textarea className="input !min-h-[70px]" value={reviewsDraft?.gbp?.sections?.calls || ""} onChange={(e) => setReviewNote("gbp", "calls", e.target.value)} placeholder="Notes: call volume drivers, missed calls, tracking, next levers…" />
                      </ReviewSection>
                      <ReviewSection title="Direction Requests">
                        <MetricLine label="Directions" cur={gbp?.direction_requests?.value} prev="" delta={_fmtDeltaPct(gbp?.direction_requests?.delta_pct)} />
                        <textarea className="input !min-h-[70px]" value={reviewsDraft?.gbp?.sections?.direction_requests || ""} onChange={(e) => setReviewNote("gbp", "direction_requests", e.target.value)} placeholder="Notes: service area alignment, proximity signals, location relevance…" />
                      </ReviewSection>
                      <ReviewSection title="Views">
                        <MetricLine label="Photo Views" cur={gbp?.photo_views?.value} prev="" delta={_fmtDeltaPct(gbp?.photo_views?.delta_pct)} />
                        <MetricLine label="Website Clicks" cur={gbp?.website_clicks?.value} prev="" delta={_fmtDeltaPct(gbp?.website_clicks?.delta_pct)} />
                        <textarea className="input !min-h-[70px]" value={reviewsDraft?.gbp?.sections?.views || ""} onChange={(e) => setReviewNote("gbp", "views", e.target.value)} placeholder="Notes: photo/post cadence, CTR, profile completeness, next actions…" />
                      </ReviewSection>
                      <ReviewSection title="Check-ins">
                        <MetricLine label="Field Check-ins" cur={map?.field_checkins} prev="" delta="" />
                        <textarea className="input !min-h-[70px]" value={reviewsDraft?.gbp?.sections?.checkins || ""} onChange={(e) => setReviewNote("gbp", "checkins", e.target.value)} placeholder="Notes: check-in strategy and coverage…" />
                      </ReviewSection>
                      <ReviewSection title="Reviews">
                        <MetricLine label="New Reviews" cur={gbp?.new_reviews?.value} prev="" delta="" />
                        <MetricLine label="Avg Rating" cur={gbp?.new_reviews?.avg_rating} prev="" delta="" />
                        <textarea className="input !min-h-[90px]" value={reviewsDraft?.gbp?.sections?.reviews || ""} onChange={(e) => setReviewNote("gbp", "reviews", e.target.value)} placeholder="Notes: review requests, review response quality, velocity plan…" />
                      </ReviewSection>
                    </div>
                  </section>
                )}
              </div>
            );
          })()}
        </div>
      )}

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
                    {(iss.solutions || []).length > 0 && (
                      <div className="mt-2 p-2 rounded bg-[#2FE0C2]/5 border border-[#2FE0C2]/15">
                        <div className="text-[11px] mono text-[#2FE0C2] uppercase tracking-wider">Solutions</div>
                        <ul className="mt-2 space-y-1 list-disc pl-5">
                          {(iss.solutions || []).map((s, idx) => (
                            <li key={idx} className="text-xs text-slate-300">{s}</li>
                          ))}
                        </ul>
                      </div>
                    )}
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
              <div className="flex items-center justify-between gap-3 mb-3">
                <div className="flex items-center gap-2"><Robot size={18} weight="duotone" color="#3FA9F5" /><h3 className="font-semibold">AI &amp; Territory Intelligence</h3></div>
                <div className="flex items-center gap-3">
                  <div className="text-xs text-slate-400">
                    {intelScan?.created_at ? `Last scan: ${new Date(intelScan.created_at).toLocaleString()}` : "No scans yet"}
                    {intelConfPct !== null ? ` · Confidence: ${intelConfLevel ? `${intelConfLevel} ` : ""}(${intelConfPct}%)` : ""}
                  </div>
                  <button
                    className="chip !px-2 !py-1 !bg-white/5 !border-white/10 hover:!bg-white/10"
                    type="button"
                    onClick={() => setIntelShowSources((v) => !v)}
                    aria-label="AI intelligence sources"
                  >
                    <Info size={14} weight="duotone" />
                  </button>
                  <button className="btn-ghost" type="button" onClick={runIntelNow} disabled={busy === "intel"}>
                    {busy === "intel" ? "Scanning…" : "Run now"}
                  </button>
                </div>
              </div>
              {!!intelErr && (
                <div className="mb-3 p-3 rounded-md border border-[#F59E0B]/25 bg-[#F59E0B]/10 text-xs text-slate-200 flex items-start gap-2">
                  <Warning size={16} weight="duotone" color="#F59E0B" />
                  <div className="min-w-0">
                    <div className="font-semibold">Data Not Available</div>
                    <div className="text-slate-200/80 mt-1">{intelErr}</div>
                  </div>
                </div>
              )}
              {!!intelShowSources && (
                <div className="mb-4 p-4 rounded-md border border-white/10 bg-white/[0.02]">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-xs text-slate-400">Source Transparency</div>
                      <div className="text-sm text-slate-200 mt-1">
                        {intelConfPct !== null ? `Confidence: ${intelConfLevel || "—"} (${intelConfPct}%)` : "Confidence: Data Not Available"}
                      </div>
                    </div>
                    <button className="btn-ghost !py-1 !px-2 !text-xs" type="button" onClick={() => setIntelShowSources(false)}>Close</button>
                  </div>
                  <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div className="p-3 rounded-md border border-white/10 bg-white/[0.02]">
                      <div className="text-xs text-slate-400 mb-2">Sources Used</div>
                      <div className="space-y-1 text-sm">
                        {[
                          { k: "google_business_profile", label: "Google Business Profile" },
                          { k: "website", label: "Website" },
                          { k: "search_console", label: "Search Console" },
                          { k: "competitors", label: "Competitor Analysis" },
                          { k: "citations", label: "Citation Data" },
                        ].map((row) => {
                          const obj = intelAvail?.[row.k] || {};
                          const ok = !!obj.ok;
                          const extra =
                            row.k === "google_business_profile"
                              ? (!obj.binding ? "Not connected (missing GBP binding)" : obj.error ? `Not connected (${String(obj.error)})` : ok ? "Connected" : "Not connected")
                              : ok ? "Connected" : "Not connected";
                          return (
                            <div key={row.k} className="flex items-start justify-between gap-3">
                              <div className="min-w-0 text-slate-200">{ok ? "✓" : "✕"} {row.label}</div>
                              <div className="text-xs text-slate-400 text-right">{extra}</div>
                            </div>
                          );
                        })}
                        {!intelScan && <div className="text-xs text-slate-400 mt-2">Run a scan to validate source availability and compute confidence.</div>}
                      </div>
                    </div>
                    <div className="p-3 rounded-md border border-white/10 bg-white/[0.02]">
                      <div className="text-xs text-slate-400 mb-2">Validation</div>
                      <div className="text-sm text-slate-200">
                        {intelHasData ? "Verified prompts were generated from connected client data (GBP → Website → Search Console)." : "Data Not Available: no verified prompt set was available for this client."}
                      </div>
                      <div className="text-xs text-slate-400 mt-2">
                        Visibility score = hit_rate (brand/domain mentioned) across provider responses. Territory score = location-intent hit_rate grouped by verified territories.
                      </div>
                      {!!intelScan && typeof intelScan?.providers === "object" && (
                        <div className="mt-3">
                          <div className="text-xs text-slate-400 mb-2">Providers</div>
                          <div className="space-y-1 text-xs text-slate-200">
                            {Object.entries(intelScan.providers || {}).map(([p, v]) => (
                              <div key={p} className="flex items-center justify-between gap-3">
                                <div className="mono">{p}</div>
                                <div className="mono text-slate-400">
                                  {Number(v?.hits || 0)}/{Number(v?.total || 0)} hits{Number(v?.errors || 0) ? ` · ${Number(v.errors)} errors` : ""}
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}
              {!intelScan && (
                <EmptyHint label="Daily scans track AI visibility and territory coverage. Run now to generate the latest intelligence for this client." />
              )}
              {!!intelScan && (
                <div className="space-y-4">
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    <div className="p-4 rounded-md border border-white/5 bg-white/[0.02]">
                      <div className="text-xs text-slate-400">AI Visibility Score</div>
                      <div className="text-2xl font-bold mt-1">{intelHasData ? `${Number(intelScan.overall_visibility_score || 0).toFixed(1)}%` : "Data Not Available"}</div>
                      {!!intelScan?.growth_engine?.delta?.visibility_score && (
                        <div className="text-xs text-slate-400 mt-1">Change: {Number(intelScan.growth_engine.delta.visibility_score).toFixed(1)} pts</div>
                      )}
                    </div>
                    <div className="p-4 rounded-md border border-white/5 bg-white/[0.02]">
                      <div className="text-xs text-slate-400">AI Share of Voice</div>
                      <div className="text-2xl font-bold mt-1">
                        {intelHasData && intelClientSov ? `${Math.round(Number(intelClientSov?.share || 0) * 100)}%` : "Data Not Available"}
                      </div>
                      <div className="text-xs text-slate-400 mt-1">Market rank: {intelScan?.share_of_voice?.market_rank || "—"}</div>
                    </div>
                    <div className="p-4 rounded-md border border-white/5 bg-white/[0.02]">
                      <div className="text-xs text-slate-400">Territory Expansion Score</div>
                      <div className="text-2xl font-bold mt-1">{intelHasData && intelTerritoryCovered.length ? `${Number(intelScan?.territory_intelligence?.territory_expansion_score || 0).toFixed(1)}%` : "Data Not Available"}</div>
                      <div className="text-xs text-slate-400 mt-1">
                        Strong: {(intelScan?.territory_intelligence?.strong_markets || []).length} · Emerging: {(intelScan?.territory_intelligence?.emerging_markets || []).length} · Weak: {(intelScan?.territory_intelligence?.weak_markets || []).length}
                      </div>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div className="p-4 rounded-md border border-white/5 bg-white/[0.02]">
                      <div className="text-xs text-slate-400 mb-2">Top Competitors (AI mentions)</div>
                      <div className="space-y-2">
                        {(intelScan?.competitors || []).slice(0, 6).map((c, idx) => (
                          <div key={idx} className="flex items-center justify-between gap-3">
                            <div className="text-sm text-slate-200 truncate">{c?.name || c?.domain || "—"}</div>
                            <div className="text-xs text-slate-400 mono">{c?.mentions || 0}</div>
                          </div>
                        ))}
                        {(intelScan?.competitors || []).length === 0 && (
                          <div className="text-xs text-slate-400">{intelHasData ? "No competitor mentions detected." : "Data Not Available"}</div>
                        )}
                      </div>
                    </div>
                    <div className="p-4 rounded-md border border-white/5 bg-white/[0.02]">
                      <div className="text-xs text-slate-400 mb-2">Expansion Opportunities</div>
                      <div className="space-y-2">
                        {(intelScan?.territory_intelligence?.expansion_opportunities || []).slice(0, 6).map((o, idx) => (
                          <div key={idx} className="p-3 rounded border border-white/5 bg-white/[0.02]">
                            <div className="flex items-center justify-between gap-3">
                              <div className="text-sm font-medium text-slate-200">{o?.territory || "—"}</div>
                              <span className="chip chip-warn">{Number(o?.current_visibility_score || 0).toFixed(0)}%</span>
                            </div>
                            <div className="text-xs text-slate-400 mt-1">Estimated gain: +{Number(o?.estimated_visibility_gain || 0).toFixed(0)} pts</div>
                            {!!o?.why && <div className="text-xs text-slate-400 mt-1">Why: {String(o.why)}</div>}
                          </div>
                        ))}
                        {(intelScan?.territory_intelligence?.expansion_opportunities || []).length === 0 && (
                          <div className="text-xs text-slate-400">{intelHasData ? "No expansion opportunities detected." : "Data Not Available"}</div>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="p-4 rounded-md border border-white/5 bg-white/[0.02]">
                    <div className="text-xs text-slate-400 mb-2">What changed (latest)</div>
                    {(intelEvents || []).slice(0, 6).map((e, idx) => (
                      <div key={idx} className={`p-3 rounded border border-white/5 bg-white/[0.02] ${idx ? "mt-2" : ""}`}>
                        <div className="flex items-center justify-between gap-3">
                          <div className="text-sm font-semibold text-slate-200">{e?.title || "Update"}</div>
                          <span className={`chip ${e?.kind === "issue" ? "chip-danger" : e?.kind === "win" ? "chip-success" : e?.kind === "opportunity" ? "chip-info" : "chip-warn"}`}>{e?.kind || "alert"}</span>
                        </div>
                        {!!e?.description && <div className="text-xs text-slate-300 mt-1.5">{e.description}</div>}
                      </div>
                    ))}
                    {(intelEvents || []).length === 0 && (
                      <div className="text-xs text-slate-400">{intelHasData ? "No recent changes detected." : "Data Not Available"}</div>
                    )}
                  </div>
                </div>
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
              <div className="flex items-center justify-between gap-3 mb-3">
                <div className="flex items-center gap-2"><Question size={18} weight="duotone" color="#F59E0B" /><h3 className="font-semibold">Discovery Questions</h3></div>
                <button className="btn-ghost" type="button" onClick={async () => {
                  setBusy("discovery");
                  try {
                    const res = await meetings.generateDiscovery(id);
                    setM(res.meeting);
                  } catch (e) {
                    alert(e?.response?.data?.detail || "Failed to generate discovery questions");
                  } finally {
                    setBusy("");
                  }
                }} disabled={busy === "discovery"}>
                  {busy === "discovery" ? "Generating…" : "Generate"}
                </button>
              </div>
              {(m.discovery_questions || []).length === 0 && <EmptyHint label="Generate guided discovery questions prioritized by current performance issues." />}
              <div className="space-y-2">
                {(m.discovery_questions || []).slice(0, 12).map((q, i) => (
                  <div key={q.id || i} className="p-3 rounded-md border border-white/5 bg-white/[0.02]">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="text-[10px] mono text-slate-400 uppercase tracking-wider">{q.kind} · {q.category}</div>
                        <div className="text-sm text-slate-200 mt-1">{q.question}</div>
                        {!!q.rationale && <div className="text-xs text-slate-400 mt-2">Why: {q.rationale}</div>}
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <span className={`chip ${prioChip(q.priority)}`}>{q.priority}</span>
                        <select className="input !py-1 !text-xs !w-[120px]" value={q.status || "suggested"} onChange={async (e) => {
                          const next = (m.discovery_questions || []).map((x) => (x.id === q.id ? { ...x, status: e.target.value } : x));
                          setM((prev) => ({ ...prev, discovery_questions: next }));
                          await meetings.update(id, { discovery_questions: next });
                        }}>
                          <option value="suggested">suggested</option>
                          <option value="asked">asked</option>
                          <option value="skipped">skipped</option>
                        </select>
                      </div>
                    </div>
                    <textarea className="input mt-2 !min-h-[70px]" placeholder="Notes / answer…" value={q.notes || ""} onChange={async (e) => {
                      const next = (m.discovery_questions || []).map((x) => (x.id === q.id ? { ...x, notes: e.target.value } : x));
                      setM((prev) => ({ ...prev, discovery_questions: next }));
                    }} onBlur={async () => {
                      await meetings.update(id, { discovery_questions: (m.discovery_questions || []) });
                    }} />
                  </div>
                ))}
              </div>
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
                <div className="flex items-center gap-2"><Sparkle size={18} weight="duotone" color="#3FA9F5" /><h3 className="font-semibold">Recommendations</h3></div>
                <Link to="/strategy" className="text-xs text-[#3FA9F5] hover:underline">View all</Link>
              </div>
              <ul className="space-y-2 list-disc pl-5">{(m.strategic_recommendations || []).map((r, i) => <li key={i} className="text-sm text-slate-300">{r}</li>)}</ul>
              {(m.strategic_recommendations || []).length === 0 && <EmptyHint />}
            </section>
            <section className="card-flat p-5">
              <div className="flex items-center gap-2 mb-3"><Robot size={18} weight="duotone" color="#F59E0B" /><h3 className="font-semibold">Campaign Recommendations</h3></div>
              {(m.campaign_recommendations || []).length === 0 && <EmptyHint label="Generate the brief to get campaign-specific recommendations tied to performance." />}
              <div className="space-y-3">
                {(m.campaign_recommendations || []).map((rec, i) => (
                  <div key={i} className="p-3 rounded-md border border-white/5 bg-white/[0.02]">
                    <div className="flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <div className="text-[10px] mono text-slate-400 uppercase tracking-wider">
                          {(rec.platform || "other").replaceAll("_", " ")}{rec.campaign ? ` · ${rec.campaign}` : ""}
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <ExplainDialog title={(rec.campaign || rec.platform || "Campaign recommendations")} explain={rec.explain} />
                        <span className={`chip ${prioChip(rec.priority)}`}>{rec.priority || "medium"}</span>
                      </div>
                    </div>
                    <ul className="mt-2 space-y-1 list-disc pl-5">
                      {(rec.recommendations || []).map((r, idx) => (
                        <li key={idx} className="text-sm text-slate-300">{r}</li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
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
              <li><span className="mono text-[#3FA9F5]">3–13</span> · Wins</li>
              <li><span className="mono text-[#3FA9F5]">13–25</span> · Performance & strategy</li>
              <li><span className="mono text-[#3FA9F5]">25–35</span> · Issues + next steps</li>
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
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="font-semibold">Action Items ({actions.length})</h3>
                    <Link to={`/follow-up?meeting_id=${encodeURIComponent(id)}`} className="text-xs text-[#3FA9F5] hover:underline">Open follow-up</Link>
                  </div>
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
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="font-semibold">Client Health</h3>
                    <div className="text-xs text-slate-400 mt-1">
                      Log NPS and sentiment so we can track trends and flag churn risk early.
                    </div>
                  </div>
                  {!!m.sentiment_classification && (
                    <span
                      className={`chip ${
                        m.sentiment_classification === "at_risk"
                          ? "chip-danger"
                          : m.sentiment_classification === "concerned"
                            ? "chip-warn"
                            : m.sentiment_classification === "neutral"
                              ? "chip-info"
                              : "chip-success"
                      }`}
                    >
                      {String(m.sentiment_classification).replaceAll("_", " ")}
                    </span>
                  )}
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-4">
                  <div>
                    <div className="label">NPS (1–10)</div>
                    <select className="input mt-1.5" value={healthDraft.nps_score} onChange={(e) => setHealthDraft((p) => ({ ...p, nps_score: e.target.value }))}>
                      <option value="">—</option>
                      {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((n) => <option key={n} value={String(n)}>{n}</option>)}
                    </select>
                  </div>
                  <div>
                    <div className="label">Sentiment</div>
                    <select
                      className="input mt-1.5"
                      value={healthDraft.sentiment_classification}
                      onChange={(e) => setHealthDraft((p) => ({ ...p, sentiment_classification: e.target.value }))}
                    >
                      <option value="">—</option>
                      <option value="happy">Happy</option>
                      <option value="neutral">Neutral</option>
                      <option value="concerned">Concerned</option>
                      <option value="at_risk">At Risk</option>
                    </select>
                  </div>
                </div>
                <div className="mt-3">
                  <div className="label">Notes</div>
                  <textarea
                    className="input mt-1.5 !min-h-[90px]"
                    value={healthDraft.health_notes}
                    onChange={(e) => setHealthDraft((p) => ({ ...p, health_notes: e.target.value }))}
                    placeholder="What’s driving this rating? What do we need to fix next?"
                  />
                </div>
                <div className="mt-4 flex items-center justify-end">
                  <button className="btn-primary" type="button" onClick={saveHealth} disabled={savingHealth}>
                    {savingHealth ? "Saving…" : "Save Client Health"}
                  </button>
                </div>
              </div>
              <div className="card-flat p-5">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="font-semibold">Client Feedback</h3>
                    <div className="text-xs text-slate-400 mt-1">
                      Capture structured feedback after the meeting. {isAdsClient ? "Required for Ads clients before generating recap." : "Optional but recommended."}
                    </div>
                  </div>
                  {isAdsClient && <span className={`chip ${feedbackComplete ? "chip-success" : "chip-danger"}`}>{feedbackComplete ? "completed" : "required"}</span>}
                </div>

                <div className="grid grid-cols-1 md:grid-cols-4 gap-3 mt-4">
                  <div>
                    <div className="label">Lead Quality (1–5)</div>
                    <select className="input mt-1.5" value={feedbackDraft.lead_quality} onChange={(e) => setFeedbackDraft((p) => ({ ...p, lead_quality: Number(e.target.value) }))}>
                      {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
                    </select>
                  </div>
                  <div>
                    <div className="label">Campaign Quality (1–5)</div>
                    <select className="input mt-1.5" value={feedbackDraft.campaign_quality} onChange={(e) => setFeedbackDraft((p) => ({ ...p, campaign_quality: Number(e.target.value) }))}>
                      {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
                    </select>
                  </div>
                  <div>
                    <div className="label">Satisfaction (1–5)</div>
                    <select className="input mt-1.5" value={feedbackDraft.satisfaction} onChange={(e) => setFeedbackDraft((p) => ({ ...p, satisfaction: Number(e.target.value) }))}>
                      {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
                    </select>
                  </div>
                  <div>
                    <div className="label">Results (1–5)</div>
                    <select className="input mt-1.5" value={feedbackDraft.results} onChange={(e) => setFeedbackDraft((p) => ({ ...p, results: Number(e.target.value) }))}>
                      {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
                    </select>
                  </div>
                </div>
                <div className="mt-3">
                  <div className="label">Notes</div>
                  <textarea className="input mt-1.5 !min-h-[90px]" value={feedbackDraft.notes} onChange={(e) => setFeedbackDraft((p) => ({ ...p, notes: e.target.value }))} placeholder="Optional details…" />
                </div>
                <div className="mt-4 flex items-center justify-end">
                  <button className="btn-primary" type="button" onClick={saveFeedback} disabled={savingFeedback}>
                    {savingFeedback ? "Saving…" : "Save Feedback"}
                  </button>
                </div>
              </div>
              <div className="card-flat p-5">
                <button className="btn-primary flex items-center gap-2" onClick={genRecap} disabled={busy === "recap" || (isAdsClient && !feedbackComplete)} data-testid="generate-recap-btn">
                  {busy === "recap" ? <ArrowsClockwise size={14} className="animate-spin" /> : <EnvelopeSimple size={14} weight="duotone" />} Generate Recap Email
                </button>
                {isAdsClient && !feedbackComplete && <div className="text-xs text-slate-400 mt-2">Feedback is required for Ads clients before generating recap.</div>}
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
