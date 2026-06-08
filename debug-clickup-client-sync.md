[OPEN] Debug Session: clickup-client-sync

## Symptoms (User Report)
- ClickUp “Sync Clients” still not importing contacts per Account Manager.
- UI sometimes shows “Network Error” when refreshing sync status.

## Expected
- Each account manager imports only their assigned clients from ClickUp Client Health Tracker.
- Imports update automatically when new clients are added (scheduled sync).

## Hypotheses
1) Status endpoint request fails in browser (CORS/timeout/cold start), producing Axios “Network Error”.
2) Sync runs but finds 0 assigned tasks because “Account Manager” field value format doesn’t match logged-in user.
3) Configured list id is wrong/not accessible with current ClickUp token, so sync aborts early.
4) ClickUp token/team_id is missing/invalid in stored integration credentials, causing sync to fail.
5) Sync succeeds but created/updated clients are not visible because client list is filtered/scoped differently than expected.

## Evidence To Collect
- Frontend: API base URL, request errors (status + sync), response timing.
- Backend: clickup sync run inputs (tenant/user/list_id), task counts, extracted AM values, match results, failure reasons.

## Plan
1) Instrument frontend + backend with debug events to a local debug server.
2) Reproduce “Sync Now” + “Refresh Status”.
3) Analyze logs to confirm root cause.
4) Implement minimal fix and verify with post-fix logs.

