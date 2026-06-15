# Debug Session: google-oauth-disconnect

Status: OPEN

Symptom:
- Clicking Disconnect on the Google OAuth card does not clear the connected state.
- User observed API response: `{"detail":"OAuth token storage is unavailable. Connection was not finalized safely."}`

Hypotheses:
1. The frontend is invoking the Google per-user OAuth disconnect endpoint for the `google_oauth` platform, which is incompatible with the Google OAuth app config card.
2. The backend disconnect path for Google OAuth depends on runtime OAuth token storage that is disabled or unavailable.
3. The Google OAuth card status is derived from saved integration config, so deleting user OAuth tokens would not change the card from connected.
4. The backend generic integration delete succeeds, but the UI reload still derives status from a different runtime source and shows stale state.

Next Steps:
- Find the exact source of the error string.
- Map which disconnect endpoint the Google OAuth card is calling.
- Verify how the Google OAuth card status is computed.
- Apply the smallest fix after evidence confirms the failing path.

Findings:
- The screenshot error string is raised in the Google OAuth callback when `write_google_oauth_token(...)` fails: `backend/server.py` and `backend/oauth_runtime.py`.
- Google per-user token writes/disconnects only use the runtime bridge/Supabase `oauth_accounts` store; there is no Mongo fallback.
- If `oauth_accounts` mirror is disabled, token write/disconnect returns `ok: false`.
- The `Google OAuth` integration card represents saved OAuth app credentials (`client_id`, `client_secret`, `redirect_uri`), not the per-user Google connection token state.

Likely Root Cause:
- Runtime bridge token storage for `oauth_accounts` is disabled, misconfigured, or missing tenant/user mapping.
- Because of that, Connect Google and Disconnect Google cannot safely persist token changes.
- Separately, the Google OAuth app config card can still appear connected because its status comes from saved integration credentials, which is a different state.
