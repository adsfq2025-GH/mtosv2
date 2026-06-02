import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { meetings } from "../api";
import { PageHead } from "../Layout";

export default function Testimonials() {
  const [list, setList] = useState([]);
  useEffect(() => { meetings.list().then(setList).catch(() => {}); }, []);

  const rows = useMemo(
    () => (list || [])
      .filter((m) => (m.testimonial_opportunity || "").trim())
      .sort((a, b) => (b.scheduled_at || "").localeCompare(a.scheduled_at || "")),
    [list],
  );

  return (
    <div>
      <PageHead title="Testimonials" subtitle="Client voice, testimonial moments, and referral-ready quotes." />
      {rows.length === 0 && <div className="card-flat p-10 text-center text-slate-400">No testimonial moments yet. Generate briefs and analyze transcripts to populate this feed.</div>}
      <div className="card-flat overflow-hidden">
        {rows.map((m, i) => (
          <Link
            key={m.id}
            to={`/meetings/${m.id}`}
            className={`block p-4 hover:bg-white/[0.03] ${i !== rows.length - 1 ? "border-b border-white/5" : ""}`}
            data-testid={`testimonial-row-${m.id}`}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-sm font-semibold">{m.client_name}</div>
                <div className="text-xs text-slate-500 mt-0.5">{m.title} · {m.scheduled_at || "Unscheduled"}</div>
                <div className="text-sm text-slate-200 mt-2 leading-relaxed">"{m.testimonial_opportunity}"</div>
              </div>
              <span className="chip chip-success shrink-0">moment</span>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}

