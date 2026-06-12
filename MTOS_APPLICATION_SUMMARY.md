# MTOS Application Summary

## Overview
MTOS, short for **Monthly Touch OS**, is a multi-tenant client success and meeting operations platform built for agencies and service businesses. Its purpose is to help teams prepare for recurring client meetings, capture outcomes, turn conversations into follow-up work, and keep client accounts organized in one operating system.

The application combines account management, meeting preparation, action tracking, integrations, AI-assisted analysis, white-label controls, and a documentation hub into a single workflow-oriented product.

## Purpose
The main goal of MTOS is to make recurring client management more consistent and measurable. It is designed to help a team:

- organize clients, meetings, owners, and account health in one place
- generate structured monthly meeting briefs before a call
- analyze transcripts and meeting outcomes after a call
- turn recommendations and discussion points into action items
- track wins, issues, opportunities, testimonials, and strategy themes over time
- connect external tools so meeting prep and follow-up can pull from live operational data
- support multiple tenants with separate branding, settings, domains, and memberships

In practical terms, MTOS acts as a client success cockpit for agencies that run regular account review meetings and need a repeatable process around preparation, execution, follow-up, and reporting.

## Core Features

### Client Management
MTOS keeps a central client record for each account, including:

- client identity and company details
- contact and location data
- assigned account manager
- services and assigned products
- notes and CRM-style metadata
- account health, churn risk, and sentiment indicators
- suggestions and alert indicators for feedback or health issues

### Meetings and Monthly Touch Workflow
The product is built around recurring client meetings, especially monthly touchpoints. It supports:

- creating and listing meetings
- storing meeting status, schedule, duration, and account owner
- generating AI-assisted meeting briefs
- tracking wins, issues, talking points, suggested questions, and strategic recommendations
- storing KPI snapshots and recap content
- analyzing transcripts after meetings
- recording feedback and meeting scores

### Action Items and Follow-Up
MTOS turns meeting outcomes into accountable work. It includes:

- action item creation and updates
- owners, due dates, priority, and status tracking
- follow-up views for open and overdue tasks
- linking action items to clients and meetings
- automation-draft follow-up conversion into action items

### Opportunity, Content, and Testimonial Capture
The application can surface reusable marketing and growth opportunities from meetings, including:

- content opportunities
- testimonial captures
- follow-up opportunities
- strategic recommendations that can be routed into later work

### Integrations
The platform includes a dedicated integrations area for operational and marketing tooling. Based on the current codebase, it supports patterns for:

- Google-connected services
- ClickUp
- GoHighLevel
- Google Analytics and Search Console related flows
- calendar and meeting-related Google services
- integration diagnostics and connection testing

The integrations area is meant to power richer KPI snapshots, account context, and downstream workflow automation.

### White Label and Tenant Controls
MTOS includes multi-tenant configuration and white-label capabilities such as:

- tenant settings
- branding controls
- terminology overrides
- workflow configuration
- tenant domains and white-label setup
- tenant membership and role-based access

### AI Visibility and Intelligence
The app includes an AI visibility feature set aimed at tracking how a client appears across AI-driven discovery surfaces. This includes:

- AI visibility configuration per client
- keyword and market-based scanning
- share-of-voice style analysis
- competitor and prompt-based intelligence
- territory and content intelligence outputs

### Dashboard Wiki and Internal Documentation
There is a built-in documentation hub that acts as an internal knowledge surface for dashboard users. It supports:

- structured docs categories
- document summaries
- in-app access to operational documentation

### Search and Operator UI
The frontend includes a search-first experience across:

- clients
- meetings
- wiki pages

This supports fast navigation for operators managing many accounts and meetings.

## How MTOS Works

### 1. User Access and Tenant Context
Users log in through the authentication flow and are loaded into a tenant-aware context. Once authenticated, the app determines:

- who the user is
- what role they have
- which tenant they belong to
- what client and meeting data they are allowed to access

Protected frontend routes are wrapped in an auth layer, and the backend resolves current context before serving tenant-scoped data.

### 2. Frontend Application Flow
The frontend is a React single-page application. After login, the user lands in a dashboard layout with navigation to the main operating areas:

- Dashboard
- Clients
- Meetings
- Wins Library
- Issues Library
- Action Items
- Follow-Up
- Opportunities
- Testimonials
- Strategy
- Integrations
- White Label
- Dashboard Wiki
- AI Visibility for admin users

Each page calls API functions from the frontend data layer and renders a workflow-specific view for operators.

### 3. Backend API Layer
The backend is built with FastAPI and exposes REST-style endpoints under `/api`. It is responsible for:

- authentication and current-user context
- tenant-aware access control
- CRUD operations for clients, meetings, actions, settings, and related entities
- integration configuration and testing
- transcript analysis and AI-generated outputs
- white-label and tenant settings
- docs delivery and diagnostics

