[OPEN] Debug Session: integrations-no-data

## Symptoms (User Report)
- Integrations show “connected” but nothing pulls data.
- AI & Territory Intelligence says nothing is connected / Data Not Available.
- Wins / Issues / Recommendations not populating.
- ClickUp clients not importing for account managers.

## Hypotheses
1) Client-level bindings missing (e.g., GBP binding per client), so features correctly report unavailable even though OAuth is connected.
2) Tenant scoping mismatch: integration credentials exist but are not found due to tenant_id isolation, so connectors return “not connected”.
3) Background jobs run but fail silently; UI shows empty because endpoints do not surface last_error/run diagnostics.
4) Brief generation is not triggered/working, so Wins/Issues remain empty by design.
5) OAuth tokens exist but expired/invalid; refresh fails and is not surfaced to UI.

## Evidence Needed
- For a selected client: source availability + missing prerequisites (GBP binding, GSC binding, Ads customer id, etc).
- For ClickUp sync: resolved list_id + sample Account Manager field values + assigned count.
- For Wins/Issues/Recommendations: whether a brief exists for the meeting and whether KPI snapshot is available.

