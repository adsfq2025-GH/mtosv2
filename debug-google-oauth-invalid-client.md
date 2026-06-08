[OPEN] Debug Session: google-oauth-invalid-client

## Symptoms (User Report)
- Connecting Google Business Profile (and other Google sources) fails.
- Popup shows: oauth_http_401: invalid_client.

## Hypotheses
1) Google OAuth client_id/client_secret mismatch (e.g., client_id overridden in Integrations → Google OAuth but secret still coming from backend env).
2) Redirect URI mismatch between what MTOS sends and what’s configured in Google Cloud OAuth client.
3) Wrong Google OAuth client is being selected due to tenant override logic (env vs Integrations → Google OAuth precedence).
4) OAuth callback is reached with stale/invalid state and client attempts token exchange with wrong tenant config.
5) Google OAuth credentials in backend env are missing/empty in production and tenant integration config is incomplete.

## Evidence Needed
- Which OAuth config source is used (env vs tenant integration) for client_id, client_secret, redirect_uri.
- The redirect_uri host+path (no secrets).
- Token endpoint error payload from Google (error + description).