### 4. Data and Runtime Flow
The data model is centered on:

- tenants
- tenant memberships
- tenant settings
- clients
- meetings
- action items
- integrations
- client integration bindings
- user OAuth accounts

The codebase also includes a runtime bridge layer and Supabase migration set that support the platform’s current data architecture and phased runtime operation. In effect, the application logic is written around stable domain models while the backend bridge coordinates how those records are resolved and stored.

### 5. AI-Assisted Workflows
AI is used to enrich client success operations rather than replace them. Current AI-assisted flows include:

- meeting brief generation
- transcript analysis
- strategy and recommendation generation
- AI visibility analysis
- issue and win extraction
- follow-up suggestion generation

These workflows typically start with client and meeting context, combine it with KPI or transcript data, and produce structured outputs that operators can review and act on.

### 6. Integrations and Automation
External systems are used to enhance context and downstream execution. Depending on the flow, integrations are used to:

- pull account or performance data
- establish OAuth-based connections
- link clients to external platforms
- push action-oriented outputs into connected systems

This makes MTOS both a source of truth for meeting operations and a control center for connected account workflows.

## Application Structure

## Top-Level Layout

### `frontend/`
Contains the React application.

- `src/App.js`: route registration and protected route setup
- `src/Layout.jsx`: sidebar, navigation, search, and global shell
- `src/pages/`: main product pages like Dashboard, Clients, Meetings, Integrations, White Label, AI Visibility, and libraries
- `src/api.js`: frontend API client layer
- `src/auth.jsx`: frontend auth provider and auth helpers
- `src/lib/supabase.js`: Supabase client wiring on the frontend
- `public/index.html`: main browser entry document

### `backend/`
Contains the FastAPI application and domain logic.

- `server.py`: primary API entrypoint and route definitions
- `auth.py`: authentication, token creation, membership resolution, and request context
- `models.py`: domain models for users, tenants, clients, meetings, action items, and more
- `runtime_bridge.py`: runtime data bridge methods across core entities
- `oauth_runtime.py`: OAuth state and token runtime helpers
- `connectors.py`: integration-related helper logic
- `monthly_touch.py`: monthly touch meeting generation workflow
- `clickup_client_sync.py`: ClickUp-related sync workflow
- `ai_visibility.py` and `ai_territory_intelligence.py`: AI visibility and territory intelligence logic
- `integrations_meta.py`: integration catalog metadata
- `docs_content.py`: in-app wiki content definitions

### `supabase/`
Contains SQL migrations and database structure for the platform.

- `migrations/001...012`: additive schema migrations for tenancy, profiles, clients, meetings, integrations, bridge support, and action items

### `memory/`
Contains product and planning artifacts, including PRD-style documentation.

### `test_reports/` and `backend/tests/`
Contain automated test outputs and backend test coverage for runtime bridge and OAuth-related behavior.

## Frontend Structure
The frontend is organized around product surfaces and reusable UI:

- page-level screens under `src/pages`
- shared UI components under `src/components/ui`
- auth and routing at the app shell level
- API communication through a dedicated client file
- utility and environment helpers under `src/lib`

This structure makes the UI modular and page-driven while keeping domain operations close to the screens that use them.

## Backend Structure
The backend is organized by domain responsibilities:

- request entry and route handling in `server.py`
- security and user context in `auth.py`
- data contracts in `models.py`
- integration orchestration in `connectors.py`
- workflow engines in files such as `monthly_touch.py`
- migration and bridge support through `runtime_bridge.py` and SQL migrations

This allows the app to support a fairly broad product surface while keeping major concerns separated by responsibility.

## Technology Stack
Based on the current repository:

- **Frontend:** React, React Router, Tailwind CSS, Radix UI, React Query, Axios
- **Backend:** FastAPI, Pydantic, Uvicorn, HTTPX
- **Auth and Data Platform:** Supabase
- **AI and Processing:** OpenAI integration plus custom AI workflow modules
- **Testing and Tooling:** Pytest, CRACO, ESLint, Tailwind tooling

## In Summary
MTOS is a multi-tenant client success operating system focused on recurring client meetings and the work that follows them. It helps teams prepare for meetings, analyze outcomes, capture opportunities, create action items, manage integrations, and operate from a single tenant-aware dashboard.

Its structure is split cleanly between:

- a React frontend for operator workflows
- a FastAPI backend for API logic and orchestration
- a Supabase-backed data and migration layer for tenant and business entities
- dedicated workflow modules for AI, meeting generation, integrations, and follow-up operations

The overall product is best understood as a meeting-centered operating system for agencies that need consistent client communication, actionable follow-up, and stronger visibility into account health and growth opportunities.
