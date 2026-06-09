# Debug Session: google-login-blankpage

Status: OPEN

Symptoms:
- Google login does not allow the user to sign in.
- Another route in the app is still producing a blank white page.

Scope:
- Frontend Google auth bootstrap and callback flow.
- Backend Google credential validation.
- Protected route render path and auth bootstrap.

Hypotheses:
- A: Frontend Google Identity initialization uses a malformed client ID or never renders the Google button.
- B: Backend `/auth/google` rejects a valid Google credential because the audience check is comparing against a bad client ID value.
- C: The blank page is caused by a route rendering `.map()` or equivalent on a non-array payload.
- D: Auth bootstrap or axios 401 handling is wiping auth state due to an API error unrelated to real authentication.
- E: Integration/status payload shape mismatch is crashing the protected route before visible UI renders.

Plan:
1. Start debug server for this session.
2. Add instrumentation only to auth bootstrap, Google login callback, auth restore, and the failing page load path.
3. Reproduce the failures and collect pre-fix evidence.
4. Implement the smallest fix supported by evidence.
5. Reproduce again and compare post-fix evidence.
