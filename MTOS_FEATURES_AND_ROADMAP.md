# MTOS Features and Planned Updates

## Overview
MTOS, short for **Monthly Touch OS**, is a multi-tenant client success and meeting operations platform for agencies and service businesses. It is designed to help teams manage client relationships, prepare for recurring meetings, analyze outcomes, create follow-up work, and operate from one tenant-aware dashboard.

This document lists:

- current MTOS features visible in the codebase
- planned and in-progress updates documented in the repo

## Current Features

### 1. Multi-Tenant Platform Foundation
- tenant-aware authentication and protected routes
- tenant memberships and role-based access
- tenant settings and workspace-specific configuration
- tenant branding, terminology, and workflow customization
- tenant domain and white-label support

### 2. Dashboard and Navigation
- dashboard home for operators
- global layout with sidebar navigation
- search across clients, meetings, and docs
- dedicated product areas for clients, meetings, action items, follow-up, opportunities, testimonials, strategy, integrations, white label, docs, and AI visibility

### 3. Client Management
- client list and detail pages
- company identity and contact records
- location and service metadata
- assigned account manager tracking
- health score, churn risk, and sentiment indicators
- CRM-style notes and account context
- suggestions, alerts, and review-related client data
- per-client integration bindings

### 4. Meetings and Monthly Touch Workflow
- create, list, and manage meetings
- recurring monthly touch workflow support
- meeting status, schedule, and duration tracking
- meeting detail pages
- meeting brief generation
- KPI snapshot support
- recap content generation
- transcript analysis
- meeting scoring and feedback support
- suggested questions and strategic talking points

### 5. Action Items and Follow-Up
- create and update action items
- assign owners, due dates, priorities, and statuses
- link action items to meetings and clients
- view open, overdue, and upcoming work
- follow-up dashboard for operational next steps
- convert automation-drafted follow-up into action items

### 6. Wins, Issues, Opportunities, Testimonials, and Strategy
- wins library
- issues library
- opportunity capture views
- testimonial capture feed
- strategy and recommendation feed
- searchable operational history across meeting-derived outputs

### 7. Integrations
- dedicated integrations management UI
- secure credential entry and storage patterns
- connection status and verification flows
- connect, disconnect, and test workflows
- Google OAuth support
- ClickUp integration paths
- GoHighLevel integration paths
- Google Ads integration paths
- Google Business Profile integration paths
- Google Analytics 4 integration paths
- Google Search Console integration paths
- Meta Ads integration paths
- Ahrefs integration paths
- Google Drive integration paths
- Google Meet integration paths
- Google Calendar integration paths
- Gmail-related integration paths
- Google Local Services Ads integration paths
- Map Check-ins integration spec support

### 8. AI-Assisted Workflows
- AI meeting brief generation
- AI transcript analysis
- AI recommendation and strategy generation
- issue and win extraction
- follow-up suggestion generation
- admin-only AI Visibility module
- client-level AI visibility configurations
- keyword and market scanning
- inferred brand and domain handling
- scan history and run history
- share-of-voice style analysis
- competitor discovery and prompt intelligence
- territory intelligence outputs

### 9. White Label and Internal Documentation
- white-label settings center
- branding and terminology controls
- workflow settings controls
- custom domain support
- document upload support in white-label flows
- AI-assisted settings analysis
- built-in dashboard documentation hub
- internal SOPs, playbooks, checklists, frameworks, and specs available inside the product

### 10. Automation and Background Workflows
- ClickUp client sync workflow
- per-user sync status and logs for ClickUp sync
- sync-all tenant job paths
- meeting and follow-up automation support
- runtime bridge architecture for phased data runtime operation
- Supabase-backed runtime domains for key entities and workflow modules

## Current Feature Notes

### Integrations State
The codebase shows that MTOS already supports integration management, credential handling, connection testing, and OAuth flows. Some integrations also have documented future live data-pull work that is still planned rather than fully activated everywhere.

### AI Visibility State
The AI Visibility and territory intelligence surface is real and implemented in the product, with active backend logic, admin UI, scan history, and persistence layers.

### Data Platform State
MTOS already includes a Supabase migration and runtime bridge architecture for tenants, clients, meetings, integrations, action items, ClickUp sync state, and AI visibility runtime data.

## Planned and Future Updates

The following planned work is documented in the repo roadmap, product docs, migration work, and test reports.

### 1. Planned Integration Activations
- activate live ClickUp data pulls and deeper sync behavior
- activate live GoHighLevel data flows
- activate live Google Ads data pulls
- activate live Google Business Profile data pulls
- activate live Google Analytics 4 data pulls
- activate live Google Search Console data pulls
- activate live Google Local Services Ads data pulls
- activate live Meta Ads data pulls
- activate live Ahrefs data pulls
- activate Google Drive-based onboarding data aggregation
- activate Google Meet transcript ingestion workflows
- expand Google Workspace-connected automation
- implement Map Check-ins integration workflows from the documented spec

### 2. Product and UX Backlog
- replace the current native date-time picker with a better shadcn-style date-time picker
- add KPI history charts
- add or improve admin user management UI
- add command palette support
- improve empty states across the app
- add a production-safe bootstrap hint flow

### 3. Email, Communication, and Workflow Enhancements
- add Gmail send functionality
- expand recap and follow-up workflows
- improve recap refresh behavior after recap email generation
- continue improving discovery-question and meeting automation flows

### 4. Scoring, Reporting, and Analytics Enhancements
- add cron-based health recompute workflows
- expand QA scorecard functionality
- continue improving KPI history and reporting surfaces
- extend analytics tied to integrations and meeting outcomes

### 5. Automation and Integration Specs Already Defined
- Google Meet plus Drive workflow that polls recordings/transcripts and feeds AI analysis
- Map Check-ins automation that triggers scans and derived outputs from location signals
- broader monthly touch operating-system automation patterns described in the planning docs

### 6. In-Progress Platform Architecture Updates
- continue staged migration of runtime domains onto Supabase
- finish runtime cutover of remaining legacy-backed modules
- continue OAuth runtime cleanup
- continue replacing remaining direct legacy persistence paths with bridge-backed Supabase paths
- run verification for full no-legacy backend operation once cutover is complete

### 7. Quality and Polish Work
- fix recap tab refresh after generating recap email
- resolve remaining docs-page test flow issues
- improve frontend tab and test-id consistency where called out in test reports

## Practical Roadmap Order

Based on the current repo planning, the intended rollout order is:

1. activate integrations one by one
2. start with ClickUp
3. continue with GoHighLevel
4. continue with Google Workspace and related Google service flows
5. expand KPI, reporting, QA, and workflow polish
6. finish the Supabase-first runtime cutover

## Source Basis

This file is based on the current repository and the main planning artifacts, including:

- `MTOS_APPLICATION_SUMMARY.md`
- `memory/PRD.md`
- `backend/docs_content.py`
- `backend/integrations_meta.py`
- `backend/server.py`
- `backend/ai_visibility.py`
- `backend/ai_territory_intelligence.py`
- `backend/clickup_client_sync.py`
- `backend/runtime_bridge.py`
- `backend/supabase_config.py`
- `supabase/migrations/`
- `test_reports/iteration_2.json`

## Summary
MTOS already includes a broad product surface covering client management, meetings, AI-assisted preparation and follow-up, action tracking, integrations, white-label controls, internal docs, AI visibility, and automation workflows.

Its main future updates are focused on:

- activating more live integration data flows
- improving reporting, QA, and operational UX
- expanding automation around Google, ClickUp, and Map Check-ins
- finishing the Supabase-first backend cutover and remaining runtime cleanup
