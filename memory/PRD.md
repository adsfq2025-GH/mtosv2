# Monthly Touch OS — Product Requirements Document

## Original Problem Statement
Monthly Touch Meeting Operating System + Automation Framework. Turn repetitive reporting into clear, client-focused conversations. Centralize meeting prep, action items, follow-through, and visibility into account health.

**Brand**: Monthly Touch OS — Powered by Map Ranking.

## Architecture
- **Frontend**: React (CRA) + React Router + Tailwind + Phosphor Icons
- **Backend**: FastAPI + Motor (MongoDB async)
- **AI Engine**: Provider router (`backend/ai.py`) with retries (Groq / OpenAI / Gemini, depending on model_key)
- **Auth**: JWT (HS256) + bcrypt; first user auto-promotes to admin
- **Integration credentials**: Fernet-encrypted at rest

## User Personas
- **Account Manager (manager role)**: prepares & runs Monthly Touch Meetings
- **Client Success Director / Admin (admin role)**: configures integrations, owns retention metrics
- **Marketing Team (downstream)**: receives content/testimonial captures (queue inside the app)

## Core Modules (all implemented)
| Module | Status | File |
|---|---|---|
| JWT Auth (login/register/me) | DONE | `backend/auth.py`, `pages/Auth.jsx` |
| Client roster + detail | DONE | `backend/models.py`, `pages/Clients.jsx` |
| Meetings CRUD | DONE | `pages/MeetingDetail.jsx` |
| AI Meeting Brief (wins / issues / talking points / questions / recommendations / testimonial opp) | DONE | `backend/ai.py::generate_meeting_brief` |
| Transcript Analysis (action items, content opps, sentiment, churn risk, health score) | DONE | `backend/ai.py::analyze_transcript` |
| Recap email generator | DONE | `backend/ai.py::generate_recap` |
| Action Items tracker | DONE | `pages/Others.jsx::Actions` |
| Content / Testimonial queue | DONE | `pages/Others.jsx::ContentQueue` |
| 13-platform Integrations (encrypted creds + status badges) | DONE (credential storage) | `backend/integrations_meta.py`, `pages/Others.jsx::Integrations` |
| Documentation Hub (14 frameworks/SOPs/playbooks/scorecards/automation maps) | DONE | `backend/docs_content.py`, `pages/Others.jsx::DocsHub` |
| Dashboard overview (health, risk, meetings, actions, content) | DONE | `pages/Dashboard.jsx` |

## What's been implemented (2026-01)
- ✅ Full backend API (40/40 tests passed in `iteration_1.json`)
- ✅ End-to-end frontend flows (12/13 verified in `iteration_2.json`)
- ✅ Bootstrap admin auto-seeded on backend startup
- ✅ AI engine producing real, high-quality, on-topic output via direct provider API keys
- ✅ 13 integration modules wired (credential capture + encryption + status; live data pulls deferred)
- ✅ Documentation Hub with 14 deeply-written guides covering framework, retention psychology, SOPs (prep / during / post), playbooks (testimonial, difficult convos), checklists, scorecards, automation architecture, Google Meet pipeline, Map Check-ins spec
- ✅ Security hardening applied (registration role escalation closed, /users admin-only, meeting cascade delete)

## Prioritized Backlog
### P1 — Live Integrations (user will plug in credentials one-by-one)
- ClickUp API client: fetch tasks, push action items (creds already supported)
- GoHighLevel: pull pipeline, push notes
- Google Ads / GBP / GA4 / GSC / LSA: KPI pulls via OAuth
- Meta Ads + Ahrefs: KPI + competitor pulls
- Google Drive + Meet: auto-attach Gemini-generated transcripts
- Map Check-ins: rank scans + heat-map summaries

### P2 — Enhancements
- Replace native `datetime-local` with shadcn DateTime picker
- Account health score auto-recompute job (cron)
- Email send (Gmail) for recap
- Per-client onboarding context aggregation from Drive
- Per-client KPI history chart timeline
- Admin user management UI
- Per-meeting QA scorecard form

### P3 — Polish
- Feature-flag bootstrap-admin hint on login card for production
- Empty-state hero illustrations
- Keyboard shortcuts palette (⌘K)

## Next Action Items
1. User provides API credentials → flip integrations to live one at a time
2. Wire first live integration: ClickUp (highest impact for action item sync)
3. Then GHL, then Google Workspace OAuth bundle
4. Add per-client onboarding context aggregation
