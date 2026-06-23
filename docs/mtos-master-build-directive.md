# MTOS Master Build Directive

This document is the in-repo product directive for MTOS and overrides older product assumptions when there is a conflict.

## Product Identity

- MTOS stands for Monthly Touch Operating System.
- MTOS is an internal AI-powered operating system for Map Ranking's account management organization.
- MTOS is not a generic CRM, not a sales platform, and not a lead management platform.
- MTOS exists to improve retention, reduce churn, raise meeting quality, improve preparation, strengthen accountability, improve follow-through, and reduce administrative workload.

## Architecture Direction

- Single-tenant today for Map Ranking.
- Multi-tenant ready in data design and permissions.
- PostgreSQL is the system-of-record target.
- Supabase Auth is the active authentication target in the current codebase.
- ClickUp Client Health Tracker is the ownership source of truth.
- AI workflows must follow a Gemini collection layer and a Claude reasoning layer where possible.

## Core Engines

All product workflows should align to these engines:

1. Client Sync and Ownership Engine
2. Pre-Meeting Intelligence Engine
3. Live Meeting Execution Engine
4. Post-Meeting Automation Engine

## Ownership Rules

- Account Managers only see assigned clients.
- Team leads see team clients.
- Department admins see department clients.
- Super admins see everything.
- Ownership must drive visibility, brief generation, scheduling, reporting, ticket routing, retention analysis, and AI workflows.

## Monthly Touch Rules

- A Monthly Touch is a strategic business review meeting.
- It is not a generic reporting call.
- It must communicate value, surface risks, create alignment, build trust, and drive growth.
- Each meeting should cover discovery, wins, performance, issues, recommendations, client questions, a 30-day plan, recap, and next-meeting scheduling.
- A Monthly Touch should not be considered complete until the next Monthly Touch is scheduled.

## Prompt Management

- Prompt behavior should be editable by admins without deployment.
- Prompt management should cover brief, audit, ticket, email, QA, coaching, and retention flows.

## Current Codebase Note

The current repository is still in transition toward this target. The active implementation should continue moving away from hybrid Mongo or bridge behavior and toward a Supabase-native PostgreSQL system aligned to this directive.
