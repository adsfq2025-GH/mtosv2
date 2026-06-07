[OPEN] Debug Session: monthly-touch-integrations

## Symptoms
- "Generate Monthly Touch" button (top right on Client page) does nothing when clicked
- Integrations (ClickUp, Google Ads, other Google services) appear connected but no data is pulled anywhere; only Gemini works

## Expected
- Clicking "Generate Monthly Touch" triggers a request and produces a new Monthly Touch output (or an actionable error)
- Connected integrations successfully pull data; if a source is unavailable, UI shows explicit “Data Not Available” with error detail

## Hypotheses (falsifiable)
- H1: The button click fires but the frontend request fails (JS error, wrong endpoint, blocked by auth/CORS)
- H2: The button click never triggers the handler due to a disabled/overlay element or wrong component wiring
- H3: Backend rejects requests because frontend points to the wrong backend URL / missing auth token / tenant mismatch
- H4: Integration tokens exist but refresh/access token exchange fails (401/403) or tenant scoping prevents reading stored tokens
- H5: Data pulls run but connector calls error (rate limit, missing mapping IDs), and errors are swallowed so UI appears to do nothing

## Evidence to collect
- Frontend: click event + network request details for Generate Monthly Touch
- Backend: request/response logs for the generate endpoint + integration fetch endpoints (status codes, error details)
- Integration-specific: availability state + which credential record was selected (tenant_id, user_id)

## Repro steps
1) Open a client detail page
2) Click "Generate Monthly Touch"
3) Go to Integrations and confirm ClickUp + Google are connected
4) Trigger any manual “sync”/“refresh” actions that should pull data

## Notes
- Do not use demo/fake data; prefer “Data Not Available” with explicit source availability/errors

