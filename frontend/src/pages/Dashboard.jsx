import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { dashboard } from "../api";
import { PageHead } from "../Layout";
import { Users, Heartbeat, Warning, CalendarCheck, CheckSquare, Megaphone, TrendUp, ArrowRight, Sparkle } from "@phosphor-icons/react";

const StatCard = ({ icon: Icon, label, value, hint, tone = "info", testid }) => {
  const toneClass = { success: "chip-success", warn: "chip-warn", danger: "chip-danger", info: "chip-info" }[tone] || "chip-info";
  return (
    <div className="card-flat p-5 animate-fade-up" data-testid={testid}>
      <div className="flex items-center justify-between">
        <span className="label">{label}</span>
        <span className={`chip ${toneClass}`}><Icon size={12} weight="bold" /></span>
      </div>
      <div className="mt-3 text-3xl font-bold mono">{value}</div>
      {hint && <div className="text-xs text-slate-400 mt-1.5">{hint}</div>}
    </div>
  );
};

export default function Dashboard() {
  const [data, setData] = useState(null);
  useEffect(() => { dashboard.overview().then(setData).catch(() => {}); }, []);

  return (
    <div>
      <PageHead
        title="Operating System Overview"
        subtitle="Account health, meeting cadence, action accountability and content opportunities — all in one control room."
        actions={<Link to="/clients" className="btn-primary flex items-center gap-2" data-testid="goto-clients-btn">Open Roster <ArrowRight size={14} weight="bold" /></Link>}
      />
      {!data && <div className="text-slate-400">Loading…</div>}
      {data && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <StatCard icon={Users} label="Total Clients" value={data.total_clients} hint="Active roster" tone="info" testid="stat-clients" />
            <StatCard icon={Heartbeat} label="Avg Health Score" value={data.avg_health_score || "—"} hint="0–100 weighted index" tone="success" testid="stat-health" />
            <StatCard icon={Warning} label="At-Risk Clients" value={data.churn_risk_high + data.churn_risk_medium} hint={`${data.churn_risk_high} high · ${data.churn_risk_medium} medium`} tone={data.churn_risk_high ? "danger" : "warn"} testid="stat-risk" />
            <StatCard icon={CalendarCheck} label="Meetings This Month" value={data.meetings_this_month} hint="Scheduled + completed" tone="info" testid="stat-meetings" />
            <StatCard icon={CalendarCheck} label="Prep Queue" value={data.prep_queue_count || 0} hint="Meetings needing brief" tone={data.prep_queue_count ? "warn" : "success"} testid="stat-prep" />
            <StatCard icon={CheckSquare} label="Open Action Items" value={data.open_action_items} hint={`${data.overdue_action_items} overdue`} tone={data.overdue_action_items ? "warn" : "info"} testid="stat-actions" />
            <StatCard icon={Megaphone} label="Content Captures" value={data.content_captures_total} hint={`${data.content_pending_routing} pending route`} tone="success" testid="stat-content" />
            <StatCard icon={Sparkle} label="Suggestions Ready" value={data.suggestions_ready_clients || 0} hint="Clients with proactive recs" tone={(data.suggestions_ready_clients || 0) ? "success" : "info"} testid="stat-suggestions" />
            <StatCard icon={TrendUp} label="Review Forecast" value={`${data.review_forecast_next_month || "—"}`} hint="Next month (avg across roster)" tone="info" testid="stat-review-forecast" />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="card-flat p-5">
              <div className="flex items-center justify-between mb-3">
                <h3 className="font-semibold">Recent Meetings</h3>
                <Link to="/meetings" className="text-xs text-[#3FA9F5] hover:underline" data-testid="view-all-meetings-link">View all</Link>
              </div>
              {data.recent_meetings.length === 0 && <div className="text-slate-500 text-sm py-6 text-center">No meetings yet. Add a client and schedule your first touch.</div>}
              <div className="flex flex-col gap-2">
                {data.recent_meetings.map((m) => (
                  <Link key={m.id} to={`/meetings/${m.id}`} className="flex items-center justify-between p-3 rounded-md border border-white/5 hover:bg-white/[0.03]">
                    <div>
                      <div className="font-medium text-sm">{m.title}</div>
                      <div className="text-xs text-slate-400 mt-0.5">{m.client_name} · {m.status}</div>
                    </div>
                    <ArrowRight size={14} className="text-slate-500" />
                  </Link>
                ))}
              </div>
            </div>

            <div className="card-flat p-5">
              <div className="flex items-center justify-between mb-3">
                <h3 className="font-semibold">At-Risk Clients</h3>
                <Link to="/clients" className="text-xs text-[#3FA9F5] hover:underline">All clients</Link>
              </div>
              {data.at_risk_clients.length === 0 && <div className="text-slate-500 text-sm py-6 text-center">No clients flagged. Run a transcript analysis to update sentiment.</div>}
              <div className="flex flex-col gap-2">
                {data.at_risk_clients.map((c) => (
                  <Link key={c.id} to={`/clients/${c.id}`} className="flex items-center justify-between p-3 rounded-md border border-white/5 hover:bg-white/[0.03]" data-testid={`risk-client-${c.id}`}>
                    <div>
                      <div className="font-medium text-sm">{c.name} · <span className="text-slate-400">{c.company}</span></div>
                      <div className="text-xs text-slate-400 mt-0.5">Health <span className="mono">{c.health_score}</span> · {c.churn_risk} risk</div>
                    </div>
                    <span className={`chip ${c.churn_risk === "high" ? "chip-danger" : "chip-warn"}`}>{c.churn_risk}</span>
                  </Link>
                ))}
              </div>
            </div>

            <div className="card-flat p-5">
              <div className="flex items-center justify-between mb-3">
                <h3 className="font-semibold">Monthly Touch Prep Queue</h3>
                <Link to="/meetings" className="text-xs text-[#3FA9F5] hover:underline">Meetings</Link>
              </div>
              {(data.prep_queue || []).length === 0 && <div className="text-slate-500 text-sm py-6 text-center">Nothing waiting. Every upcoming meeting has a brief.</div>}
              <div className="flex flex-col gap-2">
                {(data.prep_queue || []).map((m) => (
                  <Link key={m.id} to={`/meetings/${m.id}`} className="flex items-center justify-between p-3 rounded-md border border-white/5 hover:bg-white/[0.03]">
                    <div>
                      <div className="font-medium text-sm">{m.client_name}</div>
                      <div className="text-xs text-slate-400 mt-0.5">{m.title} · {m.scheduled_at || "Unscheduled"}</div>
                    </div>
                    <span className="chip chip-warn">needs brief</span>
                  </Link>
                ))}
              </div>
            </div>
          </div>

          <div className="card-flat p-5 mt-6">
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-semibold flex items-center gap-2"><Sparkle size={16} weight="duotone" /> Proactive Recommendations</h3>
              <Link to="/clients" className="text-xs text-[#3FA9F5] hover:underline">Open clients</Link>
            </div>
            {(data.top_suggestions || []).length === 0 && (
              <div className="text-slate-500 text-sm py-6 text-center">No saved suggestions yet. Generate suggestions from a client page.</div>
            )}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {(data.top_suggestions || []).slice(0, 8).map((s, idx) => (
                <Link key={`${s.client_id}-${idx}`} to={`/clients/${s.client_id}`} className="p-4 rounded-md border border-white/5 hover:bg-white/[0.03]">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-sm font-medium">{s.client_name}</div>
                    <span className={`chip ${String(s.priority || "medium") === "high" ? "chip-danger" : String(s.priority || "medium") === "low" ? "chip-success" : "chip-warn"}`}>{s.priority}</span>
                  </div>
                  <div className="text-xs text-slate-400 mt-1">{String(s.category || "").replaceAll("_", " ")}</div>
                  <div className="text-sm mt-2 text-slate-200">{s.title}</div>
                  {!!s.expected_impact && <div className="text-xs text-slate-400 mt-1">Impact: {s.expected_impact}</div>}
                  <div className="text-[11px] text-slate-500 mt-1 mono">confidence {(Math.round((Number(s.confidence || 0) * 100)))}%</div>
                </Link>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
