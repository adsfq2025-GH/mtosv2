import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { meetings } from "../api";
import { PageHead } from "../Layout";
import { Lightbulb } from "@phosphor-icons/react";

export default function Strategy() {
  const [list, setList] = useState([]);
  useEffect(() => { meetings.list().then(setList).catch(() => {}); }, []);

  const rows = useMemo(
    () => (list || [])
      .filter((m) => (m.strategic_recommendations || []).length > 0)
      .sort((a, b) => (b.scheduled_at || "").localeCompare(a.scheduled_at || "")),
    [list],
  );

  return (
    <div>
      <PageHead title="Strategy" subtitle="Account-specific recommendations, opportunities, and next moves." />
      {rows.length === 0 && <div className="card-flat p-10 text-center text-slate-400">No strategic recommendations yet. Generate briefs and analyze transcripts to populate this feed.</div>}
      <div className="space-y-4">
        {rows.map((m) => (
          <div key={m.id} className="card-flat p-5" data-testid={`strategy-card-${m.id}`}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-sm font-semibold">{m.client_name}</div>
                <div className="text-xs text-slate-500 mt-0.5">{m.title} · {m.scheduled_at || "Unscheduled"}</div>
              </div>
              <Link className="text-xs text-[#3FA9F5] hover:underline shrink-0" to={`/meetings/${m.id}`}>Open meeting</Link>
            </div>
            <ul className="mt-3 space-y-2 list-disc pl-5">
              {(m.strategic_recommendations || []).map((r, i) => (
                <li key={i} className="text-sm text-slate-300">
                  <span className="inline-flex items-center gap-2"><Lightbulb size={14} weight="duotone" />{r}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

