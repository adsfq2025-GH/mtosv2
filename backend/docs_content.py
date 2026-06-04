"""Documentation Hub content — SOPs, playbooks, scorecards, checklists, frameworks."""
from typing import List, Dict

DOCS: List[Dict] = [
    # ============ FRAMEWORKS ============
    {
        "slug": "mtm-framework",
        "category": "Framework",
        "title": "The Monthly Touch Meeting Framework",
        "summary": "Master framework: turn repetitive reporting calls into strategic growth conversations that drive retention.",
        "body": """# The Monthly Touch Meeting (MTM) Operating System

## Why MTMs Matter
Monthly Touch Meetings are the single highest-leverage retention tool an agency owns. Done well they reduce churn 20–40%, lift NRR, and surface 3–5 testimonial opportunities per quarter.

## The 5 Outcomes Every MTM Must Deliver
1. The client feels **informed** — they know exactly what we did, what worked, what didn't.
2. The client feels **involved** — they participated in the strategy, didn't just receive a report.
3. The client feels **confident** — perceived value increased, not decreased.
4. The client feels **supported** — they know what's next and who owns it.
5. The agency captures **strategic intel** — sentiment, churn signals, upsell, content.

## The 4-Phase MTM Lifecycle
- **Phase 1 — Prep (45 min, automated to <10 min via Monthly Touch OS)**
- **Phase 2 — Meeting (60 min, structured)**
- **Phase 3 — Recap (10 min, AI-drafted, human-reviewed)**
- **Phase 4 — Follow-through (continuous, tracked in ClickUp + GHL)**

## Wins & Issues (No Artificial Limits)
Every meeting opens with clear, specific wins and surfaces transparent issues. Wins reinforce value; issues build trust by demonstrating proactive leadership. Generate as many as are meaningful and supported by real data.

## The Trusted Advisor Posture
Account managers are not status messengers — they are **strategic consultants**. Lead with insight, not data. Use phrases like *"What I'd recommend next…"*, *"Here's what we're seeing across similar accounts…"*.
""",
    },
    {
        "slug": "retention-psychology",
        "category": "Framework",
        "title": "Retention Psychology & Why Clients Churn",
        "summary": "What causes silent churn and how MTMs interrupt it.",
        "body": """# Retention Psychology

## The 7 Root Causes of Client Churn
1. **Perceived lack of value** — results may exist, but the client doesn't *feel* them.
2. **Communication vacuum** — no one is reaching out proactively.
3. **Disconnected reporting** — numbers without narrative.
4. **Unmet expectations** — never explicitly aligned in onboarding.
5. **Relationship neglect** — account manager is invisible.
6. **Strategy fatigue** — same plan repeated month after month.
7. **No clear future** — the client doesn't know what's coming next.

## How the MTM System Solves Each
| Cause | MTM Counter-move |
|---|---|
| Perceived value | Wins framed in client language, every meeting |
| Communication | Recurring monthly cadence + recap email |
| Disconnected reports | Wins → narrative → strategic recommendation |
| Expectations | Open with last month's commitments, close with next |
| Relationship neglect | Live human conversation, named action items |
| Strategy fatigue | Always 1 new strategic recommendation per meeting |
| No future | "Next 30/60/90" closing always covered |

## Sentiment Watch Signals
Track in the transcript analyzer:
- Reduced engagement / one-word replies
- "I'll think about it" language around invoices
- Comparison to competitors / other agencies
- Decision delays on approvals
- New stakeholders showing up unannounced
""",
    },

    # ============ SOPs ============
    {
        "slug": "sop-prep-workflow",
        "category": "SOP",
        "title": "SOP — Pre-Meeting Prep Workflow",
        "summary": "10-minute prep playbook using Monthly Touch OS auto-brief.",
        "body": """# SOP — Pre-Meeting Prep (10 minutes)

## Step-by-step
1. **T-72h** — Open client in Monthly Touch OS. Click **Generate Brief**. AI pulls KPI snapshot from all connected integrations.
2. **T-48h** — Review the wins. Edit language to match client's vocabulary. Confirm metrics.
3. **T-48h** — Review the issues. Confirm action plans are real and credible. Add any nuance.
4. **T-24h** — Skim last meeting's action items. Mark completed ones. Carry forward incomplete.
5. **T-24h** — Read sentiment history + last recap email. Reread any unresolved threads in Gmail.
6. **T-2h** — Open the Live Meeting view. Send Google Meet link if not already sent.
7. **T-15m** — Glance at the testimonial-opportunity prompt. Decide if you'll ask today.

## Quality Bar
- Each win includes a number AND a "what it means for your business" sentence.
- Each issue includes "what we're already doing" — never raise an issue without an in-flight solution.
- Talking points are framed as questions or strategic suggestions, not status updates.
""",
    },
    {
        "slug": "sop-during-meeting",
        "category": "SOP",
        "title": "SOP — Running the Meeting",
        "summary": "Structure, pacing, language to lead a confident 60-minute MTM.",
        "body": """# SOP — Running a 60-Minute MTM

## Suggested Flow (60 min)
- **0–3 min — Rapport & Agenda** ("Before we jump in — how's the team holding up this month?")
- **3–13 min — Wins** (specific, emotional, client-language)
- **13–25 min — Performance & Strategy** (1 chart max per topic; *"here's what's driving it…"*)
- **25–35 min — Issues + Plan** (own the issue, present the fix; ask for input)
- **35–45 min — Client Voice** (engagement questions; testimonial moment if warranted)
- **45–55 min — Next 30 Days** (strategy + 1 new recommendation + action items)
- **55–60 min — Recap & Close** ("Here's what you'll get from me by Friday…")

## Phrases that Sound Like a Consultant
- *"What I'd recommend next is…"*
- *"Here's what we're seeing work across similar accounts…"*
- *"Two things I want to flag — and what we're already doing about them."*
- *"What would make this partnership feel even more valuable to you?"*

## Phrases to Avoid
- *"Just wanted to check in."*
- *"Nothing really changed this month."*
- *"Same as last month."*
- *"I'll get back to you on that."* (instead: *"I'll have an answer by EOD Thursday."*)
""",
    },
    {
        "slug": "sop-post-meeting",
        "category": "SOP",
        "title": "SOP — Post-Meeting Follow-Through",
        "summary": "Recap, action items, content routing — within 24h.",
        "body": """# SOP — Post-Meeting (within 24 hours)

1. **Upload transcript** in Monthly Touch OS → click *Analyze Transcript*.
2. **Review AI-extracted action items** — confirm owner, due date, push to ClickUp.
3. **Review content opportunities** — flag any quotes/clips for Luisa & marketing.
4. **Edit recap email** (AI-drafted) — personalize opening, send from Gmail.
5. **Update Client Health Score** based on sentiment signal.
6. **Update GoHighLevel notes** — paste sentiment + key moments.
7. **Schedule next month's meeting** if not already recurring.

## SLA
- Recap sent: **< 24h**
- Action items in ClickUp: **< 4h**
- Content moments routed: **< 48h**
- Churn signal escalation: **immediate (< 2h)**
""",
    },

    # ============ PLAYBOOKS ============
    {
        "slug": "playbook-testimonial-capture",
        "category": "Playbook",
        "title": "Playbook — Testimonial & Marketing Content Capture",
        "summary": "How to capture testimonials naturally during MTMs without making it awkward.",
        "body": """# Testimonial Capture Playbook

## When to Ask
Ask **only when**:
- The client has expressed satisfaction in the last 60 days, AND
- A measurable result improved this month, AND
- The relationship is at least 90 days old.

The Monthly Touch OS auto-flags clients who meet all three.

## How to Ask (3 Tiers)

**Tier 1 — Quote / Written Testimonial (lowest friction)**
> *"Hey [Name] — based on the progress we just walked through, would you be open to me writing up a short paragraph as a quote we could share? I'll draft it, you'll have full edit rights."*

**Tier 2 — 30-second Video Testimonial**
> *"If you'd be open to it, I'd love to capture a quick 30-second video about your experience so far. It really helps other business owners understand the impact of the work we're doing. We can do it right now in the next 60 seconds — no script, just your honest take."*

**Tier 3 — Full Case Study**
> *"Your story is genuinely one of the best we've seen this year. Would you be open to a proper case study — we'd interview you, build the visuals, and you'd own approval on the final piece."*

## What to Do After Capture
1. Flag the moment in Monthly Touch OS (`Mark Content Captured`).
2. AI auto-creates a content task → routed to Luisa + marketing.
3. Permission language gets attached (always confirm explicit permission).
4. Asset stored in client's Drive folder.

## What NOT to Do
- Don't ask within the first 90 days.
- Don't ask if last month had a hard conversation.
- Don't ask for video when the client seems rushed.
- Don't pressure — one ask, then move on if soft "no".
""",
    },
    {
        "slug": "playbook-difficult-clients",
        "category": "Playbook",
        "title": "Playbook — Handling Difficult Conversations",
        "summary": "Frustration, missed targets, churn-risk conversations.",
        "body": """# Difficult Conversations Playbook

## The 4-Step Frame: LEAD
- **L**isten without interrupting (90 seconds minimum).
- **E**mpathize ("I hear you — that's frustrating, and you're right to flag it.").
- **A**ssess ("Here's what I'm seeing in the data and what I think is driving it.").
- **D**eliver ("Here's what I'm going to do, and when you'll see the result.").

## Common Scripts

**"My results aren't where I expected"**
> *"Totally fair. Let me show you exactly where we are vs. where we said we'd be by month X, what's driving the gap, and the specific 3-step plan to close it. If after 60 days we're still off, here's what we'd do differently."*

**"I'm thinking of going elsewhere"**
> *"I appreciate you telling me directly — that means a lot. Can I ask what's behind it? If it's results, let's look together. If it's communication, I want to fix it. If you'd just like to explore options, I'd rather help you make a great decision than have you leave quietly."*

**"You haven't been responsive"**
> *"You're right, and I own that. Here's what's going to change starting today: [specific SLA]. If I miss that, you have my direct line."*
""",
    },

    # ============ CHECKLISTS ============
    {
        "slug": "checklist-mandatory",
        "category": "Checklist",
        "title": "Mandatory MTM Talking Points Checklist",
        "summary": "Non-negotiable items every MTM must cover.",
        "body": """# Mandatory MTM Checklist

Every Monthly Touch Meeting must include:

- [ ] **Wins** (with metrics + client-language meaning)
- [ ] **Issues with action plans**
- [ ] **Campaign progress vs. last month's promises**
- [ ] **One new strategic recommendation**
- [ ] **Client voice / open-ended questions**
- [ ] **Testimonial/content opportunity assessment**
- [ ] **Next 30 days plan**
- [ ] **Named action items with owners and dates**
- [ ] **Confirmation of next meeting date**
- [ ] **Sentiment read (private — logged after the call)**
""",
    },
    {
        "slug": "checklist-prep",
        "category": "Checklist",
        "title": "Pre-Meeting Prep Checklist",
        "summary": "10-minute prep with auto-brief.",
        "body": """# Pre-Meeting Prep Checklist

- [ ] Auto-brief generated (T-72h)
- [ ] Wins reviewed and edited for client voice
- [ ] Issues confirmed with credible action plans
- [ ] Last meeting's action items reviewed
- [ ] Open Gmail threads scanned for unresolved items
- [ ] Recent ClickUp tickets / GHL pipeline reviewed
- [ ] Map Check-ins heat map open and ready to share
- [ ] Google Meet link sent
- [ ] Testimonial-readiness checked
- [ ] One new strategic recommendation prepared
""",
    },

    # ============ SCORECARDS ============
    {
        "slug": "scorecard-meeting",
        "category": "Scorecard",
        "title": "MTM Quality Scorecard (out of 100)",
        "summary": "QA framework for reviewing recorded meetings or self-rating.",
        "body": """# MTM Quality Scorecard — 100 pts

## Preparation (20 pts)
- Auto-brief reviewed and personalized: 5
- Action items from last meeting closed or carried forward: 5
- Open Gmail threads addressed: 5
- One new strategic recommendation ready: 5

## Meeting Execution (50 pts)
- Wins delivered with metric + meaning: 10
- Issues with credible action plan: 10
- Time managed within 60 minutes: 5
- At least 3 open-ended client questions asked: 10
- Strategic posture (not status messenger): 10
- Confident closing with named owners + dates: 5

## Follow-through (20 pts)
- Recap sent within 24h: 10
- Action items in ClickUp within 4h: 5
- Sentiment + notes updated in GHL: 5

## Bonus (10 pts)
- Testimonial / content opportunity captured: +5
- Upsell or expansion discussed: +5

**80+ = Excellent. 60–79 = Coachable. <60 = Immediate retraining.**
""",
    },
    {
        "slug": "scorecard-account-health",
        "category": "Scorecard",
        "title": "Account Health Score Framework",
        "summary": "0–100 score that drives the dashboard and churn-risk flags.",
        "body": """# Account Health Score Framework

## Components & Weights
- **Results trend (30%)** — KPIs vs prior 30 days
- **Engagement (20%)** — meetings attended, response time, NPS-style signal
- **Sentiment (20%)** — last meeting transcript analysis
- **Commercial (15%)** — invoices paid on time, upsell signals
- **Tenure & longevity (10%)** — >12mo gets a stability bonus
- **Communication (5%)** — unresolved Gmail threads, missed callbacks

## Bands
- **80–100 — Green** — testimonial / case study candidate
- **60–79 — Yellow** — stable, watch sentiment
- **40–59 — Orange** — proactive intervention required
- **<40 — Red** — escalate to leadership within 48h

## Auto-actions
- Drop into Yellow → flag in dashboard
- Drop into Orange → required 1:1 within 7 days, manager notified
- Drop into Red → leadership escalation, retention play activated
""",
    },

    # ============ AUTOMATION ============
    {
        "slug": "automation-architecture",
        "category": "Automation",
        "title": "Automation Ecosystem & Architecture",
        "summary": "Categorized automation map: what runs inside Monthly Touch OS, what needs APIs, what stays human.",
        "body": """# Automation Architecture

## Category A — Fully inside Monthly Touch OS (no extra software)
- AI-generated meeting brief (wins, issues, talking points, suggested questions)
- AI transcript analysis (action items, content moments, sentiment, churn risk)
- AI recap email drafting
- Account Health scoring
- Documentation Hub (SOPs, playbooks, scorecards)
- Action item tracking
- Content / testimonial queue
- Meeting QA scorecards
- Internal user management

## Category B — Through Monthly Touch OS + existing APIs
- ClickUp: pull tasks, push action items
- GoHighLevel: pipeline pulls, notes sync, opportunity updates
- Google Ads / GBP / GA4 / GSC / LSA / Meta Ads: KPI snapshots
- Ahrefs: SEO/backlink summaries
- Gmail: communication history, draft follow-ups
- Google Drive / Meet: pull transcripts/recordings
- Map Check-ins: pull rank scans, generate heat-map summaries

## Category C — Specialized tooling (only if needed)
- Loom / Fathom: native video clipping (Drive + Meet covers most)
- Looker Studio: white-label client dashboards (optional)
- Zapier / Make: lightweight glue for edge cases (most flows are native)

## Category D — Human-only (never automate)
- Final recap personalization & send
- The actual conversation
- Strategic recommendations sign-off
- Difficult conversations / churn-risk interventions
- Final testimonial ask + permission capture

## Minimum Software Stack
**Required**: Monthly Touch OS + AI Provider Key(s) + ClickUp + GHL + Google Workspace.
**Optional but high-ROI**: Ahrefs, Map Check-ins, Meta Ads.
""",
    },
    {
        "slug": "automation-google-meet",
        "category": "Automation",
        "title": "Google Meet Transcript → AI Analysis Workflow",
        "summary": "How Meet + Drive + Monthly Touch OS pipeline works.",
        "body": """# Google Meet → AI Analysis Pipeline

## Flow
1. Account manager turns on **"Take notes with Gemini"** in Google Meet (or records the meeting).
2. After the call, Google Drive saves the transcript (Google Doc) and recording (MP4).
3. Monthly Touch OS (when Drive integration is connected) auto-polls the configured client folder.
4. New transcript detected → linked to the most recent scheduled meeting for that client.
5. AI Analysis job kicks off:
   - Action items extracted
   - Sentiment scored
   - Content moments flagged
   - Health score updated
6. Account manager receives a notification: *"Brief ready for review"*.

## Manual Fallback
If Drive isn't connected, account manager pastes the transcript into the meeting page and clicks **Analyze Transcript**. Same downstream flow.

## Privacy & Permissions
- Transcripts stored encrypted at rest.
- Only the assigned account manager + admins can view.
- Client-shared portions of testimonials require explicit permission flag before routing to marketing.
""",
    },
    {
        "slug": "automation-map-checkins",
        "category": "Automation",
        "title": "Map Check-ins Integration Spec",
        "summary": "What's required to fully integrate the Map Check-ins platform.",
        "body": """# Map Check-ins Integration Spec

## What we need to integrate
- **REST API base URL**
- **API token** (long-lived service token preferred)
- **Company / workspace ID** scoping
- API documentation covering at minimum:
  - `GET /scans?company_id&date_from&date_to` — list rank scans
  - `GET /scans/{id}` — full grid + per-keyword detail
  - `GET /keywords?company_id` — tracked keywords w/ history
  - `POST /scans/trigger?company_id&keyword_id` — fire ad-hoc scan
  - `GET /checkins?company_id&date_from&date_to` — field tech check-ins
  - Webhook support for `scan.completed`

## Auth recommendation
- Bearer token in `Authorization` header
- Optional HMAC signing for webhooks

## What Monthly Touch OS will do once connected
- Auto-pull last 30 days of scans per client → feeds the brief's GBP/local SEO section
- Compute avg grid rank, top-3 %, keyword movers
- Trigger a fresh scan 72h before each MTM
- AI-generate plain-English summaries from the heat map
- Identify weakest geographies → suggest GBP posts / service-area pages

## Security
- Tokens stored encrypted (Fernet) — never echoed in any API response.
""",
    },
    {
        "slug": "internal-white-label-sop",
        "category": "Internal SOP",
        "title": "White Label SOP (Map Ranking Internal)",
        "summary": "How we onboard a new white-label tenant, assign domains, and keep data isolated.",
        "body": """# White Label SOP (Internal)

## Principle
White label is one codebase + one deployment. Each new white-label customer is a new tenant with isolated data, independent users, and per-tenant branding/terminology.

## Default Domains
Every white-label tenant starts with:
- `clientname.mapranking.com` (where `clientname` = tenant slug)

Optional:
- Custom domain like `app.clientdomain.com` mapped to the tenant.

## Tenant Data Isolation Rules
- Every data record must be scoped by `tenant_id` (clients, meetings, action items, integrations, content capture, tokens).
- Never query without tenant scope.
- Integrations are:
  - Tenant-scoped (ClickUp/GHL tokens, location tokens, etc.)
  - User-scoped where required (Google OAuth per account manager).

## Onboarding SOP (New White Label Tenant)
1. Create tenant (`slug`, `name`).
2. Create tenant admin user (tenant_role = owner/admin).
3. Configure branding and terminology in White Label Configuration Center.
4. Confirm the default domain works: `slug.mapranking.com`.
5. If custom domain is requested:
   - Collect target domain (`app.clientdomain.com`)
   - Add it under White Label → Domains
   - Configure DNS/hosting as required, then validate it routes to the tenant.
6. Set tenant-level integrations (GoHighLevel, ClickUp).
7. Invite account managers and confirm role-based access.
8. Import clients (GoHighLevel import) and confirm per-client mappings.

## Role-based Access (Map Ranking)
- Account Managers: day-to-day execution; no access to tenant-level secrets or domain settings.
- Tenant Admins: manage integrations, domains, branding, and exports configuration.
- System Admin: cross-tenant operations and support.
""",
        "audience": "internal",
        "min_role": "admin",
    },
]


def get_docs_summary(docs=None):
    src = docs or DOCS
    return [
        {"slug": d["slug"], "category": d["category"], "title": d["title"], "summary": d["summary"]}
        for d in src
    ]


def get_doc(slug: str):
    for d in DOCS:
        if d["slug"] == slug:
            return d
    return None


def get_categories(docs=None):
    src = docs or DOCS
    cats = {}
    for d in src:
        cats.setdefault(d["category"], 0)
        cats[d["category"]] += 1
    return [{"category": k, "count": v} for k, v in cats.items()]
