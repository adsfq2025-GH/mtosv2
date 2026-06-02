import React, { useEffect, useState } from "react";
import { contentCaptures } from "../api";
import { PageHead } from "../Layout";
import { Megaphone } from "@phosphor-icons/react";

export default function Opportunities() {
  const [items, setItems] = useState([]);
  const load = () => contentCaptures.list().then(setItems);
  useEffect(() => { load(); }, []);
  const route = async (id, val) => { await contentCaptures.update(id, { routed_to_marketing: val }); load(); };

  return (
    <div>
      <PageHead title="Opportunities" subtitle="Testimonials, wins, and marketing-worthy moments — ready to route." />
      {items.length === 0 && <div className="card-flat p-10 text-center text-slate-400">No opportunities captured yet. Run transcript analysis after your next Monthly Touch.</div>}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {items.map((c) => (
          <div key={c.id} className="card-flat p-5" data-testid={`opportunity-card-${c.id}`}>
            <div className="flex items-center justify-between mb-2">
              <span className="chip chip-success"><Megaphone size={11} /> {c.type}</span>
              {c.routed_to_marketing
                ? <span className="chip chip-info">routed</span>
                : <button className="btn-primary text-xs !py-1 !px-2" onClick={() => route(c.id, true)} data-testid={`route-${c.id}`}>Route to marketing</button>}
            </div>
            <div className="text-sm text-slate-200 italic">"{c.content}"</div>
            {c.notes && <div className="text-xs text-slate-400 mt-2">{c.notes}</div>}
            <div className="text-[11px] mono text-slate-500 mt-2">Client {(c.client_id || "").slice(0, 8)} · Meeting {(c.meeting_id || "—").slice(0, 8)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

